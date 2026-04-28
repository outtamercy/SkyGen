import hashlib, time, os, configparser, shutil, re
from pathlib import Path
from typing import Dict, Set, Optional, Any, List, Tuple
from dataclasses import dataclass, asdict, field
import configparser
import subprocess
from PyQt6.QtCore import QObject, pyqtSignal, QThread  
from .logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_DEBUG, MO2_LOG_WARNING
from .bl_mgr import BlacklistManager, ModStatus  # Runtime import
from .sigsnoop import PluginDNA, quick_sniff, batch_sniff
from ..core.constants import (
    BASE_GAME_PLUGINS, BLACKLIST_AUTHORS, BOS_RECORD_MAP, SP_RECORD_MAP,
    DATA_DIR_NAME, COLOR_LOCKED, ICON_USER_BL, ICON_STARRED, ICON_PARTIAL, 
    COLOR_ACTIVE, ICON_LOCKED, ICON_NONE, BLESSED_CORE_FILES, PROTECTED_AUTHORS, 
    OFFICIAL_CC_PREFIX, BLESSED_HASH_PREFIX, CURRENT_APP_VERSION, 
    CURRENT_EXTRACTION_LOGIC_VERSION, COLOR_HIDDEN, COLOR_PARTIAL, COLOR_ACTIVE, 
    COLOR_USER_BL, COLOR_LOCKED, COLOR_STARRED, ICON_BLESSED, hash_file_head, 
    GLOBAL_IGNORE_PLUGINS, BLACKLIST_KEYWORDS
)
from .learning_core import LearningCore, Layer

@dataclass
class ManifestEntry:
    file_hash: str; mtime: float; size: int; author: str
    signatures: Set[str]; masters: List[str]
    object_signatures: Set[str] = field(default_factory=set)
    logic_signatures: Set[str] = field(default_factory=set)
    logic_to_content_ratio: float = 0.0
    folder_scents: Set[str] = field(default_factory=set)
    is_framework: bool = False; framework_reason: str = ""
    is_blessed: bool = False; is_partial: bool = False
    lo_index: int = -1          # <-- FIX: LO slot for FormID math
    layer: str = "hybrid"       # <-- FIX: global/bos/sp/hybrid from LC
    lc_score: int = 50          # <-- FIX: 0-100 framework score
    lc_confidence: str = "low"  # <-- FIX: high/medium/low

class ProfileManager(QObject, LoggingMixin):
    """
    Owns raw data acquisition from OrganizerWrapper.
    Zero lazy init - paths resolved by Wrapper on init.
    """
    
    silo_data_ready = pyqtSignal(str, object)  # was 'list', now 'object' so dicts flow through
    scan_complete = pyqtSignal(bool)  # <-- ADD: Class-level signal
    scan_progress = pyqtSignal(str, int)

    def __init__(self, organizer_wrapper: Any, plugin_path: Path) -> None:
        QObject.__init__(self)
        LoggingMixin.__init__(self)
        
        self.wrapper = organizer_wrapper
        self.plugin_path = plugin_path
        self.data_dir = plugin_path / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Paths resolved by wrapper - no lazy init needed
        self._manifest_path = self.data_dir / f"skygen_manifest_{self.wrapper.profile_name}.ini"
        self._manifest: Dict[str, ManifestEntry] = {}
        self._plugin_to_mod_bridge: Dict[str, str] = {}
        self._is_scanning = False
        self._refresh_attempted = False
        self.blacklist_mgr: Optional['BlacklistManager'] = None
        self.learning_core = LearningCore(plugin_path, self.wrapper.profile_name) 

    @property
    def manifest_path(self) -> Path:
        """Manifest path resolved from wrapper profile_name."""
        return self._manifest_path

    def _get_loadorder_signature(self) -> str:
        """MO2-proof hash of plugin sequence. Ignores header comments."""
        plugins = self.wrapper.read_loadorder_txt()
        
        # Filter out empty lines and comments, keep order
        clean_plugins = []
        for p in plugins:
            p = p.strip()
            if p and not p.startswith('#'):
                clean_plugins.append(p.lower())  # Normalize case
        
        # Hash the sequence
        sequence = "|".join(clean_plugins)
        sig = hashlib.sha256(sequence.encode()).hexdigest()[:16]
        
        self.log_debug(f"Load order signature: {sig} ({len(clean_plugins)} plugins)")
        return sig

    @property
    def load_order_signature(self) -> str:
        """Exposed for main_dialog welcome seal checks."""
        return self._get_loadorder_signature()

    def get_load_order_map(self) -> Dict[int, str]:
        """Build index-to-plugin map from loadorder.txt - zero API calls."""
        lo_path = self.wrapper.profile_dir / "loadorder.txt"
        
        lo_map = {}
        idx = 0
        
        if not lo_path.exists():
            self.log_warning("No loadorder.txt found - returning empty map")
            return lo_map
        
        try:
            with open(lo_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and blank lines
                    if not line or line.startswith('#'):
                        continue
                    
                    lo_map[idx] = line
                    idx += 1
                    
        except Exception as e:
            self.log_error(f"Failed to slurp loadorder.txt: {e}")
            return {}
        
        self.log_debug(f"LO map built: {len(lo_map)} entries (0-4 should be base masters)")
        return lo_map


    def refresh_silos(self) -> None:
        """Single entry point. Checks silo cache first, falls back to manifest scan."""
        if self._refresh_attempted:
            return
        self._refresh_attempted = True
        
        # Ensure audit cache exists (regenerate if stale/missing)
        if not self._get_audit_cache_path().exists():
            self.log_info("Audit cache missing, will generate after silo check")
            need_audit_gen = True
        else:
            need_audit_gen = False
            
        current_sig = self._get_loadorder_signature()
    
        # Try silo cache first (fastest)
        if self._is_silo_cache_valid(current_sig):
            self.log_info("Silo cache valid, loading filtered lists from disk")
            
            # Cache path leaves manifest empty — hydrate it for audit/BL
            if not self._manifest and self._manifest_path.exists():
                self.load_manifest()
                # Cache path skipped _build_manifest_and_emit — bridge never got built
                self._plugin_to_mod_bridge = self.build_plugin_to_mod_bridge() 
                
            # Audit cache only if missing — otherwise on-demand when Auditor opens
            if not self._get_audit_cache_path().exists():
                self.generate_audit_cache()
                        
            cache = self._load_silo_cache()
            if cache:
                # Emit rich objects directly - no sparse conversion
                self.silo_data_ready.emit("SP", cache.get("SP", {}))
                self.silo_data_ready.emit("BOS_MODS", cache.get("BOS_MODS", {}))
                self.silo_data_ready.emit("BOS_PLUGINS", cache.get("BOS_PLUGINS", {}))
                self.scan_complete.emit(True)
                return
    
        # Try manifest fast-load
        if self._manifest_path.exists():
            self.load_manifest()
            if self._manifest and not self._is_manifest_stale():
                self.log_info("Manifest fresh, fast-loading silos")
                self._emit_all_silos()
                self.scan_complete.emit(True)
                return
    
        # Full rebuild
        self.log_info("Silo cache stale or missing, building from disk...")
        self._build_manifest_and_emit()

    def _is_manifest_stale(self) -> bool:
        """Triple-lock cache invalidation."""
        if not self._manifest_path.exists():
            return True
        
        try:
            config = configparser.ConfigParser(strict=False)
            config.read(self._manifest_path, encoding='utf-8')
            
            stored_sig = config.get('_meta', 'loadorder_signature', fallback='')
            stored_logic_ver = config.getint('_meta', 'extraction_logic_version', fallback=1)
            stored_app_ver = config.get('_meta', 'app_version', fallback='0.0.0')
            
            # LOCK 1: Plugin sequence changed
            if stored_sig != self._get_loadorder_signature():
                self.log_info("TRIPLE_LOCK: Load order signature mismatch")
                return True
            
            # LOCK 2: Scan logic updated
            if stored_logic_ver < CURRENT_EXTRACTION_LOGIC_VERSION:
                self.log_info(f"TRIPLE_LOCK: Logic version {stored_logic_ver} < {CURRENT_EXTRACTION_LOGIC_VERSION}")
                return True
            
            # LOCK 3: App updated
            if stored_app_ver != CURRENT_APP_VERSION:
                self.log_info(f"TRIPLE_LOCK: App version {stored_app_ver} != {CURRENT_APP_VERSION}")
                return True
            
            # LOCK 4: Manifest truncated from crash — force rebuild
            lo_map = self.get_load_order_map()
            plugin_sections = [s for s in config.sections() if not s.startswith('_')]
            if len(plugin_sections) < len(lo_map) * 0.3:
                self.log_info(f"TRIPLE_LOCK: Manifest truncated ({len(plugin_sections)}/{len(lo_map)} plugins)")
                return True
            
            return False
            
        except Exception:
            return True

    def _emit_all_silos(self) -> None:
        """Emit rich dicts - full ManifestEntry objects flowing downstream."""
        if not self._manifest:
            self.log_warning("EMIT_SILOS: Manifest empty, nothing to emit")
            return
        
        # Build rich dicts from manifest
        sp_rich = self._filter_sp_silo(list(self._manifest.keys()))
        bos_mods_rich, bos_plugins_rich = self._filter_bos_silo(list(self._manifest.keys()))
        
        self.log_info(
            f"EMIT_RAW: SP={len(sp_rich)}, BOS_MODS={len(bos_mods_rich)}, "
            f"BOS_PLUGINS={len(bos_plugins_rich)}"
        )
        
        # Cache and emit
        current_sig = self._get_loadorder_signature()
        self._save_silo_cache(sp_rich, bos_mods_rich, bos_plugins_rich, current_sig)
        
        # Emit the rich data - let OR sort by lo_index if it wants order
        self.silo_data_ready.emit("SP", sp_rich)
        self.silo_data_ready.emit("BOS_MODS", bos_mods_rich)
        self.silo_data_ready.emit("BOS_PLUGINS", bos_plugins_rich)  # Back from retirement, but rich
        self.log_info(
            f"Emit: {len(sp_rich)} SP, {len(bos_mods_rich)} BOS mods, "
            f"{len(bos_plugins_rich)} BOS plugins"
        )
                
    def refresh_after_rule_change(self) -> None:
        """Force silo refresh when user rules change (bypasses cache)."""
        if not self._manifest:
            self.load_manifest()
        if self._manifest:
            self._emit_all_silos()
        else:
            self.refresh_silos()  # Fallback to full scan if no manifest

    def _build_manifest_and_emit(self) -> None:
        """Build manifest directly from disk, LC classifies, PM saves and emits."""
        self._is_scanning = True
        
        # Build fresh manifest from load order
        self._manifest = {}
        self._plugin_to_mod_bridge: Dict[str, str] = {}  # Cache while paths are hot
        lo_map = self.get_load_order_map()
        
        stats = {"lo_total": len(lo_map), "path_miss": 0, "empty_dna": 0, "success": 0}
        
        for idx, plugin_name in sorted(lo_map.items()):
            plugin_path = self.wrapper.get_plugin_path(plugin_name)
            if not plugin_path:
                stats["path_miss"] += 1
                continue
            
            # Build bridge entry while we have the path (zero extra disk hits)
            path = Path(plugin_path)
            if path.parent.name.lower() == 'data':
                self._plugin_to_mod_bridge[plugin_name] = plugin_name
            else:
                self._plugin_to_mod_bridge[plugin_name] = path.parent.name
                        
            # Sniff it
            dna = quick_sniff(str(plugin_path), plugin_path.parent)
            
            # <-- Raw Snoopy output
            if idx < 15:
                self.log_debug(
                    f"RAW_DNA: {plugin_name} "
                    f"sigs={len(dna.signatures)} obj={len(dna.object_signatures)} "
                    f"logic={len(dna.logic_signatures)} author={dna.author!r} "
                    f"fw={dna.is_framework} partial={dna.is_partial}"
                )            
            if not dna.signatures and not dna.masters:
                stats["empty_dna"] += 1
            else:
                stats["success"] += 1
            
            is_blessed = (plugin_name.lower() in [p.lower() for p in BLESSED_CORE_FILES] or 
                         plugin_name.lower().startswith('cc') and 'cc' in plugin_name.lower())
            
            # Build entry from DNA
            entry = ManifestEntry(
                file_hash=dna.file_hash,
                mtime=dna.mtime,
                size=dna.file_size,
                author=dna.author,
                signatures=dna.signatures,
                masters=dna.masters,
                object_signatures=dna.object_signatures,
                logic_signatures=dna.logic_signatures,
                logic_to_content_ratio=dna.logic_to_content_ratio,
                folder_scents=dna.folder_scents,
                lo_index=idx,
                is_framework=dna.is_framework,
                framework_reason=dna.framework_reason,
                is_partial=dna.is_partial,
                is_blessed=is_blessed,
                layer="global" if is_blessed else "hybrid",
            )
            
            self._manifest[plugin_name] = entry
        
        self.log_info(f"BLOOD_COUNT: {stats}")
        
        if not self._manifest:
            self.log_error("Manifest empty - no plugins found in load order")
            self._is_scanning = False
            self.scan_complete.emit(False)
            return
        
        self.log_info(f"Manifest built: {len(self._manifest)} entries from disk")
        
        # LC classification pass (unchanged from here down)
        self.log_info(f"LC_CLASSIFY: Running verdicts on {len(self._manifest)} entries...")
        for plugin_name, entry in self._manifest.items():
            # BLESSED CORE PROTECTION: Skip LC, keep hybrid for combo visibility
            if entry.is_blessed:
                entry.is_framework = False
                entry.lc_score = 0
                entry.lc_confidence = "high"
                entry.framework_reason = ""
                # layer stays 'hybrid' so they flow into SP and BOS silos
                continue
            
            dna = PluginDNA(
                signatures=entry.signatures,
                author=entry.author,
                masters=entry.masters,
                is_esm=False,
                is_esl=False,
                file_size=entry.size,
                mtime=entry.mtime,
                file_hash=entry.file_hash,
                object_signatures=entry.object_signatures,
                logic_signatures=entry.logic_signatures,
                logic_to_content_ratio=entry.logic_to_content_ratio,
                folder_scents=entry.folder_scents
            )
            
            class FakeStat:
                def __init__(self, size, mtime):
                    self.st_size = size
                    self.st_mtime = mtime
            fake_stat = FakeStat(entry.size, entry.mtime)
            
            verdict = self.learning_core.get_verdict(plugin_name, dna, fake_stat)
            
            entry.is_framework = (verdict.layer == Layer.GLOBAL)
            entry.framework_reason = verdict.reason if verdict.layer == Layer.GLOBAL else ""
            entry.layer = verdict.layer.value
            entry.lc_score = verdict.score
            entry.lc_confidence = verdict.confidence

        # Flush framework suspects to auto-blacklist
        suspects = {
            name: entry.framework_reason 
            for name, entry in self._manifest.items() 
            if entry.is_framework and entry.framework_reason
        }
        if suspects:
            self._flush_framework_batch(suspects)
            self.log_info(f"BL_FLUSH: {len(suspects)} framework plugins auto-blacklisted")  
            
        # Persist final classified 📑 manifest
        self.learning_core.force_re_save()
        self.save_manifest()
        
        # Generate audit cache so Auditor has data on fresh builds
        self.generate_audit_cache()
        
        # Filter and emit to UI
        self._emit_all_silos()
        
        self._is_scanning = False
        self.scan_complete.emit(True)
        
    def _flush_framework_batch(self, suspects: Dict[str, str]) -> None:
        """Write a batch of framework suspects to the auto-blacklist."""
        if not self.blacklist_mgr:
            return
            
        for plugin_name, reason in suspects.items():
            self.blacklist_mgr.add_auto_blacklist(plugin_name, reason)
        
        # Single disk hit for the whole batch
        if hasattr(self.blacklist_mgr, '_save_auto_blacklist'):
            self.blacklist_mgr._save_auto_blacklist()

    def _filter_sp_silo(self, all_plugins: List[str]) -> Dict[str, ManifestEntry]:
        """Return rich {plugin_name: ManifestEntry} for SP-eligible content."""
        if not self._manifest:
            self.log_warning("SP_FILTER: Manifest is empty")
            return {}
        
        if not self.blacklist_mgr:
            self.log_warning("SP_FILTER: BlacklistManager not linked")
            return {}
        
        rich_silo: Dict[str, ManifestEntry] = {}
        rejected = 0
        sample_log = 0
        
        for plugin_name, entry in self._manifest.items():
            # GLOBAL plugins stay out of SP silo unless blessed base game
            if entry.layer == "global" and not entry.is_blessed:
                continue
            
            # SINGLE SOURCE OF TRUTH: Ask BlacklistManager
            eligible = self.blacklist_mgr.is_eligible_for_silo(entry, plugin_name, 'SP')
            if not eligible:
                rejected += 1
                if sample_log < 5:
                    self.log_debug(
                        f"SP_REJECT: {plugin_name} "
                        f"layer={entry.layer} fw={entry.is_framework} "
                        f"sigs={len(entry.signatures)} obj={len(entry.object_signatures)} "
                        f"logic={len(entry.logic_signatures)}"
                    )
                    sample_log += 1
                continue
            
            rich_silo[plugin_name] = entry
        
        self.log_info(
            f"SP_FILTER: {len(rich_silo)} passed, {rejected} rejected "
            f"out of {len(self._manifest)}"
        )
        return rich_silo
        
    def _filter_bos_silo(self, all_plugins: List[str]) -> Tuple[Dict[str, ManifestEntry], Dict[str, ManifestEntry]]:
        """Return rich plugin entries for BOS-eligible mods, plus the mod→plugin mapping."""
        if not self.blacklist_mgr:
            self.log_warning("BOS_FILTER: BlacklistManager not linked")
            return {}, {}
        profile_dir = getattr(self.wrapper, 'profile_dir', None)
        if not profile_dir:
            return {}, {}
            
        modlist_path = Path(profile_dir) / "modlist.txt"
        if not modlist_path.exists():
            return {}, {}
        
        active_mods = []
        with open(modlist_path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if line.startswith('+'):
                    mod_name = line[1:].strip()
                    if mod_name and not mod_name.endswith('_separator'):
                        active_mods.append(mod_name)
        
        rich_plugins: Dict[str, ManifestEntry] = {}
        rich_mods: Dict[str, ManifestEntry] = {}
        
        mods_root = getattr(self.wrapper, 'mods_path', None)
        if not mods_root:
            return {}, {}
        
        for mod_folder in active_mods:
            # Global blacklist check (Output folders)
            if any(bl.lower() in mod_folder.lower() for bl in BLACKLIST_KEYWORDS):
                continue
            
            mod_path = Path(mods_root) / mod_folder
            found_in_mod = False
            representative_entry = None
            
            if mod_path.exists():
                for plugin_file in list(mod_path.glob("*.esp")) + list(mod_path.glob("*.esm")) + list(mod_path.glob("*.esl")):
                    plugin_name = plugin_file.name
                    entry = self._manifest.get(plugin_name)
                    if not entry:
                        continue
                    
                    # GLOBAL plugins stay out of BOS silo unless blessed base game
                    if entry.layer == "global" and not entry.is_blessed:
                        continue
                    
                    # DELEGATE to BlacklistManager
                    if not self.blacklist_mgr or not self.blacklist_mgr.is_eligible_for_silo(entry, plugin_name, 'BOS'):
                        continue
                    
                    # Content check: must have BOS-relevant signatures
                    if not entry.signatures.intersection({'ARMO', 'ARMA', 'STAT', 'MSTT', 'FURN', 'CONT'}):
                        continue
                    
                    rich_plugins[plugin_name] = entry
                    found_in_mod = True
                    if representative_entry is None:
                        representative_entry = entry
            
            if found_in_mod and representative_entry:
                rich_mods[mod_folder] = representative_entry
        
        # Inject blessed plugins (Data/ folder) - they live outside modlist
        for blessed_name in BLESSED_CORE_FILES:
            entry = self._manifest.get(blessed_name)
            if entry and blessed_name not in rich_plugins:
                rich_plugins[blessed_name] = entry
                rich_mods[blessed_name] = entry
        
        return rich_mods, rich_plugins

    def build_plugin_to_mod_bridge(self) -> Dict[str, str]:
        """Return pre-built bridge from scan. Zero disk hits."""
        if not self._plugin_to_mod_bridge and self._manifest:
            # Fallback only if cache missed (shouldn't happen)
            self.log_debug("Bridge cache empty, rebuilding from manifest")
            for plugin_name in self._manifest.keys():
                plugin_path = self.wrapper.get_plugin_path(plugin_name)
                if plugin_path:
                    path = Path(plugin_path)
                    self._plugin_to_mod_bridge[plugin_name] = (
                        plugin_name if path.parent.name.lower() == 'data' 
                        else path.parent.name
                    )
        self.log_debug(f"Bridge returned: {len(self._plugin_to_mod_bridge)} entries")
        return self._plugin_to_mod_bridge

    def _get_silo_cache_path(self) -> Path:
        """Path to silo cache file."""
        return self.data_dir / f"skygen_silos_{self.wrapper.profile_name}.ini"

    def _save_silo_cache(self, sp_entries: Dict[str, ManifestEntry], 
                         bos_mods: Dict[str, ManifestEntry],
                         bos_plugins: Dict[str, ManifestEntry],
                         signature: str) -> None:
        """Write rich v3 format - one section per plugin with full DNA."""
        cache_path = self._get_silo_cache_path()
        try:
            config = configparser.ConfigParser()
        
            # Meta section - mark as rich v3
            config.add_section('_meta')
            config.set('_meta', 'loadorder_signature', signature)
            config.set('_meta', 'saved_at', str(time.time()))
            config.set('_meta', 'profile', self.wrapper.profile_name)
            config.set('_meta', 'format', 'rich_v3')
            config.set('_meta', 'sp_count', str(len(sp_entries)))
            config.set('_meta', 'bos_mod_count', str(len(bos_mods)))
            config.set('_meta', 'bos_plugin_count', str(len(bos_plugins)))
        
            # Helper to dump a ManifestEntry into a section
            def dump_entry(section: str, entry: ManifestEntry, silo_type: str):
                config.add_section(section)
                config.set(section, 'hash', entry.file_hash or '')
                config.set(section, 'mtime', str(entry.mtime))
                config.set(section, 'size', str(entry.size))
                config.set(section, 'author', entry.author or 'Unknown')
                config.set(section, 'signatures', ', '.join(sorted(entry.signatures)))
                config.set(section, 'object_signatures', ', '.join(sorted(entry.object_signatures)))
                config.set(section, 'logic_signatures', ', '.join(sorted(entry.logic_signatures)))
                config.set(section, 'logic_to_content_ratio', str(entry.logic_to_content_ratio))
                config.set(section, 'folder_scents', ', '.join(sorted(entry.folder_scents)))
                config.set(section, 'masters', ', '.join(entry.masters))
                config.set(section, 'is_framework', str(entry.is_framework))
                config.set(section, 'framework_reason', entry.framework_reason or '')
                config.set(section, 'is_blessed', str(entry.is_blessed))
                config.set(section, 'is_partial', str(entry.is_partial))
                config.set(section, 'lo_index', str(entry.lo_index))
                config.set(section, 'layer', entry.layer)
                config.set(section, 'lc_score', str(entry.lc_score))
                config.set(section, 'lc_confidence', entry.lc_confidence)
                config.set(section, 'silo_type', silo_type)  # SP or BOS
            
            # Dump SP silo
            for name, entry in sp_entries.items():
                dump_entry(f"SP:{name}", entry, 'SP')
            
            # Dump BOS mods (representative entries)
            for name, entry in bos_mods.items():
                dump_entry(f"BOS_MOD:{name}", entry, 'BOS_MOD')
            
            # Dump BOS plugins (full entries)
            for name, entry in bos_plugins.items():
                dump_entry(f"BOS:{name}", entry, 'BOS')
        
            with open(cache_path, 'w', encoding='utf-8') as f:
                config.write(f)
            
            self.log_info(f"Rich silo cached: {len(sp_entries)} SP, {len(bos_mods)} BOS mods, {len(bos_plugins)} BOS plugins")
        
        except Exception as e:
            self.log_warning(f"Rich silo cache write failed: {e}")

    def _load_silo_cache(self) -> Optional[Dict[str, Any]]:
        """Load rich v3 format - reconstruct ManifestEntry objects from sections."""
        cache_path = self._get_silo_cache_path()
        if not cache_path.exists():
            return None
            
        try:
            config = configparser.ConfigParser(strict=False)
            config.read(cache_path, encoding='utf-8')
            
            format_ver = config.get('_meta', 'format', fallback='legacy')
            if format_ver != 'rich_v3':
                self.log_info(f"Cache format is {format_ver}, not rich_v3 - rebuilding")
                return None
            
            result = {
                "_meta": {
                    "loadorder_signature": config.get('_meta', 'loadorder_signature', fallback=''),
                    "format": "rich_v3"
                },
                "SP": {},
                "BOS_MODS": {},
                "BOS_PLUGINS": {}
            }
            
            # Parse sections back into ManifestEntry objects
            for section in config.sections():
                if section.startswith('_'):
                    continue
                
                try:
                    parts = section.split(':')
                    if len(parts) != 2:
                        continue
                        
                    silo_type, name = parts
                    
                    entry = ManifestEntry(
                        file_hash=config.get(section, 'hash', fallback=''),
                        mtime=config.getfloat(section, 'mtime', fallback=0.0),
                        size=config.getint(section, 'size', fallback=0),
                        author=config.get(section, 'author', fallback='Unknown'),
                        signatures=set(s.strip() for s in config.get(section, 'signatures', fallback='').split(',') if s.strip()),
                        masters=[m.strip() for m in config.get(section, 'masters', fallback='').split(',') if m.strip()],
                        object_signatures=set(s.strip() for s in config.get(section, 'object_signatures', fallback='').split(',') if s.strip()),
                        logic_signatures=set(s.strip() for s in config.get(section, 'logic_signatures', fallback='').split(',') if s.strip()),
                        logic_to_content_ratio=config.getfloat(section, 'logic_to_content_ratio', fallback=0.0),
                        folder_scents=set(s.strip() for s in config.get(section, 'folder_scents', fallback='').split(',') if s.strip()),
                        is_framework=config.getboolean(section, 'is_framework', fallback=False),
                        framework_reason=config.get(section, 'framework_reason', fallback=''),
                        is_blessed=config.getboolean(section, 'is_blessed', fallback=False),
                        is_partial=config.getboolean(section, 'is_partial', fallback=False),
                        lo_index=config.getint(section, 'lo_index', fallback=-1),
                        layer=config.get(section, 'layer', fallback='hybrid'),
                        lc_score=config.getint(section, 'lc_score', fallback=50),
                        lc_confidence=config.get(section, 'lc_confidence', fallback='low')
                    )
                    
                    if silo_type == 'SP':
                        result["SP"][name] = entry
                    elif silo_type == 'BOS_MOD':
                        result["BOS_MODS"][name] = entry
                    elif silo_type == 'BOS':
                        result["BOS_PLUGINS"][name] = entry
                        
                except Exception as e:
                    self.log_debug(f"Failed to parse rich section [{section}]: {e}")
                    continue
            
            self.log_info(f"Rich cache loaded: {len(result['SP'])} SP, {len(result['BOS_MODS'])} BOS mods, {len(result['BOS_PLUGINS'])} BOS plugins")
            return result
            
        except Exception as e:
            self.log_debug(f"Rich silo cache load failed: {e}")
            return None

    def _is_silo_cache_valid(self, current_signature: str) -> bool:
        """Check if silo cache matches current loadorder signature."""
        cache = self._load_silo_cache()
        if not cache:
            return False
        stored_sig = cache.get("_meta", {}).get("loadorder_signature", "")
        valid = stored_sig == current_signature
        self.log_debug(f"Silo cache valid: {valid} (stored={stored_sig[:8]}..., current={current_signature[:8]}...)")
        return valid   
    
    def load_manifest(self) -> None:
        """Load from profile INI with delta update for new plugins."""        
        profile_ini = self._ensure_profile_manifest()
        
        if not profile_ini.exists():
            self._manifest = {}
            return
        
        try:
            config = configparser.ConfigParser(strict=False)
            config.read(profile_ini, encoding='utf-8')
            
            # Check version for migration
            stored_logic_ver = config.getint('_meta', 'extraction_logic_version', fallback=1)
            needs_rebuild = (stored_logic_ver < CURRENT_EXTRACTION_LOGIC_VERSION)

            # Load bridge if Frankie cached it during scan
            if config.has_section('_bridge'):
                self._plugin_to_mod_bridge = {}
                for plugin_name in config.options('_bridge'):
                    self._plugin_to_mod_bridge[plugin_name] = config.get('_bridge', plugin_name)
                self.log_debug(f"Bridge loaded from manifest: {len(self._plugin_to_mod_bridge)} entries")
            else:
                self._plugin_to_mod_bridge = {}
                self.log_debug("No bridge section in manifest — will rebuild on first use")
                
            if needs_rebuild:
                self.log_info(f"Version migration: {stored_logic_ver} -> {CURRENT_EXTRACTION_LOGIC_VERSION}")
            
            # Parse sections
            self._manifest = {}
            
            for section in config.sections():
                if section.startswith('_'):
                    continue
                
                try:
                    # Parse folder_scents (new in v2)
                    scents_str = config.get(section, 'folder_scents', fallback='')
                    folder_scents = set(s.strip() for s in scents_str.split(',') if s.strip())
                    
                    # Parse ratio (new in v2)
                    ratio = config.getfloat(section, 'logic_to_content_ratio', fallback=0.0)
                    # Parse signature sets for pre-filter
                    obj_sigs_str = config.get(section, 'object_signatures', fallback='')
                    object_signatures = set(s.strip() for s in obj_sigs_str.split(',') if s.strip())
                
                    logic_sigs_str = config.get(section, 'logic_signatures', fallback='')
                    logic_signatures = set(s.strip() for s in logic_sigs_str.split(',') if s.strip())
                
                    lo_index = config.getint(section, 'lo_index', fallback=-1)
                    layer = config.get(section, 'layer', fallback='hybrid')
                    is_blessed = config.getboolean(section, 'is_blessed', fallback=False)
                    
                    # Frankie writes 'hybrid' for everyone - blessed stay hybrid for combos
                    # (they're not global-locked; they're base game sources)
                    is_blessed = config.getboolean(section, 'is_blessed', fallback=False)
                    
                    # Frankie writes 'hybrid' for everyone - correct blessed to global
                    if is_blessed and layer == 'hybrid':
                        layer = 'global'
                    lc_score = config.getint(section, 'lc_score', fallback=50)
                    lc_confidence = config.get(section, 'lc_confidence', fallback='low')                
                    # FRANKIE FALLBACK on load: if ratio 0.0 and 100+ sigs, mark partial
                    sigs_str = config.get(section, 'signatures', fallback='')
                    sig_count = len([s for s in sigs_str.split(',') if s.strip()])
                    is_partial = config.getboolean(section, 'is_partial', fallback=False)
                    
                    if ratio == 0.0 and sig_count >= 100 and not is_partial:
                        is_partial = True
                        self.log_debug(f"LOAD_FALLBACK: {section} forced partial (v1 data)")
                    
                    entry = ManifestEntry(
                        file_hash=config.get(section, 'hash', fallback=''),
                        mtime=config.getfloat(section, 'mtime', fallback=0.0),
                        size=config.getint(section, 'size', fallback=0),
                        author=config.get(section, 'author', fallback='Unknown'),
                        signatures=set(s.strip() for s in sigs_str.split(',') if s.strip()),
                        masters=[m.strip() for m in config.get(section, 'masters', fallback='').split(',') if m.strip()],
                        object_signatures=object_signatures,
                        logic_signatures=logic_signatures,
                        logic_to_content_ratio=ratio,
                        folder_scents=folder_scents,
                        is_framework=config.getboolean(section, 'is_framework', fallback=False),
                        framework_reason=config.get(section, 'framework_reason', fallback=''),
                        is_blessed=config.getboolean(section, 'is_blessed', fallback=False),
                        is_partial=is_partial,
                        lo_index=lo_index,
                        layer=layer,
                        lc_score=lc_score,
                        lc_confidence=lc_confidence
                    )
                    self._manifest[section] = entry
                except Exception as e:
                    self.log_debug(f"Failed to parse section [{section}]: {e}")
                    continue
            
            self.log_info(f"Manifest loaded: {len(self._manifest)} entries (logic v{stored_logic_ver})")
            
            # If version mismatch, trigger background refresh to get new fields
            if needs_rebuild:
                self.log_info("Triggering background refresh for v2 fields...")
                # Don't block - let current load finish, mark for refresh
                self._refresh_attempted = False  # Allow refresh_silos to rebuild
            
        except Exception as e:
            self.log_warning(f"Failed to load manifest: {e}")
            self._manifest = {}

    def _ensure_profile_manifest(self) -> Path:
        """Ensure profile-specific manifest exists, seeded from blessed base."""
        profile_ini = self.data_dir / f"skygen_manifest_{self.wrapper.profile_name}.ini"
        
        if profile_ini.exists():
            return profile_ini
        
        # Copy blessed base as starting point
        blessed_base = self.plugin_path / "data" / "blessed_base.ini"
        if blessed_base.exists():
            import shutil
            shutil.copy(str(blessed_base), str(profile_ini))
            self.log_info(f"Seeded profile manifest from blessed base: {profile_ini}")
        else:
            # No blessed base, create empty with _meta
            self._create_empty_manifest(profile_ini)
        
        return profile_ini
    
    def _create_empty_manifest(self, path: Path) -> None:
        """Create empty manifest with _meta section."""
        
        config = configparser.ConfigParser()
        config.add_section('_meta')
        config.set('_meta', 'loadorder_signature', '')
        config.set('_meta', 'generated_at', '0')
        config.set('_meta', 'profile', self.wrapper.profile_name)
        config.set('_meta', 'is_full_scan', 'false')
        config.set('_meta', 'app_version', CURRENT_APP_VERSION)
        config.set('_meta', 'extraction_logic_version', str(CURRENT_EXTRACTION_LOGIC_VERSION))
        
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            config.write(f)
    
    def _delta_update(self, config, new_plugins: set) -> None:
        """Sniff new plugins and add to config. Protect BLESSED entries."""
        for plugin_name in sorted(new_plugins):
            if config.has_section(plugin_name):
                continue
            
            # Protect blessed entries
            if config.has_section(plugin_name):
                existing_hash = config.get(plugin_name, 'file_hash', fallback='')
                if existing_hash.startswith(BLESSED_HASH_PREFIX):
                    continue
            
            plugin_path = self.wrapper.get_plugin_path(plugin_name)
            if not plugin_path:
                continue
            
            try:
                mod_folder_hint = plugin_path.parent.name if plugin_path.parent else None
                dna = quick_sniff(str(plugin_path), mod_folder_hint)
                
                # FRANKIE FALLBACK: If ratio is 0.0 but has 100+ records, mark partial
                is_partial = dna.is_partial
                if dna.logic_to_content_ratio == 0.0 and len(dna.signatures) >= 100:
                    is_partial = True
                    self.log_debug(f"FRANKIE_FALLBACK: {plugin_name} marked partial (no ratio, {len(dna.signatures)} records)")
                
                config.add_section(plugin_name)
                config.set(plugin_name, 'hash', hash_file_head(plugin_path))
                config.set(plugin_name, 'mtime', str(plugin_path.stat().st_mtime))
                config.set(plugin_name, 'size', str(plugin_path.stat().st_size))
                config.set(plugin_name, 'author', dna.author or 'Unknown')
                config.set(plugin_name, 'signatures', ', '.join(sorted(dna.signatures)))
                config.set(plugin_name, 'masters', ', '.join(dna.masters))
                config.set(plugin_name, 'is_framework', str(dna.is_framework))
                config.set(plugin_name, 'is_blessed', 'False')
                config.set(plugin_name, 'is_partial', str(is_partial))  # Use fallback value
                config.set(plugin_name, 'framework_reason', dna.framework_reason or '')
                # Persist new fields for Version 2
                config.set(plugin_name, 'logic_to_content_ratio', str(dna.logic_to_content_ratio))
                config.set(plugin_name, 'folder_scents', ', '.join(dna.folder_scents))
                config.set(plugin_name, 'object_signatures', ', '.join(sorted(dna.object_signatures)))
                config.set(plugin_name, 'logic_signatures', ', '.join(sorted(dna.logic_signatures)))
                
            except Exception as e:
                self.log_debug(f"Delta failed for {plugin_name}: {e}")

    def get_plugin_data(self, plugin_name: str) -> Optional[ManifestEntry]:
        """Retrieve plugin data from loaded manifest."""
        return self._manifest.get(plugin_name)

    def generate_audit_cache(self) -> None:
        """Marriage of Manifest + Silos + Blessed + BL rules + Pre-Patched. INI format."""
        # Ensure manifest is loaded (hydrate if using silo cache)
        if not self._manifest:
            if self._manifest_path.exists():
                self.load_manifest()
        
        if not self._manifest:
            self.log_warning("AUDIT_GEN: No manifest available")
            return
        
        self.log_info(f"AUDIT_GEN: Processing {len(self._manifest)} entries")
        
        config = configparser.ConfigParser()
        data_dir = self.data_dir
        masters_to_lock: Set[str] = set()
        
        for plugin_name, entry in self._manifest.items():
            # Build canonical signature sets once from constants
            sp_sigs = set().union(*SP_RECORD_MAP.values())
            bos_sigs = set().union(*BOS_RECORD_MAP.values())
            
            # Respect LC layer assignment — source of truth
            if entry.layer == Layer.GLOBAL.value:
                if entry.is_blessed:
                    silos = ["SP", "BOS"]  # Base game masters carry everything
                else:
                    silos = ["GLOBAL"]
            elif entry.layer == Layer.BOS.value:
                silos = ["BOS"]
            elif entry.layer == Layer.SP.value:
                silos = ["SP"]
            elif entry.layer == Layer.HYBRID.value:
                silos = []
                if entry.signatures.intersection(bos_sigs):
                    silos.append("BOS")
                if entry.signatures.intersection(sp_sigs) or not entry.is_framework:
                    silos.append("SP")
                if not silos:
                    silos.append("SP")
            else:
                silos = ["SP"]
                        
            # Determine pre-patched status (full vs partial)
            is_pre_patched = False
            patched_types: List[str] = []
            is_full_patch = False
            
            # Check for BOS swap
            bos_ini = data_dir / "BOS" / f"{plugin_name}_SWAP.ini"
            if bos_ini.exists():
                is_pre_patched = True
                patched_types.append("BOS")
                is_full_patch = self._is_full_bos_swap(bos_ini, entry)
                if is_full_patch and entry.masters:
                    masters_to_lock.update(entry.masters)
            
            # Check for SP patch
            sp_dir = data_dir / "SkyPatcher"
            if sp_dir.exists():
                for sp_ini in sp_dir.glob("*.ini"):
                    try:
                        with open(sp_ini, 'r', encoding='utf-8') as f:
                            content = f.read()
                            if plugin_name in content:
                                is_pre_patched = True
                                patched_types.append("SP")
                                if self._is_full_sp_patch(content, plugin_name):
                                    is_full_patch = True
                                    if entry.masters:
                                        masters_to_lock.update(entry.masters)
                                break
                    except:
                        pass
            
            # Determine status (blessed beats framework beats pre_patched)
            plugin_lower = plugin_name.lower()
            is_blessed = (entry.is_blessed or 
                         entry.file_hash.startswith('BLESSED_') or
                         plugin_lower.startswith(OFFICIAL_CC_PREFIX) or
                         plugin_lower in [p.lower() for p in BLESSED_CORE_FILES])
            
            status = "active"
            reason = "content"
            color = COLOR_ACTIVE
            icon = ICON_NONE
            display_name = plugin_name
            
            if self.blacklist_mgr:
                plugin_lower = plugin_name.lower()
                user_rule = self.blacklist_mgr._user_rules.get(plugin_lower)
                auto_reason = self.blacklist_mgr._auto_blacklist.get(plugin_lower)
                
                if user_rule == "whitelist":
                    status, reason, color, icon = "active", "user_whitelist", COLOR_STARRED, ICON_STARRED
                elif user_rule == "blacklist":
                    status, reason, color, icon = "locked", "user_blacklist", COLOR_USER_BL, ICON_USER_BL
                elif is_blessed:
                    status, reason, color, icon = "shielded", "blessed", COLOR_LOCKED, ICON_BLESSED
                    display_name = f"{plugin_name} [BLESSED]"
                elif auto_reason:
                    status, reason, color, icon = "locked", "framework", COLOR_LOCKED, ICON_LOCKED
                    display_name = f"{plugin_name} [Framework]"
                elif is_pre_patched:
                    if is_full_patch:
                        status, reason, color, icon = "locked", "pre_patched_full", COLOR_LOCKED, ICON_LOCKED
                        display_name = f"{plugin_name} [Full: {','.join(patched_types)}]"
                    else:
                        status, reason, color, icon = "active", "partial", COLOR_PARTIAL, ICON_PARTIAL
                        display_name = f"{plugin_name} [Partial: {','.join(patched_types)}]"
            
            # INI Section per plugin
            config.add_section(plugin_name)
            config.set(plugin_name, 'status', status)
            config.set(plugin_name, 'reason', reason)
            config.set(plugin_name, 'color', color)
            config.set(plugin_name, 'icon', icon)
            config.set(plugin_name, 'display_name', display_name)
            config.set(plugin_name, 'author', entry.author)
            config.set(plugin_name, 'silos', ','.join(silos))
            config.set(plugin_name, 'is_blessed', str(is_blessed))
            config.set(plugin_name, 'is_pre_patched', str(is_pre_patched))
            config.set(plugin_name, 'patched_types', ','.join(patched_types))
            config.set(plugin_name, 'is_full_patch', str(is_full_patch))
            config.set(plugin_name, 'signatures', ','.join(list(entry.signatures)[:5]))
            # Frankie's verdict – shove it in the audit so AD knows what's hard-locked
            config.set(plugin_name, 'layer', entry.layer)  # global', 'bos', 'sp', 'hybrid'
            config.set(plugin_name, 'lc_confidence', entry.lc_confidence)
            
        # Second pass: Lock masters of fully patched plugins
        for master_name in masters_to_lock:
            if config.has_section(master_name):
                current_status = config.get(master_name, 'status', fallback='active')
                # Only lock if not already blessed/framework
                if current_status not in ('locked', 'blessed'):
                    config.set(master_name, 'status', 'locked')
                    config.set(master_name, 'reason', 'master_of_full_patch')
                    config.set(master_name, 'color', COLOR_LOCKED)
                    config.set(master_name, 'icon', ICON_LOCKED)
                    config.set(master_name, 'display_name', f"{master_name} [Master Locked]")
        
        # Direct write — no temp file rename dance (WinError 5)
        cache_path = self._get_audit_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            config.write(f)
            f.flush()
            os.fsync(f.fileno())
        self.log_info(f"Audit INI generated: {len(config.sections())} sections")

    def _is_full_bos_swap(self, ini_path: Path, entry: ManifestEntry) -> bool:
        """Detect if BOS swap is full (all base records) or partial."""
        try:
            with open(ini_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Count FormID entries in swap ini vs expected records
            # Simple heuristic: >80% coverage = full
            import re
            formid_entries = len(re.findall(r'FormID|formId', content))
            # Assume avg 1-3 records per object type, estimate total objects
            estimated_records = max(len(entry.signatures), 1)
            return formid_entries >= estimated_records * 0.8
        except:
            return False
    
    def _is_full_sp_patch(self, ini_content: str, plugin_name: str) -> bool:
        """Detect if SP patch is full (all categories) or partial."""
        # Check for generate_all_categories or multiple filter types
        has_all_filter = "generate_all_categories=true" in ini_content.lower()
        has_all_filter = has_all_filter or "filterByKeywords" in ini_content and ini_content.count("filterBy") >= 3
        return has_all_filter

    def _get_audit_cache_path(self) -> Path:
        return self.data_dir / f"audit_state_{self.wrapper.profile_name}.ini"

    def get_audit_cache(self) -> Dict[str, Dict]:
        """Read audit INI as dict."""
        cache_path = self._get_audit_cache_path()
        if not cache_path.exists():
            self.log_info("Audit INI missing, generating...")
            self.generate_audit_cache()
        
        # Double-check it exists now
        if not cache_path.exists():
            self.log_error("Audit generation failed to create file")
            return {}
        
        try:
            config = configparser.ConfigParser()
            config.read(cache_path, encoding='utf-8')
            
            if len(config.sections()) == 0:
                self.log_warning("Audit INI has 0 sections, regenerating...")
                self.generate_audit_cache()
                config.read(cache_path, encoding='utf-8')  # Re-read after regen
            
            data = {}
            for section in config.sections():
                silos_str = config.get(section, 'silos', fallback='')
                silos = [s.strip() for s in silos_str.split(',') if s.strip()]
                
                data[section] = {
                    'status': config.get(section, 'status', fallback='active'),
                    'reason': config.get(section, 'reason', fallback='content'),
                    'color': config.get(section, 'color', fallback=COLOR_ACTIVE),
                    'icon': config.get(section, 'icon', fallback=ICON_NONE),
                    'display_name': config.get(section, 'display_name', fallback=section),
                    'author': config.get(section, 'author', fallback='Unknown'),
                    'silos': silos,
                    'is_blessed': config.getboolean(section, 'is_blessed', fallback=False),
                    # Pull LC data up for the UI to check hard-lock status
                    'layer': config.get(section, 'layer', fallback='hybrid'),
                    'lc_confidence': config.get(section, 'lc_confidence', fallback='low'),
                }
            self.log_info(f"Audit INI loaded: {len(data)} sections")
            return data
        except Exception as e:
            self.log_warning(f"Failed to load audit INI: {e}")
            return {}

    def get_plugins_for_silo(self, silo: str, include_locked: bool = False) -> List[str]:
        """Get filtered plugin list for a specific silo from audit cache."""
        audit = self.get_audit_cache()
        result = []
        
        for plugin_name, data in audit.items():
            # PANELS: Skip locked items (hidden from combos)
            # AD: Can pass include_locked=True to see everything
            if data.get('status') == 'locked' and not include_locked:
                continue
            
            # Check silo membership
            silos = data.get('silos', [])
            if silo in silos:
                result.append(plugin_name)
                
        return sorted(result)

    def save_manifest(self) -> None:
        
        # === SCREAMING DIAGNOSTIC ===
        if not self._manifest:
            self.log_error("MANIFEST_WRITE: _manifest dict is EMPTY")
            return
        
        sample = next(iter(self._manifest.values()))
        self.log_info(f"MANIFEST_WRITE: {len(self._manifest)} entries ready")
        self.log_info(f"MANIFEST_SAMPLE: obj_sigs={len(sample.object_signatures)}, logic_sigs={len(sample.logic_signatures)}, scents={len(sample.folder_scents)}")
        # === END DIAGNOSTIC ===
        
        """Frankie-style explicit write: field-by-field, no iteration shortcuts."""
        
        if not self._manifest:
            self.log_error("MANIFEST_EMPTY: Refusing to write empty manifest")
            return
            
        profile_ini = self.data_dir / f"skygen_manifest_{self.wrapper.profile_name}.ini"
        config = configparser.ConfigParser()
        
        # Meta section
        config.add_section('_meta')
        config.set('_meta', 'loadorder_signature', self._get_loadorder_signature())
        config.set('_meta', 'generated_at', str(time.time()))
        config.set('_meta', 'profile', self.wrapper.profile_name)
        config.set('_meta', 'is_full_scan', 'true')
        config.set('_meta', 'app_version', CURRENT_APP_VERSION)
        config.set('_meta', 'extraction_logic_version', str(CURRENT_EXTRACTION_LOGIC_VERSION))
        
        # Load order section
        config.add_section('_loadorder')
        lo_map = self.get_load_order_map()
        for idx, name in sorted(lo_map.items()):
            config.set('_loadorder', str(idx), name)

        # Bridge cache — plugin_name -> mod_folder, built during scan
        config.add_section('_bridge')
        for plugin_name, mod_name in self._plugin_to_mod_bridge.items():
            config.set('_bridge', plugin_name, mod_name)  
            
        # Plugin sections - EXPLICIT like Frankie
        written = 0
        for plugin_name, entry in self._manifest.items():
            try:
                config.add_section(plugin_name)
                # Core
                config.set(plugin_name, 'hash', entry.file_hash or '')
                config.set(plugin_name, 'mtime', str(entry.mtime))
                config.set(plugin_name, 'size', str(entry.size))
                config.set(plugin_name, 'author', entry.author or 'Unknown')
                config.set(plugin_name, 'signatures', ', '.join(sorted(entry.signatures)))
                config.set(plugin_name, 'masters', ', '.join(entry.masters))
                # Rich v2 (write even if empty - Frankie pattern)
                config.set(plugin_name, 'object_signatures', ', '.join(sorted(entry.object_signatures)))
                config.set(plugin_name, 'logic_signatures', ', '.join(sorted(entry.logic_signatures)))
                config.set(plugin_name, 'logic_to_content_ratio', str(entry.logic_to_content_ratio))
                config.set(plugin_name, 'folder_scents', ', '.join(sorted(entry.folder_scents)))
                config.set(plugin_name, 'lo_index', str(entry.lo_index))
                config.set(plugin_name, 'layer', entry.layer)
                config.set(plugin_name, 'lc_score', str(entry.lc_score))
                config.set(plugin_name, 'lc_confidence', entry.lc_confidence)
                config.set(plugin_name, 'is_blessed', str(entry.is_blessed))
                config.set(plugin_name, 'is_framework', str(entry.is_framework))
                config.set(plugin_name, 'is_partial', str(entry.is_partial))
                config.set(plugin_name, 'framework_reason', entry.framework_reason or '')
                written += 1
            except Exception as e:
                self.log_error(f"SECTION_FAIL {plugin_name}: {e}")
                continue
        
        self.log_info(f"MANIFEST_PREWRITE: {written} sections prepared")
        
        # Direct write: no temp file, no rename, no Windows lock dance
        profile_ini.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(profile_ini, 'w', encoding='utf-8') as f:
                config.write(f)
                f.flush()
                os.fsync(f.fileno())
            
            verify_size = profile_ini.stat().st_size
            self.log_info(f"MANIFEST_SAVED: {written} entries, {verify_size} bytes")
            
        except Exception as e:
            self.log_critical(f"MANIFEST_WRITE_CRASH: {e}")
            raise

class SiloedSnoop(QObject, LoggingMixin):
    """
    High-level orchestrator for Siloed Intelligence.
    Bridges ProfileManager + BlacklistManager with UI.
    """
    
    filter_ready = pyqtSignal(str, list)  # silo, List[ModStatus]
    
    def __init__(self, organizer_wrapper: Any, plugin_path: Path) -> None:
        QObject.__init__(self)
        LoggingMixin.__init__(self)
        
        self.profile_mgr = ProfileManager(organizer_wrapper, plugin_path)
        self.blacklist_mgr = BlacklistManager(self.profile_mgr, plugin_path)
        # Link ProfileManager to BlacklistManager for auto-BL persistence
        self.profile_mgr.blacklist_mgr = self.blacklist_mgr
                
        # Snoop observes PM's scan state, doesn't re-emit signals
        self.profile_mgr.scan_complete.connect(self._on_scan_complete)
        
        # Note: silo_data_ready comes from PM, not Snoop
        # UI panels connect to PM.silo_data_ready directly
            
    def initialize(self, plugins: List[str]) -> None:
        """DEPRECATED: Route through refresh_silos() instead."""
        self.log_debug("SiloedSnoop.initialize() called - delegating to PM.refresh_silos()")
        self.profile_mgr.refresh_silos()
        
    def _on_scan_complete(self, success: bool) -> None:
        """Emit ready signal for both silos."""
        self.log_info("Scan complete, silos ready")
        
        # Flush staged auto-blacklist entries
        if self.blacklist_mgr and hasattr(self.blacklist_mgr, '_auto_blacklist') and self.blacklist_mgr._auto_blacklist:
            self.blacklist_mgr._save_auto_blacklist()
            self.log_info(f"Auto-blacklist persisted: {len(self.blacklist_mgr._auto_blacklist)} entries")
        
        # Pre-compute filters for common categories
        for silo in ["SP", "BOS"]:
            self.filter_ready.emit(silo, [])
            
    def get_mod_display_info(self, plugin_name: str, silo: str,
                             category: Optional[str] = None) -> ModStatus:
        """Get full status for Auditor UI."""
        return self.blacklist_mgr.get_mod_status(plugin_name, silo, category)
    
    def set_user_rule(self, plugin_name: str, rule: Optional[str]) -> None:
        """Proxy to BlacklistManager."""
        self.blacklist_mgr.set_user_rule(plugin_name, rule)
    
    def is_scanning(self) -> bool:
        return self.profile_mgr._is_scanning
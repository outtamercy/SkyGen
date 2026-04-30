
# + FOXHUNT_FIX: Re-entrancy guard with try/finally for both BOS and SP
from __future__ import annotations

import json
from PyQt6.QtCore import (   # type: ignore
    QObject, pyqtSignal, QTimer, QThreadPool, Qt, QThread, QRunnable
)
from PyQt6.QtWidgets import QMessageBox, QFileDialog   # type: ignore
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from pathlib import Path

from ..utils.logger import (LoggingMixin, SkyGenLogger,
    MO2_LOG_DEBUG, MO2_LOG_INFO, MO2_LOG_WARNING,
    MO2_LOG_ERROR, MO2_LOG_CRITICAL, MO2_LOG_TRACE
)
from ..src.config import ConfigManager
from ..ui.theme_manager import ThemeManager
from ..src.organizer_wrapper import OrganizerWrapper
from ..core.constants import (
    SKYPATCHER_SUPPORTED_RECORD_TYPES, ERROR_MESSAGES, BYPASS_BLACKLIST, 
    BOS_SUPPORTED_RECORD_TYPES, DEBUG_MODE, TRACEBACK_LOGGING, SIGNATURE_TO_CATEGORIES,
    SIGNATURE_TO_FILTER, BLESSED_CORE_FILES, KEYWORD_SECTION_MAP, BOS_SIGNATURES
)

from ..utils.file_ops import FileOperationsManager
from ..extractors.plugin_extractor import PluginExtractor
from ..utils.data_exporter import DataExporter
from ..utils.patch_gen import PatchAndConfigGenerationManager
from .worker import GenerationWorker
from ..core.models import ApplicationConfig, PatchGenerationOptions
from ..storage.cache import CacheManager
from ..utils.bl_mgr import BlacklistManager
from ..utils.pm_mgr import ProfileManager, ManifestEntry, SiloedSnoop
from ..utils.guard import Guard

if TYPE_CHECKING:
    from ..ui.main_dialog import SkyGenMainDialog
    from ..ui.sp_panel import SkyPatcherPanel
    from ..ui.bos_panel import BosPanel
from ..src.OR import OneRing

_logger_configured: bool = False


def _configure_logger_once(debug: bool, trace: bool) -> None:
    global _logger_configured
    if _logger_configured:
        return
    from ..utils.logger import SkyGenLogger
    SkyGenLogger().set_debug_mode(debug)
    SkyGenLogger().set_traceback_logging(trace)
    _logger_configured = True

class ScanWorker(QRunnable):
    """Thin wrapper to chuck the heavy scan into the threadpool."""
    
    def __init__(self, profile_manager):
        super().__init__()
        self.profile_manager = profile_manager
        
    def run(self):
        try:
            self.profile_manager.refresh_silos()
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            # PM has no signal for errors, so write to logger directly
            self.profile_manager.log_critical(f"SCANWORKER_DEATH: {e}\n{err}")
            self.profile_manager.scan_complete.emit(False)

class SkyGenUIController(QObject):
    """Brain of SkyGen – all logging routed through  _handle_worker_log_line."""

    progress_updated = pyqtSignal(dict)
    generation_complete = pyqtSignal(bool, str, str)
    activity_indicator_toggle = pyqtSignal(bool)
    show_message_box = pyqtSignal(str, str, str)
    panels_ready = pyqtSignal()  # NEW: Gate 2 for welcome panel

    def _handle_worker_log_line(self, msg: str, lvl: int) -> None:
        from ..utils.logger import SkyGenLogger
        logger = SkyGenLogger()
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Viewer gets INFO and above immediately
        if lvl >= MO2_LOG_INFO:
            self.log_callback(msg, lvl)
                
        # DEBUG/TRACE: File only (never viewer)
        if lvl == MO2_LOG_TRACE and self.app_config.traceback_logging:
            logger.trace(msg)
        elif lvl == MO2_LOG_DEBUG and self.app_config.debug_logging:
            logger.debug(msg)
        # INFO: File if debug mode, buffer always for flush backup
        elif lvl == MO2_LOG_INFO:
            if self.app_config.debug_logging:
                logger.info(msg)
            # Capture in session buffer so flush has it even if widget stalls
            if len(self._session_buffer) < self._session_buffer_max:
                self._session_buffer.append(f"[{timestamp}] [INFO] {msg}")
        
        # WARNING/ERROR/CRITICAL: Always to main file + capture in buffer if generating
        elif lvl >= MO2_LOG_WARNING:
            level_name = "WARN" if lvl == MO2_LOG_WARNING else "ERROR" if lvl == MO2_LOG_ERROR else "CRIT"
            if lvl == MO2_LOG_WARNING:
                logger.warning(msg)
            elif lvl == MO2_LOG_ERROR:
                logger.error(msg)
            elif lvl == MO2_LOG_CRITICAL:
                logger.critical(msg)
            
            # Also capture errors in session buffer for context (RING BUFFER)
            if self._generation_in_progress:
                self._session_buffer.append(f"[{timestamp}] [{level_name}] {msg}")
                # Ring buffer: drop oldest if max exceeded
                if len(self._session_buffer) > self._session_buffer_max:
                    self._session_buffer.pop(0)

    def __init__(
        self,
        main_dialog: 'SkyGenMainDialog',
        organizer_wrapper: OrganizerWrapper,
        file_operations_manager: FileOperationsManager,
        plugin_extractor: PluginExtractor,
        patch_generator: PatchAndConfigGenerationManager,
        data_exporter: DataExporter,
        config_manager: ConfigManager,
        theme_manager: ThemeManager,
        plugin_path: Path,
        guard: Guard, 
        parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)

        self.organizer_wrapper = organizer_wrapper
        self.file_ops = file_operations_manager
        self.plugin_extractor = plugin_extractor
        self.patch_gen = patch_generator
        self.data_exporter = data_exporter
        self.config_manager = config_manager
        self.theme_manager = theme_manager
        self.main_dialog = main_dialog
        self.plugin_path = plugin_path
        self.cache = CacheManager(str(plugin_path))
        self.data_exporter.cache_manager = self.cache

        self.ui_widgets: Optional[Dict[str, Any]] = None
        self.sp_panel: Optional['SkyPatcherPanel'] = None
        self.bos_panel: Optional['BosPanel'] = None
        self.guard = guard  # Traffic cop reference
        
        # Wire Guard signals to Controller actions
        self.guard.scan_started.connect(self._on_guard_scan_start)
        self.app_config: ApplicationConfig = self.config_manager.get_application_config()
        self.patch_settings: PatchGenerationOptions = self.config_manager.get_patch_settings()

        # Deferred PM initialization to prevent cold boot freeze
        self.siloed_snoop = None
        self.profile_manager = None
        self._pm_ready = False

        # Bridge map: plugin_name -> mod_folder (for T&S resolution)
        self._plugin_to_mod_bridge: Dict[str, str] = {}

        self.threadpool = QThreadPool.globalInstance()
        self.threadpool.setMaxThreadCount(1)

        self.generation_worker: Optional[GenerationWorker] = None

        # Session capture for post-mortem (INFO and above)
        self._session_buffer: List[str] = []
        self._session_buffer_max = 5000
        self._generation_in_progress = False
        self.log_callback = lambda msg, lvl: self.main_dialog.status_log_widget.append_line(msg, lvl)

        # Keyword Cache: Warm at startup to avoid disk hits during UI interaction
        self._keyword_cache: Dict[str, List[str]] = {}
        self._filter_cache: Dict[str, List[str]] = {}  # INI keys for Filter combo
        self._warm_keyword_cache()

        # Feed DE the keyword cache so auto-gen has ammo
        self.data_exporter.keyword_cache = self._keyword_cache

        self._handle_worker_log_line("Director Fury on-line – 'S.H.I.E.L.D. Status Report' active.", MO2_LOG_INFO)
        _configure_logger_once(self.app_config.debug_logging, self.app_config.traceback_logging)

    def _deferred_pm_init(self):
        if getattr(self, '_pm_init_done', False):
            return
        self._pm_init_done = True
        """Lazy-load the Profile Manager so we don't freeze MO2 on startup."""
        # Guard against double-fire from Guard or race conditions
        if getattr(self, '_pm_signals_wired', False):
            self._handle_worker_log_line("PM init skipped - signals already wired", MO2_LOG_DEBUG)
            return
        
        # Wake the hound first so they know who's hunting
        self._handle_worker_log_line(r"""
      __
  _-=(o ')=-_     [ FRANKEN-SNOOP ]
    (  O  )  \     [    v2.0       ]
     `---'    \    [  IT'S ALIVE   ]
     /|\      |
    (_|_)_____|
""", MO2_LOG_INFO)
        self._handle_worker_log_line("Franken-Snoop waking up to hunt...", MO2_LOG_INFO)
        
        self.siloed_snoop = SiloedSnoop(self.organizer_wrapper, self.plugin_path)
        self.profile_manager = self.siloed_snoop.profile_mgr

        # Grab BL from snoop (born inside SiloedSnoop.__init__)
        self.blacklist_mgr = self.siloed_snoop.blacklist_mgr

        # One Ring to rule them all – combo & threading coordinator
        self.one_ring = OneRing(self, self.profile_manager, self.blacklist_mgr)
        self._handle_worker_log_line("One Ring to rule them all – combo linking active", MO2_LOG_INFO)        

        # Rich-native storage - PM emits full ManifestEntry objects now
        self._rich_silos: Dict[str, Dict[str, ManifestEntry]] = {
            "GLOBAL": {},
            "SP": {}, 
            "BOS_MODS": {}, 
            "BOS_PLUGINS": {},
        }

        # Check cache first – avoid unnecessary scan
        current_sig = self.profile_manager._get_loadorder_signature()
        if self.profile_manager._is_silo_cache_valid(current_sig):
            self._handle_worker_log_line("Cache hit – loading silos from disk, skipping scan", MO2_LOG_INFO)
            # Hydrate PM manifest so bridge rebuild has data to chew on
            if not self.profile_manager._manifest and self.profile_manager._manifest_path.exists():
                self.profile_manager.load_manifest()
            cache = self.profile_manager._load_silo_cache()
            if cache:
                self._store_silo_data("SP", cache.get("SP", {}))
                self._store_silo_data("BOS_MODS", cache.get("BOS_MODS", {}))
                self._on_pm_scan_finished(True)  # Fake the finish to open gates
                return  # Skip worker creation entirely        

        self._pm_ready = False
        
        # Wire the callback first so we don't miss the signal
        # GUARD: only connect once even if Guard double-taps
        if not getattr(self, '_pm_signals_wired', False):
            self._pm_signals_wired = True
            
            self.profile_manager.scan_complete.connect(
                self._on_pm_scan_finished, 
                Qt.ConnectionType.QueuedConnection
            )
            
            # Catch sparse maps when Frankie emits them
            self.profile_manager.silo_data_ready.connect(self._store_silo_data)
            
            # Wire PM's signal to controller's relay so panels get the juice  
            self.profile_manager.silo_data_ready.connect(self.silo_data_ready.emit)
            
            # Hook viewer to Snoopy's progress so user sees the grind
            self.profile_manager.scan_progress.connect(
                lambda msg, lvl: self._handle_worker_log_line(msg, lvl)
            )
        
        # Fire up Snoopy - ONE instance only
        self._active_scan_worker = ScanWorker(self.profile_manager)
        self.threadpool.start(self._active_scan_worker)
        
        self._handle_worker_log_line("Background scan spinning up...", MO2_LOG_INFO)

    def _on_pm_scan_finished(self, success):
        self._active_scan_worker = None
        self._pm_ready = True
        
        # 1. Bridge first (instant - cached during scan)
        self._plugin_to_mod_bridge = self.profile_manager.build_plugin_to_mod_bridge()
        self.log_info(f"Bridge built: {len(self._plugin_to_mod_bridge)} plugins mapped")
        
        # ---- PLUGINLESS MOD DETECTION ----
        # PM only tracks mods with plugins. BOS needs asset-only mods too — 
        # BodySlide outputs, texture packs, mesh replacers. They never show 
        # in plugins.txt so Frankie can't see them. We hunt them manually.
        pluginless = self._detect_pluginless_mods()
        if pluginless:
            self._rich_silos["BOS_MOD"] = pluginless
            self.log_info(f"Pluginless mods detected: {len(pluginless)} folders (BodySlide, textures, etc.)")
        self.log_info(f"Bridge built: {len(self._plugin_to_mod_bridge)} plugins mapped")
        
        # 2. Combos second - everything settled before user can enter
        self.one_ring.populate_sp_combos("")
        self.one_ring.populate_bos_combos("")
        if self.sp_panel and self.one_ring:
            self.one_ring.populate_sp_category(self.sp_panel)
        
        # 3. Gate 2 LAST - only after bridge + combos are ready
        self._handle_worker_log_line("Frankie wrapped - opening Gate 2", MO2_LOG_INFO)
        self.panels_ready.emit()
            
    def _store_silo_data(self, silo_type: str, data: Any) -> None:
        """Store rich silo with duplicate detection."""
        # Defensive: BOS_PLUGINS silo is retired
        if silo_type == "BOS_PLUGINS":
            return
            
        # Prevent duplicate processing (spam filter)
        if silo_type in self._rich_silos:
            existing = self._rich_silos[silo_type]
            if isinstance(data, dict) and len(existing) == len(data):
                self.log_debug(f"Ignoring duplicate {silo_type} emission ({len(existing)} entries)")
                return
            
        if not isinstance(data, dict):
            self.log_error(f"Silo data must be dict, got {type(data)}")
            return
        
        # Take it as-is - PM already gave us {name: ManifestEntry}
        clean_data: Dict[str, ManifestEntry] = {}
        for k, v in data.items():
            name = str(k)
            if not name or name.isdigit():
                continue
            # Duck-type check: does it quack like a ManifestEntry?
            if hasattr(v, 'signatures') and hasattr(v, 'lo_index'):
                clean_data[name] = v
        
        self._rich_silos[silo_type] = clean_data
        
        # Specific logging for BOS_MODS (restored)
        if silo_type == "BOS_MODS":
            self.log_info(f"BOS_MODS stored: {len(clean_data)} mod folders ready")
        else:
            self.log_info(f"SILO_STORED: {silo_type} with {len(clean_data)} rich entries")

    def _on_guard_scan_start(self):
        """Guard says 'start working' - fire up the PM."""
        self._deferred_pm_init()

    def _detect_pluginless_mods(self) -> Dict[str, Any]:
        """Hunt mod folders with assets but no plugins — invisible to Frankie."""
        from types import SimpleNamespace
        
        result: Dict[str, Any] = {}
        mods_root = self.organizer_wrapper.mods_path
        
        if not mods_root or not mods_root.exists():
            return result
        
        # Build exclusion set — anything with a plugin is already handled
        known = set(self._plugin_to_mod_bridge.values())
        known.update(self._plugin_to_mod_bridge.keys())
        known.update(self._rich_silos.get("SP", {}).keys())
        known.update(self._rich_silos.get("BOS_MODS", {}).keys())
        
        for mod_folder in mods_root.iterdir():
            if not mod_folder.is_dir():
                continue
            
            name = mod_folder.name
            if name in known:
                continue
            
            # Skip if blacklisted — but _is_blacklisted wants a ManifestEntry, 
            # not a raw string. Pluginless mods are asset-only so they rarely 
            # hit the BL anyway, but check the raw name list if we can.
            if hasattr(self, 'blacklist_mgr') and self.blacklist_mgr:
                try:
                    # Some BL versions check by name, some by entry object
                    raw_list = getattr(self.blacklist_mgr, '_blacklist', set())
                    if name.lower() in {n.lower() for n in raw_list}:
                        continue
                except Exception:
                    pass  # BL isn't our problem here — don't crash on it
            
            # Any plugin file means it's not pluginless
            has_plugin = (
                any(mod_folder.glob("*.esp")) or 
                any(mod_folder.glob("*.esm")) or 
                any(mod_folder.glob("*.esl"))
            )
            if has_plugin:
                continue
            
            # Need actual asset content to be BOS-relevant
            has_meshes = (mod_folder / "meshes").exists()
            has_textures = (mod_folder / "textures").exists()
            if not has_meshes and not has_textures:
                continue
            
            # Tag with BOS signatures so every category filter lets them through
            sigs = set(BOS_SIGNATURES)
            
            # Fake ManifestEntry — OR just needs lo_index and signatures
            entry = SimpleNamespace(
                signatures=sigs,
                lo_index=9999,  # No load order — park at the end
                is_blessed=False,
                is_pluginless=True,
                mod_folder=name
            )
            result[name] = entry
        
        return result
    # ---------- NEW: Silo Data Routing ----------
    
    silo_data_ready = pyqtSignal(str, object)

    # silo_data_ready emits:
    #   ("SP", [plugin_names]) — SkyPatcher filtered plugins
    #   ("BOS_MODS", [mod_names]) — BOS UI mod list
    #   ("BOS_PLUGINS", [plugin_names]) — BOS scan plugin list
    def rule_the_combos(self, silo_type: str, category: str = "") -> None:
        """Passes to One Ring – central combo coordinator."""
        if not self._pm_ready:
            return
        
        if silo_type == "SP":
            self.one_ring.populate_sp_combos(category)
        elif silo_type == "BOS":
            self.one_ring.populate_bos_combos(category)
        
        self._update_generate_button()

    def _populate_sp_combos(self, category: str = "") -> None:
        """FORWARDING STUB – Logic moved to One Ring."""
        if hasattr(self, 'one_ring') and self.one_ring:
            self.one_ring.populate_sp_combos(category)

        """FORWARDING STUB – Logic moved to One Ring."""
        if hasattr(self, 'one_ring') and self.one_ring:
            self.one_ring.populate_bos_combos(category)
                
    def refresh_silos(self) -> None:
        """
        Orchestrates silo refresh - sync if cached, async if heavy.
        Prevents UI freeze by chucking Frankie to background thread.
        """
        if not self.profile_manager:
            self.log_warning("PM not initialized, deferring refresh")
            return
        
        # Get signature FIRST (needed for both paths)
        current_sig = self.profile_manager._get_loadorder_signature()
        cache_valid = self.profile_manager._is_silo_cache_valid(current_sig)
        worker_active = getattr(self, '_active_scan_worker', None) is not None
        
        self.log_info(f"REFRESH_PATH: cache_valid={cache_valid}, worker_active={worker_active}")
        
        # Fast path: cache valid - run sync (milliseconds)
        if cache_valid:
            self.log_info("Cache valid - fast refresh")
            self.profile_manager.refresh_silos()
            return
            
        # Slow path: already running?
        if worker_active:
            self.log_info("Background scan already spinning")
            return
            
        # Slow path: chuck to threadpool so UI breathes
        self.log_info("Cache stale - starting background Frankie")
        worker = ScanWorker(self.profile_manager)
        self._active_scan_worker = worker
        self.threadpool.start(worker)

    def get_cached_silo(self, silo_type: str) -> List[str]:
        """Get names from rich silo storage."""
        if not self.profile_manager:
            return []
            
        # Memory first - rich silos are live
        rich = self._rich_silos.get(silo_type, {})
        if rich:
            return list(rich.keys())
            
        # Disk fallback - v3 cache has rich objects
        cache = self.profile_manager._load_silo_cache()
        if cache and silo_type in cache:
            return list(cache[silo_type].keys())
        return []

    def _warm_keyword_cache(self) -> None:
        """Load keyword/keywords.ini – handles duplicate keys SkyPatcher-style."""
        keywords_path = self.plugin_path / "keyword" / "keywords.ini"
        if not keywords_path.exists():
            self._handle_worker_log_line("keywords.ini not found at keyword/keywords.ini", MO2_LOG_DEBUG)
            return
        
        try:
            content = keywords_path.read_text(encoding='utf-8')
            current_section = None
            
            for line in content.splitlines():
                line = line.strip()
                
                # Skip empty and comments
                if not line or line.startswith(';'):
                    continue
                
                # New section [category]
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1].upper()
                    # Map full-word sections to 4-letter record type codes
                    current_section = KEYWORD_SECTION_MAP.get(current_section, current_section)
                    continue
                
                # Parse key=value pairs
                if '=' in line and current_section:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Extract keywordsToAdd
                    if 'keywordstoadd' in value.lower():
                        parts = value.lower().split('keywordstoadd=')
                        if len(parts) > 1:
                            keyword = parts[1].split(':')[0].strip()
                            if keyword:
                                if current_section not in self._keyword_cache:
                                    self._keyword_cache[current_section] = []
                                if keyword not in self._keyword_cache[current_section]:
                                    self._keyword_cache[current_section].append(keyword)

                        # Store the INI key as a filter expression
                        if current_section not in self._filter_cache:
                            self._filter_cache[current_section] = []
                        if key not in self._filter_cache[current_section]:
                            self._filter_cache[current_section].append(key)
                            
            # Sort all lists
            for cat in self._keyword_cache:
                self._keyword_cache[cat] = sorted(self._keyword_cache[cat])
            
            self._handle_worker_log_line(f"keywords.ini loaded: {len(self._keyword_cache)} categories", MO2_LOG_INFO)
            
        except Exception as e:
            self._handle_worker_log_line(f"keywords.ini parse error: {e}", MO2_LOG_WARNING)

    def _extract_category_from_filename(self, filename: str) -> str:
        """Map keyword filename to record category."""
        name_upper = filename.upper()
        mappings = {
            "WEAP": ["WEAP", "WEAPON"],
            "ARMO": ["ARMO", "ARMOR"], 
            "AMMO": ["AMMO"],
            "ALCH": ["ALCH", "POTION", "FOOD"],
            "BOOK": ["BOOK", "SCROLL"],
            "MISC": ["MISC", "MISCELLANEOUS"],
            "INGR": ["INGR", "INGREDIENT"],
            "KEYM": ["KEYM", "KEY"],
            "FURN": ["FURN", "FURNITURE"],
            "LVLI": ["LVLI", "LEVELED", "LEVELEDITEM"],
            "LVLC": ["LVLC", "LEVELEDLISTC", "CREATURE"],
            "NPC_": ["NPC_", "NPC", "ACTOR"],
            "CONT": ["CONT", "CONTAINER"],
            "SPEL": ["SPEL", "SPELL", "MAGIC"],
            "RACE": ["RACE", "RACES"],
            "FLST": ["FLST", "FORMLIST"],
        }
        for category, patterns in mappings.items():
            if any(p in name_upper for p in patterns):
                return category
        return ""

    def parse_keyword_ini(self, path) -> dict:
        """Diagnostic parser for keyword INI with heavy logging."""
        filters = {}
        if not path.exists():
            self._handle_worker_log_line(f"KEYWORD_INI: File not found {path}", MO2_LOG_DEBUG)
            return filters
        
        try:
            with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()
                lines = content.splitlines()
                self._handle_worker_log_line(f"KEYWORD_INI: Reading {path.name} ({len(lines)} lines)", MO2_LOG_DEBUG)
                
                keyword_count = 0
                for i, raw_line in enumerate(lines):
                    line = raw_line.strip()
                    if not line or line.startswith(';'):
                        continue
                    
                    # Debug: log first few non-comment lines to see format
                    if i < 10:
                        self._handle_worker_log_line(f"KEYWORD_INI: Line {i}: '{line[:60]}...'", MO2_LOG_DEBUG)
                    
                    # Case-insensitive check
                    upper_line = line.upper()
                    if upper_line.startswith('KEYWORD = '):
                        val_part = line[10:]  # After "Keyword = "
                        name_part, _, _ = val_part.partition('|')
                        name = name_part.strip()
                        if name:
                            filters[name] = val_part
                            keyword_count += 1
                            if keyword_count <= 3:  # Log first 3 matches
                                self._handle_worker_log_line(f"KEYWORD_INI: -> Found keyword '{name}'", MO2_LOG_DEBUG)
                
                self._handle_worker_log_line(f"KEYWORD_INI: Parsed {keyword_count} keywords from {path.name}", MO2_LOG_DEBUG)
                
        except Exception as e:
            self._handle_worker_log_line(f"KEYWORD_INI parse error {path.name}: {e}", MO2_LOG_WARNING)
            import traceback
            self._handle_worker_log_line(traceback.format_exc(), MO2_LOG_DEBUG)
        
        return filters

    def _load_keyword_chain(self) -> Dict[str, List[str]]:
        """Load category inheritance from keyword/keywords.ini [CHAIN] section."""
        chain_path = self.plugin_path / "keyword" / "keywords.ini"
        chain: Dict[str, List[str]] = {}
        
        if not chain_path.exists():
            self._handle_worker_log_line("CHAIN_INI_MISSING: No keyword/keywords.ini found", MO2_LOG_DEBUG)
            return chain
        
        try:
            content = chain_path.read_text(encoding='utf-8')
            in_chain = False
            
            for raw in content.splitlines():
                line = raw.strip()
                if not line or line.startswith(';'):
                    continue
                    
                if line.upper() == '[CHAIN]':
                    in_chain = True
                    continue
                    
                if in_chain:
                    # Stop at next section header
                    if line.startswith('[') and line.endswith(']'):
                        break
                        
                    if '=' in line:
                        category, links = line.split('=', 1)
                        category = category.strip().upper()
                        chain[category] = [
                            l.strip().upper() 
                            for l in links.split(',') 
                            if l.strip()
                        ]
            
            self._handle_worker_log_line(
                f"CHAIN_LOADED: {len(chain)} categories from keywords.ini", 
                MO2_LOG_DEBUG
            )
                
        except Exception as e:
            self._handle_worker_log_line(f"CHAIN_LOAD_FAIL: {e}", MO2_LOG_ERROR)
        
        return chain

    def get_keywords_for_category(self, category: str) -> list[str]:
        """Pull keywords for category. If category chains to others, merge them."""
        if not category:
            return []
        
        cat_upper = category.upper()
        results = []

        # Filter combo source: INI keys (left side of =)
        if hasattr(self, '_filter_cache') and cat_upper in self._filter_cache:
            results.extend(self._filter_cache[cat_upper])

        # Chain inheritance
        if not hasattr(self, '_chain_cache'):
            self._chain_cache = self._load_keyword_chain()
        if cat_upper in self._chain_cache:
            for linked in self._chain_cache[cat_upper]:
                linked_up = linked.upper()
                if hasattr(self, '_filter_cache') and linked_up in self._filter_cache and linked_up != cat_upper:
                    results.extend(self._filter_cache[linked_up])

        return sorted(set(results))

    def create_generation_worker(self, active_plugins: Optional[List[str]] = None, target_plugins: Optional[List[str]] = None) -> GenerationWorker:
        """Factory for SP worker – injects all required component refs."""
        # ---- Helper: dict or dataclass ----
        def _get(entry, key, default=None):
            if isinstance(entry, dict):
                return entry.get(key, default)
            return getattr(entry, key, default)
        
        all_silos = self._rich_silos
        sp_silo: dict = {}
        
        if isinstance(all_silos, dict):
            if "SP" in all_silos and isinstance(all_silos["SP"], dict):
                sp_silo = all_silos["SP"]
            else:
                # Flat fallback
                for key, entry in all_silos.items():
                    if _get(entry, 'silo_type', '') == 'SP':
                        name = key.split(':', 1)[-1] if ':' in key else key
                        sp_silo[name] = entry
        
        sorted_targets = sorted(
            sp_silo.keys(),
            key=lambda name: _get(sp_silo[name], 'lo_index', 9999)
        )
        
        worker = GenerationWorker(
            active_plugins=sorted_targets,
            target_plugins=sorted_targets,
            organizer_wrapper=self.organizer_wrapper,
            file_operations_manager=self.file_ops,
            plugin_extractor=self.plugin_extractor,
            patch_generator=self.patch_gen,
            data_exporter=self.data_exporter,
            app_config=self.app_config,
            patch_settings=self.patch_settings,
            cache_manager=self.cache,
            parent=self,
        )
        return worker

    def on_generate_sp_patch(self):
        """SP generation dispatcher."""
        self._session_buffer = []
        self.log_info("Controller: SP generation initiated")
        self._save_current_ui_config_to_models()
        
        # Full load order for FormID resolution context — must match MO2 exactly
        lo_map = self.profile_manager.get_load_order_map()
        full_plugin_list = [lo_map[i] for i in sorted(lo_map.keys())]
        
        # Filtered silo for extraction — already blacklist-screened, sorted by LO index
        sp_silo = self._rich_silos.get("SP", {})
        target_plugins = sorted(
            sp_silo.keys(),
            key=lambda name: getattr(sp_silo.get(name), 'lo_index', 9999)
        )
        self.log_info(f"SP_GEN: {len(target_plugins)} plugins from filtered silo")
        
        worker = self.create_generation_worker(
            active_plugins=full_plugin_list,      # Full LO for FormID prefix math
            target_plugins=target_plugins         # Filtered subset for extraction
        )
        
        # Wire signals
        worker.signals.log_line.connect(self._handle_worker_log_line)
        worker.signals.gen_progress.connect(self._handle_generation_progress)
        worker.signals.generation_finished.connect(self._handle_generation_finished)
        worker.signals.error_occurred.connect(self._handle_worker_error)
        
        # Cleanup wiring
        def cleanup():
            self.generation_worker = None
            self._generation_in_progress = False
        
        worker.signals.generation_finished.connect(cleanup)
        worker.signals.error_occurred.connect(cleanup)
        
        self.activity_indicator_toggle.emit(True)
        self.generation_worker = worker          # <-- ASSIGN FIRST
        self._generation_in_progress = True      # <-- FLAG SECOND
        self.threadpool.start(worker)            # <-- START LAST

    def _handle_worker_error(self, error_title: str, error_message: str) -> None:
        """Catch worker errors without crashing the UI."""
        self._generation_in_progress = False
        self.activity_indicator_toggle.emit(False)
        self._handle_worker_log_line(f"Worker error: {error_message}", MO2_LOG_ERROR)

    # ---------- ui glue ----------

    def set_ui_widgets_for_access(self, widgets_dict: Dict[str, Any]) -> None:
        self.ui_widgets = widgets_dict
        self.sp_panel = widgets_dict["sp_panel"]
        self.bos_panel = widgets_dict["bos_panel"]
        
        # Seed SP category combo – OR owns the brain
        if hasattr(self, 'one_ring') and self.one_ring:
            self.one_ring.populate_sp_category(self.sp_panel)

        # Target/Source live persistence - SP was missing this
        self.sp_panel.target_mod_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'target_mod', text.strip()))
        self.sp_panel.source_mod_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'source_mod', text.strip()))
        
        self._handle_worker_log_line(f"UI widgets registered: {list(self.ui_widgets.keys())}", MO2_LOG_DEBUG)

        # BOS (direct – controller populates in _try_populate_combos)
        self.bos_panel.rows_changed.connect(self._on_bos_rows_changed, Qt.ConnectionType.QueuedConnection)

        # Category persistence - triggers on every combo change
        self.sp_panel.category_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'category', text))

        self.sp_panel.gen_modlist_cb.toggled.connect(self._update_generate_button)
        self.sp_panel.gen_all_cats_cb.toggled.connect(self._update_generate_button)
        self.sp_panel.target_mod_combo.currentTextChanged.connect(self._update_generate_button)
        self.sp_panel.category_combo.currentTextChanged.connect(self._update_generate_button)
        self.sp_panel.output_folder_input.textChanged.connect(self._update_generate_button)
        self.sp_panel.speed_mode_rb.toggled.connect(self._update_generate_button)
        self.sp_panel.space_saver_mode_rb.toggled.connect(self._update_generate_button)
        # Sentence Builder persistence
        self.sp_panel.filter_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'sp_filter_type', text))
        self.sp_panel.action_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'sp_action_type', text))
        self.sp_panel.value_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'sp_value_formid', text))
        self.sp_panel.lmw_toggle.toggled.connect(
            lambda checked: setattr(self.patch_settings, 'sp_lmw_winners_only', checked))
        self.sp_panel.category_combo.currentTextChanged.connect(
            lambda text: setattr(self.patch_settings, 'category', text))  
        
    def connect_ui_elements(self) -> None:
        if getattr(self, '_ui_signals_connected', False):
            return
        self._ui_signals_connected = True
        if not self.ui_widgets:
            self._handle_worker_log_line("UI widgets not available for signal connection.", MO2_LOG_WARNING)
            return

        # output folder
        self.ui_widgets["game_version_se_radio"].toggled.connect(
            lambda: self._on_game_version_changed("SkyrimSE")
            if self.ui_widgets["game_version_se_radio"].isChecked() else None)
        self.ui_widgets["game_version_vr_radio"].toggled.connect(
            lambda: self._on_game_version_changed("SkyrimVR")
            if self.ui_widgets["game_version_vr_radio"].isChecked() else None)

        self.ui_widgets["output_type_se_radio"].toggled.connect(
            lambda: self._on_output_type_changed("SkyPatcher INI")
            if self.ui_widgets["output_type_se_radio"].isChecked() else None)
        self.ui_widgets["output_type_bos_radio"].toggled.connect(
            lambda: self._on_output_type_changed("BOS INI")
            if self.ui_widgets["output_type_bos_radio"].isChecked() else None)

        # global flags
        self.ui_widgets["debug_logging_checkbox"].toggled.connect(self._on_debug_logging_changed)
        self.ui_widgets["traceback_logging_checkbox"].toggled.connect(self._on_traceback_logging_changed)
        self.app_config.dev_settings_hidden = self.main_dialog.hide_dev_btn.isChecked()

        # dialog
        self.ui_widgets["main_dialog"].accepted.connect(self.on_dialog_accepted)
        self.ui_widgets["main_dialog"].rejected.connect(self.on_dialog_rejected)
        self.ui_widgets["main_dialog"].finished.connect(self.on_dialog_close)

        # BOS ready-state
        self.bos_panel.target_combo.currentIndexChanged.connect(self._update_generate_button)
        self.bos_panel.scan_all_cb.toggled.connect(self._update_generate_button)

        # stop button
        self.sp_panel.stop_button.clicked.connect(self.on_stop_clicked)

        self._handle_worker_log_line("UI signals connected to controller slots.", MO2_LOG_DEBUG)


    def _update_generate_button(self) -> None:
        """Refresh generate button state based on active panel readiness."""
        is_sp_active = self.main_dialog.panel_stack.currentIndex() == 0
        
        if is_sp_active:
            ready = self.sp_panel.is_ready()
            self.sp_panel.generate_btn.setEnabled(ready)
        else:
            ready = self.bos_panel.is_ready()
            self.bos_panel.generate_btn.setEnabled(ready)

    def _validate_output_folder(self, folder_path: str, worker_callback) -> Optional[Path]:
        """Returns Path if valid, emits errors via callback if not."""
        if not folder_path:
            worker_callback("Please specify an output folder.", MO2_LOG_WARNING)
            return None
        path = Path(folder_path)
        if not path.is_dir():
            if not self.file_ops.create_directory(path):
                worker_callback("Failed to create output directory.", MO2_LOG_CRITICAL)
                return None
        return path

    # ---------- slots ----------
    def _on_bos_rows_changed(self, rows: List[Dict[str, Any]]) -> None:
        self._handle_worker_log_line(f"BOS FormID overrides updated: {len(rows)} rows", MO2_LOG_DEBUG)

    # ---------- config save ----------
    def _save_current_ui_config_to_models(self) -> None:
        self._handle_worker_log_line(f"SAVE_UI_START – app_config id: {id(self.app_config)}", MO2_LOG_INFO)
        self._handle_worker_log_line(f"SAVE_UI – patch_settings id: {id(self.patch_settings)}", MO2_LOG_INFO)
        if not self.ui_widgets:
            self._handle_worker_log_line("UI widgets not available for config saving.", MO2_LOG_WARNING)
            return

        # game / output
        if self.ui_widgets["game_version_se_radio"].isChecked():
            self.app_config.game_version = "SkyrimSE"
        elif self.ui_widgets["game_version_vr_radio"].isChecked():
            self.app_config.game_version = "SkyrimVR"

        old_type = self.app_config.output_type
        if self.ui_widgets["output_type_se_radio"].isChecked():
            self.app_config.output_type = "SkyPatcher INI"
        elif self.ui_widgets["output_type_bos_radio"].isChecked():
            self.app_config.output_type = "BOS INI"

        # SP panel
        sp = self.sp_panel
        ps = self.patch_settings
        # Read from the actual widgets, not the stale property shadows
        # Panel properties got set during restore but never update when user picks stuff
        ps.target_mod           = sp.target_mod_combo.currentText().strip()
        ps.source_mod           = sp.source_mod_combo.currentText().strip()
        ps.category             = sp.category_combo.currentText().strip()
        ps.keywords             = sp.category_combo.currentText().strip()
        ps.skypatcher_output_folder = sp.output_folder_input.text().strip() if hasattr(sp, 'output_folder_input') else sp.output_folder_path
        ps.generate_all_categories = sp.gen_all_cats_cb.isChecked() if hasattr(sp, 'gen_all_cats_cb') else sp.generate_all
        ps.generate_modlist = sp.gen_modlist_cb.isChecked() if hasattr(sp, 'gen_modlist_cb') else False
        ps.generate_modlist = sp.gen_modlist_cb.isChecked() if hasattr(sp, 'gen_modlist_cb') else False
        ps.sp_filter_type = sp.filter_combo.currentText().strip() if hasattr(sp, 'filter_combo') else ""
        ps.sp_action_type = sp.action_combo.currentText().strip() if hasattr(sp, 'action_combo') else ""
        ps.sp_value_formid = sp.value_combo.currentText().strip() if hasattr(sp, 'value_combo') else ""
        ps.sp_lmw_winners_only = sp.lmw_toggle.isChecked() if hasattr(sp, 'lmw_toggle') else True

        # BOS panel
        bos = self.bos_panel
        ps.bos_output_folder        = bos.output_folder
        ps.bos_target_mod           = bos.target_mod  # Grabs from combo via property
        ps.bos_source_mod           = bos.source_mod  # Grabs from combo via property
        ps.bos_xyz                  = ','.join(bos.xyz)
        ps.bos_formids              = json.dumps(bos.form_id_overrides)
        ps.bos_scan_all             = bos.scan_all_cb.isChecked() if hasattr(bos, 'scan_all_cb') else False

        # M2M (Mod-to-Mod) settings from BOS panel
        if hasattr(self.bos_panel, '_m2m_cat_combo'):
            ps.m2m_category = self.bos_panel._m2m_cat_combo.currentText()
        if hasattr(self.bos_panel, '_m2m_chance_spin'):
            ps.m2m_chance = self.bos_panel._m2m_chance_spin.value()

        # global flags
        self.app_config.debug_logging       = self.ui_widgets["debug_logging_checkbox"].isChecked()
        self.app_config.traceback_logging   = self.ui_widgets["traceback_logging_checkbox"].isChecked()
        self.app_config.selected_theme      = self.main_dialog.theme_combo.currentText()
        self.app_config.dev_settings_hidden = self.main_dialog.hide_dev_btn.isChecked()
        # Safety net: if patch_settings dangled from _enter_workspace or anywhere else,
        # force app_config to carry the mutated one that actually has user data
        if hasattr(self.app_config, 'patch_settings') and self.app_config.patch_settings is not self.patch_settings:
            self.app_config.patch_settings = self.patch_settings
        self.config_manager.save_application_config(self.app_config)
        self._handle_worker_log_line("=== SAVE_FINISHED ===", MO2_LOG_INFO)

    # ---------- event handlers ----------
    def _on_game_version_changed(self, version: str) -> None:
        self._handle_worker_log_line(f"Game version changed to: {version}", MO2_LOG_DEBUG)
        self.app_config.game_version = version

    def _on_output_type_changed(self, output_type: str) -> None:
        old_type = self.app_config.output_type
        self._handle_worker_log_line(f"Output type changed: {old_type} → {output_type}", MO2_LOG_DEBUG)
        self.app_config.output_type = output_type
        self.main_dialog.update_ui_for_output_type(output_type)

    def _on_debug_logging_changed(self, state: bool) -> None:
        if not DEBUG_MODE:
            self.app_config.debug_logging = state
            SkyGenLogger().set_debug_mode(state)
            self._handle_worker_log_line(f"Debug logging {'ON' if state else 'OFF'}", MO2_LOG_INFO)

    def _on_traceback_logging_changed(self, state: bool) -> None:
        if not TRACEBACK_LOGGING:
            self.app_config.traceback_logging = state
            SkyGenLogger().set_traceback_logging(state)
            self._handle_worker_log_line(f"Traceback logging {'ON' if state else 'OFF'}", MO2_LOG_INFO)

    def _on_theme_changed(self, theme_name: str) -> None:
        self._handle_worker_log_line(f"Theme changed to: {theme_name}", MO2_LOG_DEBUG)
        self.app_config.selected_theme = theme_name
        self.theme_manager.apply_theme(theme_name)

    # ---------- progress / finish / error ----------
    def _handle_generation_progress(self, progress_info: Dict[str, Any]) -> None:
        status_text = progress_info.get("status", "Processing...")
        level = progress_info.get("level", MO2_LOG_INFO)
        details = progress_info.get("details", "")
        full_status = f"{status_text} - {details}" if details else status_text
        self._handle_worker_log_line(full_status, level)
        self.progress_updated.emit(progress_info)

    def _handle_generation_finished(self, success: bool, output_type: str, message: str) -> None:
        self._generation_in_progress = False
        self.generation_worker = None
        self._handle_worker_log_line(
            f"Generation finished. Success: {success}, Type: {output_type}, Message: {message}", 
            MO2_LOG_INFO
        )
        
        # Goldilocks seal: dump error dedup summary for forensics without 50MB bloat
        SkyGenLogger().finalize_error_summary()
        
        self.activity_indicator_toggle.emit(False)
        self.generation_complete.emit(success, output_type, message)

        if success:
            self.log_info(f"Generation complete: {message}")
        else:
            self.log_error(f"Generation failed: {message}")

        # Clear session buffer to free memory (no file write)
        self._session_buffer.clear()

    # ---------- dialog life-cycle ----------
    def on_dialog_accepted(self) -> None:
        self._handle_worker_log_line("Dialog accepted.", MO2_LOG_INFO)
        self._save_current_ui_config_to_models()

    def on_dialog_rejected(self) -> None:
        self._handle_worker_log_line("Dialog rejected.", MO2_LOG_INFO)

    def on_dialog_close(self) -> None:
        self._handle_worker_log_line("Dialog closed event triggered.", MO2_LOG_INFO)
        if hasattr(self.main_dialog, '_flush_viewer_log_to_disk'):
            self.main_dialog._flush_viewer_log_to_disk()

        if hasattr(self, 'generation_worker') and self.generation_worker:
            self.generation_worker.request_interruption()
            self._handle_worker_log_line("Requested worker interruption on dialog close.", MO2_LOG_INFO)

        if self.threadpool.activeThreadCount() > 0:
            self.threadpool.waitForDone(1000)
            if self.threadpool.activeThreadCount() > 0:
                self._handle_worker_log_line("Worker threads did not finish gracefully within timeout.", MO2_LOG_WARNING)

        if hasattr(self, 'cache') and self.cache:
            if self.patch_settings.cache_mode == "space_saver":
                self.cache.clear_cache()
                self._handle_worker_log_line("Cache cleared (Space Saver mode)", MO2_LOG_INFO)

        self._handle_worker_log_line("Controller shutdown complete.", MO2_LOG_INFO)

    # ---------- logging interface ----------
    def log_info(self, msg: str) -> None:
        self._handle_worker_log_line(msg, MO2_LOG_INFO)

    def log_warning(self, msg: str) -> None:
        self._handle_worker_log_line(msg, MO2_LOG_WARNING)

    def log_error(self, msg: str) -> None:
        self._handle_worker_log_line(msg, MO2_LOG_ERROR)

    def log_critical(self, msg: str, exc_info: bool = False) -> None:
        self._handle_worker_log_line(msg, MO2_LOG_CRITICAL)
        if exc_info:
            import traceback
            self._handle_worker_log_line(traceback.format_exc(), MO2_LOG_CRITICAL)

    def log_debug(self, msg: str) -> None:
        self._handle_worker_log_line(msg, MO2_LOG_DEBUG)

    def log_trace(self, msg: str) -> None:
        self._handle_worker_log_line(msg, MO2_LOG_TRACE)

    # ---------- stop-generation handler ----------
    def on_stop_clicked(self) -> None:
        """Stop button only stops the worker, nothing else."""
        self._handle_worker_log_line("DEBUG: Stop button signal received", MO2_LOG_DEBUG)
        if hasattr(self, 'generation_worker') and self.generation_worker:
            self.generation_worker.request_interruption()
            self._handle_worker_log_line("Stop button clicked – interruption requested", MO2_LOG_INFO)
        else:
            self._handle_worker_log_line("DEBUG: No active worker to stop", MO2_LOG_DEBUG)

    def _on_auditor_rules_changed(self) -> None:
        """Refresh panels directly from audit cache when rules change."""
        self.log_info("Rules changed - refreshing panels from audit cache")
        # Regenerate audit with new rules
        self.profile_manager.generate_audit_cache()
        # One Ring repopulates both panels with current filters
        self.rule_the_combos("SP", self.sp_panel.category_combo.currentText())
        self.rule_the_combos("BOS", self.bos_panel._m2m_cat_combo.currentText())

    def launch_auditor(self, silo: str) -> None:
        from ..ui.auditor_dialog import BlacklistAuditorDialog
        
        audit_data = self.profile_manager.get_audit_cache()
        all_plugins = list(audit_data.keys())
        
        dialog = BlacklistAuditorDialog(
            siloed_snoop=self.siloed_snoop,
            all_plugins=all_plugins,
            silo=silo,
            parent=self.main_dialog
        )
        
       
        dialog.rules_changed.connect(
            self._on_auditor_rules_changed, 
            Qt.ConnectionType.QueuedConnection
        )
        
        dialog.exec()

    def launch_wizard(self, silo: str) -> None:
        """Launch BlacklistWizard for the specified silo."""
        self.log_info(f"Wizard launch requested for silo: {silo}")
        # Future: from ..ui.wizard_dialog import BlacklistWizard
        # dialog = BlacklistWizard(siloed_snoop=self.siloed_snoop, silo=silo, parent=self.main_dialog)
        # dialog.exec()

    @property
    def patch_gen(self):
        """Shortcut for patch_generator."""
        return self.patch_generator

    @patch_gen.setter
    def patch_gen(self, value: PatchAndConfigGenerationManager):
        self.patch_generator = value
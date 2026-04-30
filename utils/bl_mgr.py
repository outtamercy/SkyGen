import hashlib, time, os, configparser, shutil
from pathlib import Path
from typing import Dict, Set, Optional, Any, List, TYPE_CHECKING
from dataclasses import dataclass
from PyQt6.QtCore import QObject # type: ignore
from ..utils.logger import LoggingMixin, MO2_LOG_DEBUG, MO2_LOG_WARNING, MO2_LOG_INFO
from ..utils.sigsnoop import PluginDNA, quick_sniff
from ..core.constants import (
    DATA_DIR_NAME, USER_RULES_FILE_NAME, COLOR_LOCKED, COLOR_USER_BL,
    COLOR_STARRED, COLOR_PARTIAL, COLOR_ACTIVE, ICON_LOCKED, ICON_USER_BL,
    ICON_STARRED, ICON_PARTIAL, ICON_NONE, BYPASS_BLACKLIST, 
    BLESSED_CORE_FILES, PROTECTED_AUTHORS, BLACKLIST_AUTHORS, OFFICIAL_CC_PREFIX, GLOBAL_IGNORE_PLUGINS
)

if TYPE_CHECKING:
    from .pm_mgr import ProfileManager, ManifestEntry

@dataclass
class ModStatus:
    visible: bool; display_name: str; color: str; icon: str; reason: str

class BlacklistManager(LoggingMixin):
    def __init__(self, profile_manager: 'ProfileManager', plugin_path: Path) -> None:
        LoggingMixin.__init__(self)
        self.profile_mgr = profile_manager
        self.plugin_path = plugin_path
        self._user_rules: Dict[str, str] = {}
        self._load_user_rules()
        self._auto_blacklist: Dict[str, str] = {}   # make the bucket first
        self._load_auto_blacklist()                 # then fill it
        self._blacklist_corrupted = False  # Circuit breaker: breaker 19 you got yourself a blacklister on the fritz, better call an electrician
        data_dir = self.plugin_path / DATA_DIR_NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        self.log_debug(f"BlacklistManager data directory ensured: {data_dir}")

    def blacklist_exists(self) -> bool:
        profile_name = self.profile_mgr.wrapper.profile_name
        rules_path = self.plugin_path / DATA_DIR_NAME / USER_RULES_FILE_NAME.format(profile=profile_name)
        return rules_path.exists()   
    
    def _load_user_rules(self) -> None:
        profile_name = self.profile_mgr.wrapper.profile_name
        rules_path = self.plugin_path / DATA_DIR_NAME / USER_RULES_FILE_NAME.format(profile=profile_name)
        if not rules_path.exists():
            return
        try:
            config = configparser.ConfigParser()
            config.read(rules_path, encoding='utf-8')
            if 'UserRules' in config:
                for plugin_name, rule in config['UserRules'].items():
                    self._user_rules[plugin_name.lower()] = rule.lower()
            self.log_info(f"Loaded {len(self._user_rules)} user rules")
        except Exception as e:
            self.log_warning(f"Failed to load user rules: {e}")
    
    def get_mod_status(self, plugin_name: str, silo: str, category: Optional[str] = None) -> ModStatus:
        """Get full status for Auditor UI - preserves original plugin_name casing."""
        
        # === GLOBAL IGNORE SHIELD (Tier -1) ===
        # Hardcoded utility mods (SkyUI, RaceMenu, etc.) never contain patchable records
        # Snoop drops these at extraction layer; BL marks 🔒 for UI transparency
        if plugin_name in GLOBAL_IGNORE_PLUGINS:
            return ModStatus(
                visible=False,  # Hidden from active silos
                display_name=f"{plugin_name} [Global Ignore]",
                color=COLOR_LOCKED,
                icon=ICON_LOCKED,
                reason="global_ignore"
            )
        
        # === TIER 0: BLESSED CORE ===
        # Single source of truth: manifest entry or audit cache, not hardcoded constants
        entry = self.profile_mgr.get_plugin_data(plugin_name)
        if entry and entry.is_blessed:
            return ModStatus(True, plugin_name, COLOR_ACTIVE, ICON_NONE, "vanilla")
        
        audit = self.profile_mgr.get_audit_cache()
        baseline = audit.get(plugin_name, {})
        if baseline.get('is_blessed', False):
            return ModStatus(True, plugin_name, COLOR_ACTIVE, ICON_NONE, "vanilla")
        display_name = baseline.get('display_name', plugin_name)  # Falls back to original if missing
        status = baseline.get('status', 'active')
        reason = baseline.get('reason', 'content')
        color = baseline.get('color', COLOR_ACTIVE)
        icon = baseline.get('icon', ICON_NONE)
        
        plugin_lower = plugin_name.lower()  # Local only for dict lookups
        if plugin_lower in self._user_rules:
            rule = self._user_rules[plugin_lower]
            if rule == "whitelist":
                status, reason, color, icon = "active", "user_whitelist", COLOR_STARRED, ICON_STARRED
            elif rule == "blacklist":
                status, reason, color, icon = "locked", "user_blacklist", COLOR_USER_BL, ICON_USER_BL
        
        return ModStatus(visible=(status == "active"), display_name=display_name, color=color, icon=icon, reason=reason)
    
    def set_user_rule(self, plugin_name: str, rule: Optional[str]) -> None:
        plugin_lower = plugin_name.lower()
        if rule is None:
            if plugin_lower in self._user_rules:
                del self._user_rules[plugin_lower]
        else:
            self._user_rules[plugin_lower] = rule.lower()
        self._save_user_rules()
    
    def _save_user_rules(self) -> None:
        profile_name = self.profile_mgr.wrapper.profile_name
        rules_path = self.plugin_path / DATA_DIR_NAME / USER_RULES_FILE_NAME.format(profile=profile_name)
        try:
            config = configparser.ConfigParser()
            clean_rules = {name: rule for name, rule in self._user_rules.items() if name and rule}
            if clean_rules:
                config['UserRules'] = clean_rules
            with open(rules_path, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception as e:
            self.log_warning(f"Failed to save user rules: {e}")

    def is_eligible_for_silo(self, entry: 'ManifestEntry', plugin_name: str, silo: str) -> bool:
        """
        Central decision engine: should this plugin appear in combo for this silo?
        Checks: global ignore > blessed shield > user rules > auto-blacklist > layer suitability
        """
        # Hardcoded utility mods (SkyUI, RaceMenu, Synthesis, etc.)
        # They live in the audit for the Auditor, but never enter generation silos
        if plugin_name in GLOBAL_IGNORE_PLUGINS and silo in ('SP', 'BOS'):
            return False
            
        # Layer 0: GLOBAL framework = never eligible for any content silo
        # Blessed base game plugins are exempt - they carry all record types
        if entry.layer == 'global' and not entry.is_blessed:
            return False
            
        # Blessed shield: vanilla masters always eligible regardless of signatures
        if entry.is_blessed or plugin_name in BLESSED_CORE_FILES:
            return True
            
        # User rules override everything else
        plugin_lower = plugin_name.lower()
        if plugin_lower in self._user_rules:
            return self._user_rules[plugin_lower] != 'blacklist'
        
        # Auto-blacklist check
        if plugin_lower in self._auto_blacklist:
            return False
            
        # Layer check: must match silo type or be hybrid
        if entry.layer == 'sp' and silo not in ('SP',):
            return False
        if entry.layer == 'bos' and silo not in ('BOS',):
            return False
        # Hybrid passes all silos
            
        return True

    def add_auto_blacklist(self, plugin_name: str, reason: str) -> None:
        # Breaker 19 - if the board is fried, don't touch the wires
        if getattr(self, '_blacklist_corrupted', False):
            return
            
        plugin_lower = plugin_name.lower()
        if plugin_lower in self._user_rules:
            return
        if plugin_lower not in self._auto_blacklist:
            self._auto_blacklist[plugin_lower] = reason
            self.log_info(f"AUTO_BL_STAGED: {plugin_name} = {reason}")

    def _save_auto_blacklist(self) -> None:
        """Flush auto-blacklist to disk. Direct write, no rename dance."""
        if self._blacklist_corrupted:
            return
        if not self._auto_blacklist:
            return
            
        profile_name = self.profile_mgr.wrapper.profile_name
        rules_path = self.plugin_path / DATA_DIR_NAME / USER_RULES_FILE_NAME.format(profile=profile_name)
        
        try:
            config = configparser.ConfigParser()
            if rules_path.exists():
                try:
                    config.read(rules_path, encoding='utf-8')
                except configparser.DuplicateSectionError as e:
                    self._blacklist_corrupted = True
                    self.log_critical(f"BLACKLIST_CORRUPT: Duplicate section {e.section}. All writes disabled.")
                    return
                except Exception as read_e:
                    self.log_error(f"INI read failed: {read_e}")
                    return
            
            if 'AutoBlacklist' not in config:
                config['AutoBlacklist'] = {}
            
            write_count = 0
            for plugin_lower, reason in self._auto_blacklist.items():
                if plugin_lower not in config['AutoBlacklist']:
                    config['AutoBlacklist'][plugin_lower] = reason
                    write_count += 1
            
            if write_count == 0:
                return
                
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            # Direct write — open, dump, close. No temp file.
            with open(rules_path, 'w', encoding='utf-8') as f:
                config.write(f)
                f.flush()
                os.fsync(f.fileno())
            self.log_info(f"AUTO_BL_FLUSH: {write_count} entries -> {rules_path.name}")
            
        except Exception as e:
            self.log_error(f"AUTO_BL_FLUSH_FAILED🚽: {e}")

    def _load_auto_blacklist(self) -> None:
        profile_name = self.profile_mgr.wrapper.profile_name
        rules_path = self.plugin_path / DATA_DIR_NAME / USER_RULES_FILE_NAME.format(profile=profile_name)
        self._auto_blacklist: Dict[str, str] = {}
        if not rules_path.exists():
            return
        try:
            config = configparser.ConfigParser()
            config.read(rules_path, encoding='utf-8')
            if 'AutoBlacklist' in config:
                for plugin_name, reason in config['AutoBlacklist'].items():
                    self._auto_blacklist[plugin_name.lower()] = reason.lower()
                self.log_debug(f"AUTO_BL_LOAD: {len(self._auto_blacklist)} entries")
        except Exception as e:
            self.log_warning(f"Failed to load auto-blacklist: {e}")

    def _is_blacklisted(self, plugin_name: str, entry: 'ManifestEntry') -> bool:
        """Layer-aware blacklist: GLOBAL = always locked, others = content-based."""
        
        # --- LAYER 0: GLOBAL (Hard Framework) ---
        if entry.layer == 'global':
            return True  # Always blacklisted, regardless of other factors

        plugin_lower = plugin_name.lower()
        
        # --- LAYER 1: BLESSED (Vanilla/CC) ---
        if entry.file_hash.startswith('BLESSED_') or entry.is_blessed:
            return False
        
        # --- LAYER 2/3/4: BOS/SP/HYBRID (Content) ---
        # Asset anchor check (Project Clarity protection)
        if getattr(entry, 'lc_score', 50) == 0:
            return False
        
        # ⚡ FAST-PASS: Absolute framework scents (BOS/SkyPatcher detected in folder)
        if entry.folder_scents:
            if "BOS_FRAMEWORK" in entry.folder_scents or "SKYPATCHER_FRAMEWORK" in entry.folder_scents:
                self.log_info(f"AUTO_BL_SCENT: {plugin_name} ({entry.folder_scents})")
                return True
        
        # 📊 RATIO CHECK: Script-heavy detection (>0.8 ratio, >50 records)
        if entry.logic_to_content_ratio > 0.8 and len(entry.signatures) > 50:
            self.log_info(f"AUTO_BL_RATIO: {plugin_name} (ratio: {entry.logic_to_content_ratio:.2f})")
            return True
                
        # Build DNA for legacy checks
        dna = PluginDNA(
            signatures=entry.signatures,
            author=entry.author,
            masters=entry.masters,
            is_esm=False,
            is_esl=False,
            file_size=entry.size,
            mtime=entry.mtime,
            object_signatures=entry.object_signatures,
            logic_signatures=entry.logic_signatures,
            logic_to_content_ratio=entry.logic_to_content_ratio,
            folder_scents=entry.folder_scents
        )
        
        # 🔒 LEGACY FRAMEWORK CHECK
        if dna.is_framework and not entry.is_partial:
            return True
        
        # PARTIALS: Never blacklisted
        if entry.is_partial:
            return False

        # 🛡️ OFFICIAL SHIELD
        is_official = (
            plugin_lower in [p.lower() for p in BLESSED_CORE_FILES] or
            plugin_lower.startswith(OFFICIAL_CC_PREFIX) or
            entry.author.lower() in [a.lower() for a in PROTECTED_AUTHORS]
        )
        
        if is_official and dna.is_framework:
            return False
                
        if dna.is_framework:
            return True
        
        author_lower = entry.author.lower()
        for bl_author in BLACKLIST_AUTHORS:
            if bl_author.lower() in author_lower:
                return True
        
        if not entry.signatures and not entry.masters:
            return True
        
        return False
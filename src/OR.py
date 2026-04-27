# or.py – One Ring to rule the combos, bind the threading, and find the damn assets
# Sectioned: SP logic | BOS logic | Workers | ThreadPool glue

from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool, Qt
from PyQt6.QtWidgets import QComboBox

from ..utils.logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_DEBUG, MO2_LOG_WARNING
from ..core.constants import (
    SKYPATCHER_SUPPORTED_RECORD_TYPES, 
    SIGNATURE_TO_FILTER, FILTER_TO_ACTIONS, BLESSED_CORE_FILES,
    CATEGORY_FILTER_ALIASES, BOS_CATEGORIES, BOS_SIGNATURES
)

class FidScanner(QRunnable):
    """Heavy lifter for BOS FID scanning – keeps UI breathing."""
    
    def __init__(self, processor, plugin_files, mod_names, category, 
                 abort_flag, progress_callback, active_plugins, completion_callback):
        super().__init__()
        self.processor = processor
        self.plugin_files = plugin_files
        self.mod_names = mod_names
        self.category = category
        self.abort_flag = abort_flag
        self.progress_callback = progress_callback
        self.active_plugins = active_plugins
        self.completion_callback = completion_callback  # Called with results

    def run(self):
        """Grind through plugins in background thread."""
        try:
            results = self.processor.scan_plugins(
                plugin_files=self.plugin_files,
                mod_names=self.mod_names,
                category=self.category,
                abort_flag=self.abort_flag,
                progress_callback=self.progress_callback,
                active_plugins=self.active_plugins
            )
            self.completion_callback(results)
        except Exception as e:
            self.completion_callback([])  # Empty on fail

class OneRing(QObject, LoggingMixin):
    """Central combo & threading coordinator – SP and BOS sections walled off."""
    
    # Signals for async operations
    fid_scan_complete = pyqtSignal(list)  # Results back to BOS panel
    modlist_progress = pyqtSignal(str, int)  # Status updates
    
    def __init__(self, controller, profile_manager, blacklist_manager):
        QObject.__init__(self)
        LoggingMixin.__init__(self)
        
        self.controller = controller
        self.pm = profile_manager
        self.bl = blacklist_manager
        
        # Thread pool for background ops
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(2)  # FID scan + modlist gen can coexist
        
        # Cache for keywords (avoid disk hits)
        self._keyword_cache: Dict[str, List[str]] = {}
        
        # Current constraint state for bidirectional linking
        self._sp_current_category: str = ""
        self._sp_current_target_mod: str = ""
        self._sp_current_source_mod: str = ""

        # Cache for silo data
        self._cached_silos: Dict[str, Dict[int, str]] = {
            "SP": {},
            "BOS_MODS": {},
        }

    # ============================================================
    # SP SECTION – SkyPatcher combo logic & auto-link
    # ============================================================
    
    def populate_sp_combos(self, category_filter: str = "") -> None:
        """Fill SP target/source - asks BlacklistManager for visibility."""
        if not self.controller.sp_panel or not self.controller.blacklist_mgr:
            return
            
        rich_sp = self.controller._rich_silos.get("SP", {})
        
        if not rich_sp:
            self.log_warning("SP silo empty")
            return
        
        compatible = []
        cat_sig = category_filter.strip().upper() if category_filter else ""
        check_sigs = CATEGORY_FILTER_ALIASES.get(cat_sig, {cat_sig}) if cat_sig else set()
        
        for plugin_name, entry in rich_sp.items():
            # Ask BlacklistManager: visible for SP silo?
            if not self.controller.blacklist_mgr.is_eligible_for_silo(entry, plugin_name, 'SP'):
                continue
            
            # Category signature check
            if cat_sig:
                entry_sigs = getattr(entry, 'signatures', set())
                if not entry_sigs.intersection(check_sigs):
                    continue
            
            compatible.append(plugin_name)
        
        # Sort by LO index...
        def get_lo_index(name):
            entry = rich_sp.get(name)
            return getattr(entry, 'lo_index', 9999)
        
        compatible.sort(key=get_lo_index)
        
        # Populate combos...
        self.log_debug(f"SP combo population: {len(compatible)} plugins (category={category_filter}, aliases={check_sigs})")
        
        panel = self.controller.sp_panel
        
        old_target = panel.target_mod_combo.currentText()
        old_source = panel.source_mod_combo.currentText()
        
        panel.target_mod_combo.blockSignals(True)
        panel.source_mod_combo.blockSignals(True)
        
        for combo in (panel.target_mod_combo, panel.source_mod_combo):
            combo.clear()
            combo.addItem("")
            combo.addItems(compatible)
        
        if old_target in compatible:
            panel.target_mod_combo.setCurrentText(old_target)
        else:
            panel.target_mod_combo.setCurrentText("")
            if old_target:
                self.log_info(f"Target cleared: '{old_target}' has no {category_filter} records")
            
        if old_source in compatible:
            panel.source_mod_combo.setCurrentText(old_source)
        else:
            panel.source_mod_combo.setCurrentText("")
            if old_source:
                self.log_info(f"Source cleared: '{old_source}' has no {category_filter} records")
            
        panel.target_mod_combo.blockSignals(False)
        panel.source_mod_combo.blockSignals(False)

    def apply_sp_constraints(self, changed_field: str, new_value: str) -> None:
        """
        Bidirectional constraint engine – the heart of auto-link.
        changed_field: 'category' | 'target_mod' | 'source_mod'
        """
        panel = self.controller.sp_panel
        if not panel:
            return
            
        # Update our tracking
        if changed_field == 'category':
            self._sp_current_category = new_value
            # Category changed → Filter mods to those with this signature
        if new_value and new_value.strip():
            self.populate_sp_combos(new_value)
                
        elif changed_field == 'target_mod':
            self._sp_current_target_mod = new_value
            # Mod selected → Restrict categories to those present in this mod
            if new_value and new_value.strip():
                valid_categories = self._get_mod_categories(new_value)
                self._restrict_category_combo(panel, valid_categories)
                # Auto-suggest source if empty (Last-Mod-Wins logic)
                if not panel.source_mod_combo.currentText():
                    self._suggest_source_for_target(panel, new_value)
                    
        elif changed_field == 'source_mod':
            self._sp_current_source_mod = new_value

    def auto_link_categories(self, category: str) -> None:
        """
        Public entry for panel to call when category changes.
        Delegates to constraint engine.
        """
        self.apply_sp_constraints('category', category)

    def _filter_mods_by_signature(self, mod_names: List[str], signature: str) -> List[str]:
        """Filter to mods containing this signature or its aliases."""
        rich_sp = self.controller._rich_silos.get("SP", {})
        
        # Get aliases from constants (e.g., NPC_ → {NPC_, RACE})
        sig_set = CATEGORY_FILTER_ALIASES.get(signature, {signature})
        
        filtered = []
        for name in mod_names:
            entry = rich_sp.get(name)
            if not entry:
                continue
                
            entry_sigs = getattr(entry, 'signatures', set())
            # Check if any of the target signatures (including aliases) exist
            if entry_sigs.intersection(sig_set):
                filtered.append(name)
        
        return filtered

    def _get_mod_categories(self, mod_name: str) -> List[str]:
        """Return all record categories present in a mod from its rich entry.
        Blessed plugins return all SP categories (they contain everything)."""
        rich_sp = self.controller._rich_silos.get("SP", {})
        entry = rich_sp.get(mod_name)
        
        # Blessed plugins: return all possible categories (base game has everything)
        if mod_name in BLESSED_CORE_FILES or getattr(entry, 'is_blessed', False):  # BLESSED_CORE_FILES already imported
            return list(SKYPATCHER_SUPPORTED_RECORD_TYPES)  # Already imported at top
        
        if not entry:
            return ["NPC_", "WEAP", "ARMO"]  # Fallback
        
        # Direct read from entry.signatures
        categories = [
            sig for sig in getattr(entry, 'signatures', set())
            if sig in SKYPATCHER_SUPPORTED_RECORD_TYPES  # Already imported
        ]
        
        return sorted(categories) if categories else ["NPC_"]

    def _restrict_category_combo(self, panel, valid_categories: List[str]) -> None:
        """Rebuild category combo with only valid entries for selected mod."""
        panel.category_combo.blockSignals(True)
        panel.category_combo.clear()
        panel.category_combo.addItem("")
        panel.category_combo.addItems(valid_categories)
        panel.category_combo.blockSignals(False)

    def _suggest_source_for_target(self, panel, target_mod: str) -> None:
        """Auto-populate source with next mod in load order (LMW logic)."""
        # Find target in LO, pick next active plugin as source suggestion
        lo_map = self.pm.get_load_order_map()
        target_idx = None
        
        # Find index of target
        for idx, name in lo_map.items():
            if name == target_mod:
                target_idx = idx
                break
                
        if target_idx is not None:
            # Look ahead for next unlocked plugin
            for i in range(target_idx + 1, max(lo_map.keys()) + 1):
                if i in lo_map:
                    candidate = lo_map[i]
                    audit = self.pm.get_audit_cache()
                    if audit.get(candidate, {}).get('status') != 'locked':
                        panel.source_mod_combo.setCurrentText(candidate)
                        break

    def _update_sentence_builder(self, panel, category: str) -> None:
        """Rebuild Filter/Action/Value combos based on category."""
        # Block signals to prevent cascade
        panel.filter_combo.blockSignals(True)
        panel.action_combo.blockSignals(True)
        panel.value_combo.blockSignals(True)
        
        panel.filter_combo.clear()
        panel.action_combo.clear()
        panel.value_combo.clear()
        
        if not category:
            panel.filter_combo.setEnabled(False)
            panel.action_combo.setEnabled(False)
            panel.value_combo.setEnabled(False)
        else:
            # Filter = keywords for this category (from keywords.ini)
            filter_type = SIGNATURE_TO_FILTER.get(category.upper(), "")
            actions = FILTER_TO_ACTIONS.get(filter_type, [])
            
            panel.action_combo.addItem("")
            panel.action_combo.addItems(actions)
            panel.action_combo.setEnabled(True)
            
            # Box 1: Terrigenesis (INI keys — the thing that triggers the change)
            mist = self.controller._filter_cache.get(category.upper(), [])
            panel.filter_combo.addItem("")
            panel.filter_combo.addItems(mist)
            
            # Box 3: Inhuman Abilities (Keyword payloads — the actual power applied)
            powers = self.controller._keyword_cache.get(category.upper(), [])
            panel.value_combo.addItem("")
            panel.value_combo.addItems(powers)
            
        panel.filter_combo.blockSignals(False)
        panel.action_combo.blockSignals(False)
        panel.value_combo.blockSignals(False)
        
        # Force view rebuild
        for combo in (panel.filter_combo, panel.action_combo, panel.value_combo):
            if combo.count() > 0:
                combo.showPopup()
                combo.hidePopup()

    def _get_keywords_for_category(self, category: str) -> List[str]:
        """Pull keywords from controller's cache (loaded from keyword/keywords.ini)."""
        if not category:
            return []
            
        cat_upper = category.upper()
        
        # Single source: keywords.ini cache
        if hasattr(self.controller, '_keyword_cache') and cat_upper in self.controller._keyword_cache:
            return self.controller._keyword_cache[cat_upper]
        
        # Last resort: category name itself so SB isn't dead
        return [cat_upper] if cat_upper else []

    def populate_sp_category(self, sp_panel) -> None:
        """Seed the Cat combo once on panel birth."""
        # Already seeded? Don't nuke it — restore may have already set a value
        if sp_panel.category_combo.count() > 1:
            return
            
        sp_panel.category_combo.blockSignals(True)
        sp_panel.category_combo.clear()
        sp_panel.category_combo.addItem("")
        
        cats = sorted(SKYPATCHER_SUPPORTED_RECORD_TYPES)
        sp_panel.category_combo.addItems(cats)
        sp_panel.category_combo.blockSignals(False)
        
        # wake it up so Qt builds the view
        if sp_panel.category_combo.count() > 0:
            sp_panel.category_combo.showPopup()
            sp_panel.category_combo.hidePopup()
        self.log_debug(f"Category combo seeded: {len(cats)} types")

    def wake_sp_combos(self, sp_panel) -> None:
        """Kick T&S awake – Qt needs the popup hack to build the view."""
        for combo in (sp_panel.target_mod_combo, sp_panel.source_mod_combo):
            if combo.count() > 0 and combo.isEnabled():
                current = combo.currentText()
                combo.setEditText(current)  # force lineEdit sync
                combo.showPopup()
                combo.hidePopup()
        self.log_info("T&S combos woke up")

    def apply_cat_change(self, sp_panel, category: str) -> None:
        """Cat picked – filter T&S, refresh sentence builder."""
        if not category:
            return
            
        # tell controller to filter the mod combos
        self.populate_sp_combos(category)
        
        # wake the sentence builder for this cat
        self._update_sentence_builder(sp_panel, category)
        
        self.log_debug(f"Category change applied: {category}")

    def apply_filter_change(self, sp_panel, filter_target: str) -> None:
        """Filter picked — look up the exact keyword payload for this key."""
        if not filter_target:
            return
            
        cat_upper = sp_panel._category.upper()
        
        sp_panel.value_combo.blockSignals(True)
        sp_panel.value_combo.clear()
        sp_panel.value_combo.addItem("")
        # Lookup in keyword cache (loaded from keywords.ini)
        powers = self._get_keywords_for_category(cat_upper)
        sp_panel.value_combo.addItems(powers)
        sp_panel.value_combo.blockSignals(False)
        sp_panel.value_combo.setEnabled(True)
        
        self.log_info(f"Filter '{filter_target}' selected — Terrigenesis started")

    # ============================================================
    # BOS SECTION – M2M combos & asset waterfall
    # ============================================================
    
    def populate_bos_combos(self, category_filter: str = "") -> None:
        """Fill BOS target/source — bulletproof against dict vs object entries."""
        if not self.controller.bos_panel:
            return
        
        # ---- Helper: dict or dataclass, we don't care ----
        def _get(entry, key, default=None):
            if isinstance(entry, dict):
                return entry.get(key, default)
            return getattr(entry, key, default)
        
        all_silos = self.controller._rich_silos
        rich_plugins: dict = {}
        rich_folders: dict = {}
        
        # ---- STRUCTURE DETECTION ----
        if isinstance(all_silos, dict):
            # Try nested first
            for nested_key in ("BOS", "BOS_MOD", "BOS_MODS"):
                if nested_key in all_silos and isinstance(all_silos[nested_key], dict):
                    if nested_key in ("BOS", "BOS_MODS"):
                        rich_plugins = all_silos[nested_key]
                    else:
                        rich_folders = all_silos[nested_key]
            
            # Flat fallback: keys are "BOS:Name" or "BOS_MOD:Name"
            if not rich_plugins and not rich_folders:
                for key, entry in all_silos.items():
                    silo_type = _get(entry, 'silo_type', '')
                    name = key.split(':', 1)[-1] if ':' in key else key
                    if silo_type == 'BOS':
                        rich_plugins[name] = entry
                    elif silo_type in ('BOS_MOD', 'BOS_MODS'):
                        rich_folders[name] = entry
        
        self.log_debug(f"BOS silos: plugins={len(rich_plugins)}, folders={len(rich_folders)}")
        
        # ---- MERGE BOTH WELLS ----
        merged = []
        for name, entry in rich_plugins.items():
            merged.append((name, _get(entry, 'lo_index', 9999), entry, True))
        
        seen = {name for name, _, _, _ in merged}
        for name, entry in rich_folders.items():
            if name not in seen:
                merged.append((name, _get(entry, 'lo_index', 9999), entry, False))
                seen.add(name)
        
        merged.sort(key=lambda x: x[1])
        
        # ---- CATEGORY FILTER ----
        if category_filter and category_filter.strip() and category_filter != "All":
            cat_key = category_filter.strip()
            check_sigs = BOS_CATEGORIES.get(cat_key, {cat_key.upper()})
            filtered = []
            for name, idx, entry, is_plugin in merged:
                if _get(entry, 'is_blessed', False) or name in BLESSED_CORE_FILES:
                    filtered.append((name, idx, entry, is_plugin))
                    continue
                sigs = _get(entry, 'signatures', set())
                # Handle string signatures from INI parser
                if isinstance(sigs, str):
                    sigs = set(sigs.split(', ')) if sigs else set()
                if sigs.intersection(check_sigs):
                    filtered.append((name, idx, entry, is_plugin))
            if cat_key.upper() in {"BODY", "SKIN", "ASSET_SKIN", "ASSET_BODY"} and not filtered:
                filtered = list(merged)
            merged = filtered
        
        bos_names = [name for name, _, _, _ in merged]
        
        # ---- POPULATE ----
        panel = self.controller.bos_panel
        old_target = panel.target_combo.currentText()
        old_source = panel.source_combo.currentText()
        
        panel.target_combo.blockSignals(True)
        panel.source_combo.blockSignals(True)
        
        for combo in (panel.target_combo, panel.source_combo):
            combo.clear()
            combo.addItem("")
            combo.addItems(bos_names)
        
        if old_target in bos_names:
            panel.target_combo.setCurrentText(old_target)
        if old_source in bos_names:
            panel.source_combo.setCurrentText(old_source)
            
        panel.target_combo.blockSignals(False)
        panel.source_combo.blockSignals(False)        
        
    def m2m_category_changed(self, category: str) -> None:
        """
        M2M category switched – apply BodySlide Output priority if skin/body.
        Waterfall: BodySlide Output > Overwrite (ignored) > Base Mod
        """
        panel = self.controller.bos_panel
        if not panel:
            return
            
        # If skin/body category, prioritize asset output folders
        if category.upper() in {"SKIN", "BODY", "ASSET_BODY", "ASSET_SKIN"}:
            self._prioritize_asset_outputs(panel, category)
        else:
            # Standard population for other categories
            self.populate_bos_combos(category)

    def _prioritize_asset_outputs(self, panel, category: str) -> None:
        """Reorder combos to put BodySlide Output at top if present."""
        # Get current list
        current_items = [panel.target_combo.itemText(i) 
                        for i in range(panel.target_combo.count())]
        
        # Find BodySlide outputs (whitelist check)
        asset_outputs = [name for name in current_items 
                        if "BODYSLIDE" in name.upper() or "BSOUTPUT" in name.upper()]
        
        if asset_outputs:
            # Reorder: Asset outputs first, then rest
            others = [n for n in current_items if n not in asset_outputs and n != ""]
            new_order = [""] + asset_outputs + others
            
            panel.target_combo.blockSignals(True)
            panel.target_combo.clear()
            panel.target_combo.addItems(new_order)
            panel.target_combo.blockSignals(False)
            
            self.log_info(f"Waterfall: Prioritized {len(asset_outputs)} asset outputs")

    def launch_fid_scan(self, processor, plugin_files, mod_names, category, 
                       abort_flag, progress_callback):
        """
        Kicks FID scanner into ThreadPool.
        Completion signals back via fid_scan_complete.
        """
        def on_complete(results):
            self.fid_scan_complete.emit(results)
            
        scanner = FidScanner(
            processor, plugin_files, mod_names, category,
            abort_flag, progress_callback, 
            list(self.pm.get_audit_cache().keys()),
            on_complete
        )
        self._pool.start(scanner)
        self.log_info("FID scanner dispatched to thread pool")

    # ============================================================
    # SHARED UTILS
    # ============================================================
    
    def refresh_all_silos(self) -> None:
        """Trigger PM refresh – convenience method for controller."""
        self.pm.refresh_silos()
        
    def get_mod_status(self, plugin_name: str, silo: str) -> Any:
        """Proxy to BL for UI display info."""
        return self.bl.get_mod_status(plugin_name, silo)
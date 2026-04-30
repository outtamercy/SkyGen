# ui/auditor_dialog.py

from typing import List, Optional, Dict
from pathlib import Path

from PyQt6.QtWidgets import ( # type: ignore
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QSplitter, QWidget,
    QAbstractItemView, QFrame, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer # type: ignore
from PyQt6.QtGui import QColor, QBrush, QFont # type: ignore

from ..utils.logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_DEBUG
from ..utils.bl_mgr import  ModStatus
from ..utils.pm_mgr import ProfileManager, ManifestEntry, SiloedSnoop
from ..utils.sigsnoop import PluginDNA  
from ..core.constants import (
    COLOR_LOCKED, COLOR_USER_BL, COLOR_HIDDEN, COLOR_STARRED,
    COLOR_PARTIAL, COLOR_ACTIVE, ICON_BLESSED, ICON_LOCKED, ICON_USER_BL,
    ICON_STARRED, ICON_PARTIAL, ICON_NONE, AUDITOR_BG_COLOR,
    BLACKLIST_AUTHORS, BLACKLIST_KEYWORDS, BLESSED_CORE_FILES, 
    OFFICIAL_CC_PREFIX, GLOBAL_IGNORE_PLUGINS, AE_CORE_FILES, BASE_GAME_PLUGINS
)


class ModListItem(QListWidgetItem):
    def __init__(self, status: ModStatus, plugin_name: str, dna: Optional[PluginDNA], parent=None):
        # Line 1: Icon + Mod Name
        display_text = f"{status.icon} {status.display_name}"
        
        # Line 2: Smart Reason String based on DNA
        reason_text = self._build_reason_text(status, dna)
        if reason_text:
            display_text += f"\n\n{reason_text}"
        
        super().__init__(display_text, parent)
        
        self.plugin_name = plugin_name
        self.reason = status.reason
        self.current_rule = "default"
        self.dna = dna  # Store DNA for later reference
        
        # Lock framework/blessed/core - no checkbox
        if status.reason in ("framework", "blessed", "core_game_file"):
            self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            font = self.font()
            font.setBold(True)
            self.setFont(font)
        else:
            self.setFlags(self.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_blacklisted = (status.reason == "user_blacklist")
            self.setCheckState(Qt.CheckState.Checked if is_blacklisted else Qt.CheckState.Unchecked)
        
        # Color handling
        from PyQt6.QtWidgets import QApplication # type: ignore
        palette = parent.palette() if parent else QApplication.instance().palette()
        if status.color == COLOR_ACTIVE:
            text_color = palette.color(palette.ColorRole.Text)
        else:
            text_color = QColor(status.color)
        self.setForeground(QBrush(text_color))
    
    def _build_reason_text(self, status: ModStatus, dna: Optional[PluginDNA]) -> str:
        """Build human-readable reason from DNA scents and ratios."""
        if not dna:
            return f"Status: {status.reason}"
        
        parts = []
        
        # Blessed shield overrides everything
        if status.reason == "blessed":
            return "🛡️ Base Game / Official Content"
        
        # Scent-based reasons (highest priority)
        if dna.folder_scents:
            if "BOS_FRAMEWORK" in dna.folder_scents:
                return "🔄 Base Object Swapper Framework"
            if "SKYPATCHER_FRAMEWORK" in dna.folder_scents:
                return "🔄 SkyPatcher Framework"
            if "SKSE" in dna.folder_scents:
                parts.append("SKSE Dependent")
        
        # Ratio-based reason
        if dna.logic_to_content_ratio > 0.8 and len(dna.signatures) > 50:
            return f"⚠️ Script-Heavy ({dna.logic_to_content_ratio:.0%} logic)"
        elif dna.logic_to_content_ratio > 0.5:
            parts.append(f"Mixed Content ({dna.logic_to_content_ratio:.0%} logic)")
        
        # Show author if available
        if dna.author and dna.author != "Unknown":
            parts.append(f"Author: {dna.author}")
        
        if parts:
            return " | ".join(parts)
        return f"Status: {status.reason}"

class BlacklistAuditorDialog(QDialog, LoggingMixin):
    """
    ONLY popup in SkyGen system.
    3-state mod manager: Default / Whitelist (⭐) / Blacklist (⚠)
    """
    
    rules_changed = pyqtSignal()  # Notify controller to refresh UI
    
    def __init__(self, siloed_snoop: SiloedSnoop, 
                 all_plugins: List[str],
                 silo: str = "SP",  # Add silo parameter
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        LoggingMixin.__init__(self)
        
        self.siloed_snoop = siloed_snoop
        self.all_plugins = all_plugins
        self.current_silo = silo  # Use passed silo instead of default "SP"
        
        self.setWindowTitle(f"Blacklist Auditor - {silo}")
        self.setMinimumSize(600, 500)
        # Theme inheritance: remove forced dark background
        # Native theme handles background via palette
        #         
        self._build_ui()
        self._populate_list()

        
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Silo:"))
        
        self.silo_combo = QComboBox()
        self.silo_combo.addItems(["Global", "SkyPatcher", "BOS"])  # Global first
        self.silo_combo.currentTextChanged.connect(self._on_silo_changed)
        header.addWidget(self.silo_combo)
        
        header.addStretch()
        
        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search mods...")
        self.search_input.textChanged.connect(self._on_search_changed)
        header.addWidget(self.search_input)
        
        layout.addLayout(header)

        # Blessed tier filters - three checkboxes for AE, CC, Base
        blessed_layout = QHBoxLayout()
        
        self.chk_ae = QCheckBox("AE-Safe")
        self.chk_ae.setToolTip("BLESSED-AE: Anniversary Edition Core Content")
        self.chk_ae.setChecked(True)
        self.chk_ae.stateChanged.connect(self._on_blessed_filter_changed)
        
        self.chk_cc = QCheckBox("CC-Curated")
        self.chk_cc.setToolTip("BLESSED-CC: Creation Club Content")
        self.chk_cc.setChecked(True)
        self.chk_cc.stateChanged.connect(self._on_blessed_filter_changed)
        
        self.chk_base = QCheckBox("Base-Sacred")
        self.chk_base.setToolTip("BLESSED-BASE: Base Game Plugins")
        self.chk_base.setChecked(True)
        self.chk_base.stateChanged.connect(self._on_blessed_filter_changed)
        
        blessed_layout.addWidget(self.chk_ae)
        blessed_layout.addWidget(self.chk_cc)
        blessed_layout.addWidget(self.chk_base)
        blessed_layout.addStretch()
        
        layout.addLayout(blessed_layout)
        
        # Single panel: Mod list only (full width)
        self.mod_list = QListWidget()
        self.mod_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.mod_list.setFrameShape(QFrame.Shape.NoFrame)
        self.mod_list.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.mod_list.itemChanged.connect(self._on_item_changed)  # Checkbox toggle
        
        layout.addWidget(self.mod_list)
        
        # Legend
        legend = QLabel("🔒 Framework (Locked)  | ☑ Checked = Blacklisted  |  ☐ Unchecked = Active")
        legend.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(legend)
        
        # Close button (atomic save)
        close_btn = QPushButton("Save & Close")
        close_btn.clicked.connect(self._on_save_close)
        layout.addWidget(close_btn)
        
        self._pending_rules: Dict[str, Optional[str]] = {}  # Atomic save buffer

    def _on_item_changed(self, item: ModListItem):
        """Buffer changes, don't save yet."""
        if item.reason == "framework":
            return  # Ignore framework locks
        
        new_rule = "blacklist" if item.checkState() == Qt.CheckState.Checked else "default"
        self._pending_rules[item.plugin_name] = new_rule if new_rule != "default" else None
    
    def _on_save_close(self):
        """Atomic save all pending rules."""
        for plugin_name, rule in self._pending_rules.items():
            self.siloed_snoop.set_user_rule(plugin_name, rule)
        
        # BL owns its own file — make it write now
        bl = self.siloed_snoop.blacklist_mgr
        if bl and hasattr(bl, '_save_user_rules'):
            bl._save_user_rules()
        elif bl and hasattr(bl, '_save_auto_blacklist'):
            # Fallback: some BL implementations share one save method
            bl._save_auto_blacklist()
        
        self.rules_changed.emit()
        self.accept()
        
    def _populate_list(self) -> None:
            """Chunked population - JR opens instantly, fills as you watch."""
            self.mod_list.clear()
            self.mod_list.setUpdatesEnabled(False)
            
            # Queue the herd
            self._pending_plugins = sorted(self.all_plugins)
            self._populate_chunk()

    def _populate_chunk(self, chunk_size: int = 50) -> None:
            """Process 50 at a time, let Qt breathe between bites."""
            if not self._pending_plugins:
                    # Herds all in the corral
                    self.mod_list.setUpdatesEnabled(True)
                    self.mod_list.viewport().update()
                    bl_count = len(self.siloed_snoop.blacklist_mgr._auto_blacklist)
                    self.log_info(f"AUDIT: Population complete, {self.mod_list.count()} items, {bl_count} auto-blacklist")
                    return
            
            chunk = self._pending_plugins[:chunk_size]
            self._pending_plugins = self._pending_plugins[chunk_size:]
            
            audit = self.siloed_snoop.profile_mgr.get_audit_cache()
            user_rules = self.siloed_snoop.blacklist_mgr._user_rules
            
            silo_map = {"Global": "GLOBAL", "SkyPatcher": "SP", "BOS": "BOS"}
            current_silo = silo_map.get(self.silo_combo.currentText(), "SP")
            
            for plugin_name in chunk:
                    # CRITICAL: Initialize display_name so it always exists
                    display_name = plugin_name
                    
                    audit_entry = audit.get(plugin_name, {})
                    # Check if Frankie hard-locked this (GLOBAL + high confidence = hands off)
                    layer = audit_entry.get('layer', '')
                    confidence = audit_entry.get('lc_confidence', 'low')
                    is_hard_locked = (layer == 'global' and confidence == 'high')
                    
                    # Silo filter logic
                    plugin_silos = audit_entry.get('silos', [])
                    if current_silo == "GLOBAL":
                            if "GLOBAL" not in plugin_silos:
                                    continue
                    elif current_silo not in plugin_silos:
                            continue
                    
                    entry = self.siloed_snoop.profile_mgr.get_plugin_data(plugin_name)
                    plugin_lower = plugin_name.lower()
                    
                    # === GLOBAL IGNORE SHIELD (Tier -1) ===
                    if plugin_name in GLOBAL_IGNORE_PLUGINS:
                            icon = ICON_LOCKED
                            color = COLOR_LOCKED
                            reason = "framework"
                            dna = None
                    
                    # Tier 0a: AE Core (Anniversary Edition)
                    elif plugin_name in AE_CORE_FILES:
                            if not self.chk_ae.isChecked():
                                    continue
                            icon = f"{ICON_BLESSED}{ICON_LOCKED}"
                            color = COLOR_LOCKED
                            reason = "blessed"
                            display_name = f"{plugin_name} [BLESSED-AE]"
                    
                    # Tier 0b: Base Game
                    elif (entry and getattr(entry, 'is_blessed', False)) or (plugin_lower in [p.lower() for p in BASE_GAME_PLUGINS]):
                            if not self.chk_base.isChecked():
                                    continue
                            icon = f"{ICON_BLESSED}{ICON_LOCKED}"
                            color = COLOR_LOCKED
                            reason = "blessed"
                            display_name = f"{plugin_name} [BLESSED-BASE]"
                    
                    # Tier 1: CC mods — visible but LC-classified, not hard-locked
                    if plugin_lower.startswith(OFFICIAL_CC_PREFIX):
                        if not self.chk_cc.isChecked():
                            continue
                        if entry and entry.is_blessed:
                            icon = f"{ICON_BLESSED}{ICON_LOCKED}"
                            color = COLOR_LOCKED
                            reason = "blessed"
                            display_name = f"{plugin_name} [BLESSED-CC]"
                        elif entry and entry.is_framework:
                            icon = ICON_LOCKED
                            color = COLOR_LOCKED
                            reason = "framework"
                            display_name = f"{plugin_name} [CC-Framework]"
                        else:
                            icon = ICON_NONE
                            color = COLOR_ACTIVE
                            reason = "active"
                            display_name = f"{plugin_name} [CC-Content]"
                    
                    # Tier 2: Auto-blacklist
                    elif self.siloed_snoop.blacklist_mgr._auto_blacklist.get(plugin_lower):
                            icon = ICON_LOCKED
                            color = COLOR_LOCKED
                            reason = "framework"
                            display_name = f"{plugin_name} [Framework]"
                    
                    # Tier 3: User rules
                    elif plugin_lower in user_rules:
                            rule = user_rules[plugin_lower]
                            if rule == "whitelist":
                                    icon = ICON_STARRED
                                    color = COLOR_STARRED
                                    reason = "user_whitelist"
                                    display_name = f"{plugin_name} [Starred]"
                            else:
                                    icon = ICON_USER_BL
                                    color = COLOR_USER_BL
                                    reason = "user_blacklist"
                                    display_name = f"{plugin_name} [Blacklisted]"
                    
                    # Default: Active
                    else:
                            icon = ICON_NONE
                            color = COLOR_ACTIVE
                            reason = "active"
                            # display_name keeps the plugin_name default
                    
                    # Create status (your existing)
                    from ..utils.bl_mgr import ModStatus
                    status = ModStatus(
                            visible=(reason == "active"),
                            display_name=display_name,
                            icon=icon,
                            color=color,
                            reason=reason
                    )
                    
                    # NEW - Build DNA from the entry data we already have
                    dna = None
                    if entry:
                            from ..utils.sigsnoop import PluginDNA
                            # entry can be ManifestEntry object or dict from cache
                            if isinstance(entry, dict):
                                    dna = PluginDNA(
                                            signatures=set(entry.get('signatures', [])),
                                            author=entry.get('author', 'Unknown'),
                                            masters=entry.get('masters', []),
                                            is_esm=False,
                                            is_esl=False,
                                            file_size=entry.get('size', 0),
                                            mtime=entry.get('mtime', 0.0),
                                            object_signatures=set(entry.get('object_signatures', [])),
                                            logic_signatures=set(entry.get('logic_signatures', [])),
                                            logic_to_content_ratio=entry.get('logic_to_content_ratio', 0.0),
                                            folder_scents=set(entry.get('folder_scents', []))
                                    )
                            else:
                                    # ManifestEntry dataclass - use attribute access
                                    dna = PluginDNA(
                                            signatures=getattr(entry, 'signatures', set()),
                                            author=getattr(entry, 'author', 'Unknown'),
                                            masters=getattr(entry, 'masters', []),
                                            is_esm=False,
                                            is_esl=False,
                                            file_size=getattr(entry, 'size', 0),
                                            mtime=getattr(entry, 'mtime', 0.0),
                                            object_signatures=getattr(entry, 'object_signatures', set()),
                                            logic_signatures=getattr(entry, 'logic_signatures', set()),
                                            logic_to_content_ratio=getattr(entry, 'logic_to_content_ratio', 0.0),
                                            folder_scents=getattr(entry, 'folder_scents', set())
                                    )
                    
                    # Then pass it to the list item (your existing line)
                    item = ModListItem(status, plugin_name, dna, self.mod_list)
                    # Hard-lock = disabled checkbox, soft-lock = user can still toggle
                    if is_hard_locked:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                        item.setToolTip("Hard-locked: GLOBAL framework plugin (high confidence)")
                        # Gray it out so users know it's untouchable
                        font = item.font()
                        font.setItalic(True)
                        item.setFont(font)
                    item.current_rule = self._detect_current_rule(status)
                    self.mod_list.addItem(item)
            
            # Next bite in 10ms - keeps UI breathing
            QTimer.singleShot(10, self._populate_chunk)       

    def _detect_current_rule(self, status: ModStatus) -> str:
        """Detect current user rule from status."""
        if status.reason == "user_whitelist":
            return "whitelist"
        elif status.reason == "user_blacklist":
            return "blacklist"
        return "default"
    
    def _on_silo_changed(self, text: str) -> None:
        """Switch between SP/BOS view."""
        self._populate_list()

    def _on_blessed_filter_changed(self, state):
        """Repopulate when blessed tier filters change."""
        self._populate_list()
    
    def _on_search_changed(self, text: str) -> None:
        """Filter list by search text."""
        search_term = text.lower().strip()
        
        for i in range(self.mod_list.count()):
            item = self.mod_list.item(i)
            if isinstance(item, ModListItem):
                matches = search_term in item.plugin_name.lower()
                item.setHidden(not matches)
        
        # Force Qt6 to repaint the list after filter changes
        self.mod_list.viewport().update()
    
    def _on_mod_selected(self, item: ModListItem) -> None:
        """Update details panel."""
        self.details_label.setText(item.plugin_name)
        
        reason_map = {
            "framework": "Framework/Utility (Auto-hidden by author/signature)",
            "user_whitelist": "User Whitelisted (Forced visible)",
            "user_blacklist": "User Blacklisted (Forced hidden)",
            "vanilla": "Base Game Plugin (Auto-hidden)",
            "pre_patched": "Pre-Patched Config Exists",
            "no_signatures": "No records for current category",
            "kill_switch": "Blacklist Kill Switch Active",
            "active": "Active (Visible in UI)",
        }
        
        reason_text = reason_map.get(item.reason, f"Status: {item.reason}")
        self.reason_label.setText(reason_text)
        
        # Update button states
        self.default_btn.setEnabled(item.current_rule != "default")
        self.whitelist_btn.setEnabled(item.current_rule != "whitelist")
        self.blacklist_btn.setEnabled(item.current_rule != "blacklist")
    
    def _on_mod_double_clicked(self, item: ModListItem) -> None:
        """Cycle through states on double-click."""
        cycle = {"default": "whitelist", "whitelist": "blacklist", "blacklist": "default"}
        new_rule = cycle.get(item.current_rule, "default")
        self._apply_rule(item, new_rule)
    
    def _set_rule(self, rule: str) -> None:
        """Apply rule to selected mod."""
        current_item = self.mod_list.currentItem()
        if not current_item:
            return
        
        self._apply_rule(current_item, rule)
    
    def _apply_rule(self, item: ModListItem, rule: str) -> None:
        """Apply and persist user rule."""
        # Convert display rule to persistence format
        persistence_rule = None if rule == "default" else rule
        
        # Update backend
        self.siloed_snoop.set_user_rule(item.plugin_name, persistence_rule)
        
        # Update item
        item.current_rule = rule
        
        # Refresh display
        status = self.siloed_snoop.get_mod_display_info(item.plugin_name, self.current_silo)
        new_item = ModListItem(status, item.plugin_name, None, self.mod_list)
        new_item.current_rule = rule
        
        # Replace in list
        row = self.mod_list.row(item)
        self.mod_list.takeItem(row)
        self.mod_list.insertItem(row, new_item)
        self.mod_list.setCurrentItem(new_item)
        
        self._on_mod_selected(new_item)
        self.rules_changed.emit()
        
        self.log_info(f"User rule set: {item.plugin_name} = {rule}", MO2_LOG_INFO)
    
    def accept(self) -> None:
        """Close dialog."""
        self.log_debug("Auditor closed")
        super().accept()
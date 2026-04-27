# sp_panel.py – KISS edition: panel owns the shared Generate button
# <-- FIX: Add dedicated local generate button, remove shared button logic
# <-- FIX: Replace placeholder generation with real patch_gen call via controller
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import ( # type: ignore
    QWidget, QVBoxLayout, QGroupBox, QHBoxLayout, QLabel,
    QCheckBox, QComboBox, QLineEdit, QPushButton, QSizePolicy, QFileDialog, QSplitter, QRadioButton,
    QMessageBox, QApplication, QCompleter
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QThread, QObject, QTimer # type: ignore

from ..utils.logger import LoggingMixin, SkyGenLogger, MO2_LOG_INFO, MO2_LOG_DEBUG, MO2_LOG_WARNING, MO2_LOG_ERROR
from .panel_base import PanelGeometryMixin
from ..src.worker import GenerationWorker
from ..core.constants import ( SKYPATCHER_SUPPORTED_RECORD_TYPES, FILTER_TO_ACTIONS, 
                              SIGNATURE_TO_FILTER, BLESSED_CORE_FILES
                              
                              )


class SkyPatcherPanel(QWidget, LoggingMixin, PanelGeometryMixin):
    MIN_WIDTH  = 600
    SP_SIGNATURES = set(SKYPATCHER_SUPPORTED_RECORD_TYPES)

    _requestBrowse = pyqtSignal(object)

    def __init__(self, main_dialog: QWidget) -> None:
        QWidget.__init__(self)
        LoggingMixin.__init__(self)
        PanelGeometryMixin.__init__(self, main_dialog)
        self._category: str = ""
        self._implicit_filter_type: str = ""  
        self._build_ui()
        self._wire_internal()

        # <-- FIX: Worker thread management
        self._worker_thread: Optional[QThread] = None
        self._generation_running = False

    # ---------- UI build ----------
    def _build_ui(self) -> None:
        self.setLayout(QVBoxLayout())
        grp = QGroupBox("SkyPatcher INI Settings")
        lay = QVBoxLayout(grp)

        self.gen_modlist_cb    = QCheckBox("Generate Entire ModList")
        self.gen_all_cats_cb   = QCheckBox("Generate All Supported Categories")
        lay.addWidget(self.gen_modlist_cb)
        lay.addWidget(self.gen_all_cats_cb)

        self.target_mod_combo = QComboBox()
        self.target_mod_combo.setEditable(True)
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.setEditable(True)
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)

        for lbl, w in (
            ("Target Plugin:", self.target_mod_combo),
            ("Source Plugin (Required):", self.source_mod_combo),
            ("Category (Record Type):", self.category_combo),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(lbl))
            row.addWidget(w)
            lay.addLayout(row)
        # Sentence Builder: Filter | Action | Value
        sentence_layout = QHBoxLayout()
        
        # Box 1: Filter (Keywords)
        sentence_layout.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.setToolTip("keywords Vanilla keywords - defines WHAT to target")
        self.filter_combo.setEnabled(False)
        sentence_layout.addWidget(self.filter_combo)
        
        # Box 2: Action (Verbs)
        sentence_layout.addWidget(QLabel("Action:"))
        self.action_combo = QComboBox()
        self.action_combo.setToolTip("SkyPatcher verb: addKeywords, setRace, changeWeight...")
        self.action_combo.setEnabled(False)
        sentence_layout.addWidget(self.action_combo)
        
        # Box 3: Value (FormIDs)
        sentence_layout.addWidget(QLabel("Value:"))
        self.value_combo = QComboBox()
        self.value_combo.setToolTip("FormID to apply: 00123456 (hex, no 0x prefix)")
        self.value_combo.setEditable(True)
        self.value_combo.setInsertPolicy(QComboBox.InsertPolicy.InsertAtBottom)
        self.value_combo.setPlaceholderText("FormID (e.g., 00012345)")
        self.value_combo.setEnabled(False)
        self.value_combo.setMaximumWidth(200)
        
        # Completer for keywords + manual FormIDs
        self._value_completer = QCompleter([], self.value_combo)
        self._value_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._value_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.value_combo.setCompleter(self._value_completer)
        sentence_layout.addWidget(self.value_combo)
        
        # LMW Toggle (Winners Only)
        self.lmw_toggle = QCheckBox("Winners Only")
        self.lmw_toggle.setChecked(True)
        self.lmw_toggle.setToolTip("Only show Last-Mod-Wins records")
        sentence_layout.addWidget(self.lmw_toggle)
        
        # Give SB combos breathing room - Filter and Action expand, Value stays reasonable
        sentence_layout.setStretchFactor(self.filter_combo, 3)
        sentence_layout.setStretchFactor(self.action_combo, 3)
        sentence_layout.setStretchFactor(self.value_combo, 2)
        sentence_layout.setStretchFactor(self.lmw_toggle, 0)  # Toggle stays fixed
        
        # Ensure combos expand horizontally
        self.filter_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.value_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addLayout(sentence_layout)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Cache Mode:"))
        self.speed_mode_rb = QRadioButton("Speed")
        self.space_saver_mode_rb = QRadioButton("Space Saver")
        self.speed_mode_rb.setChecked(True)
        mode_layout.addWidget(self.speed_mode_rb)
        mode_layout.addWidget(self.space_saver_mode_rb)
        mode_layout.addStretch()
        lay.addLayout(mode_layout)

        self.output_folder_input = QLineEdit()
        self.output_folder_input.setReadOnly(True)
        self.output_folder_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.output_folder_input.setMaximumWidth(400)
        self.output_folder_browse_btn = QPushButton("Browse")
        self.output_folder_browse_btn.setToolTip(
            "Where the Skypatcher INI gets written. Same folder for every generation."
        )
        self.output_folder_browse_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        row = QHBoxLayout()
        row.addWidget(QLabel("Output Folder:"))
        row.addWidget(self.output_folder_input)
        row.addWidget(self.output_folder_browse_btn)
        lay.addLayout(row)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("spInvisibleSplitter")
        self.splitter.addWidget(grp)
        self.layout().addWidget(self.splitter)
        self.settings_vertical_splitter = self.splitter

        self.stop_button = QPushButton("⏹ Stop Gen")
        self.stop_button.setEnabled(False)
        
        # <-- FIX: Add dedicated local generate button
        self.generate_btn = QPushButton("Generate Patch")
        self.generate_btn.clicked.connect(self._on_generate_clicked)

    # ---------- Event wiring ----------
    def _wire_internal(self) -> None:
        self._requestBrowse.connect(self._on_browse_answer)
        self.output_folder_browse_btn.clicked.connect(
            lambda: self._requestBrowse.emit(self.output_folder_input)
        )
        
        # Cat change -> OR handles the heavy lifting
        self.category_combo.currentTextChanged.connect(self._on_category_changed)
        self.category_combo.currentTextChanged.connect(self._delegate_cat_to_or)
        
        self.gen_modlist_cb.toggled.connect(
            lambda c: c and self.gen_all_cats_cb.setChecked(False))
        self.gen_all_cats_cb.toggled.connect(
            lambda c: c and self.gen_modlist_cb.setChecked(False))
        self.gen_modlist_cb.toggled.connect(self._update_combo_states)
        self.gen_all_cats_cb.toggled.connect(self._update_combo_states)
        self.speed_mode_rb.toggled.connect(self._on_cache_mode_changed)
        self.space_saver_mode_rb.toggled.connect(self._on_cache_mode_changed)
        self.stop_button.clicked.connect(lambda: self._md.controller.on_stop_clicked())
        
        # Sentence Builder child wiring
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.action_combo.currentTextChanged.connect(self._on_action_changed)
        self._update_combo_states()
        # Notify controller when anything changes so button updates
        self.target_mod_combo.currentTextChanged.connect(self._trigger_button_refresh)
        self.source_mod_combo.currentTextChanged.connect(self._trigger_button_refresh)
        self.category_combo.currentTextChanged.connect(self._trigger_button_refresh)
        self.gen_modlist_cb.toggled.connect(self._trigger_button_refresh)
        self.gen_all_cats_cb.toggled.connect(self._trigger_button_refresh)
        self.output_folder_input.textChanged.connect(self._trigger_button_refresh)

    def _trigger_button_refresh(self) -> None:
        """Tell controller to recheck button state."""
        if hasattr(self._md, 'controller') and self._md.controller:
            self._md.controller._update_generate_button()

    def _update_combo_states(self) -> None:
        modlist = self.gen_modlist_cb.isChecked()
        allcats = self.gen_all_cats_cb.isChecked()
        single_mode = not modlist and not allcats
        
        # Target/Source/Category mirror pattern
        self.target_mod_combo.setEnabled(single_mode)
        self.source_mod_combo.setEnabled(single_mode)
        self.category_combo.setEnabled(not allcats)
        
        # SB trio follows same disable pattern (LMW stays free for bulk)
        self.filter_combo.setEnabled(single_mode)
        self.action_combo.setEnabled(single_mode)
        has_both = bool(self.filter_combo.currentText()) and bool(self.action_combo.currentText())
        self.value_combo.setEnabled(single_mode and has_both)

        # Force button recalc whenever mode switches — checkbox state matters too
        self._trigger_button_refresh()        

        # Sync the flag downstream (only if controller is actually wired up)
        if hasattr(self._md, 'controller') and self._md.controller:
            self._md.controller.patch_settings.sp_use_sentence_builder = single_mode
            self.log_debug(f"SB gate: {'armed' if single_mode else 'bypassed'}")

    def _on_browse_answer(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            clean = str(Path(path))
            line_edit.setText(clean)
            if hasattr(self._md, 'controller') and self._md.controller:
                self._md.controller.patch_settings.skypatcher_output_folder = clean

    def _on_category_changed(self, text: str) -> None:
        if not text.strip():
            return
        self.log_debug(f"_on_category_changed fired  text='{text}'")
        self._category = text

    def _delegate_cat_to_or(self, category: str) -> None:
        """Hand off to One Ring – let the brain coordinate."""
        if not category or not hasattr(self._md, 'controller'):
            return
        # Don't wake OR if Frankie hasn't finished his coffee
        if not hasattr(self._md.controller, 'one_ring') or not self._md.controller.one_ring:
            return
        self._md.controller.one_ring.apply_cat_change(self, category)
    
    def _update_sentence_builder(self, category: str) -> None:
        """Triple Clear Fix: Box 1=Actions, Box 2= keyword Targets, Box 3=FormIDs."""
        # Block all signals first to prevent cross-contamination
        self.action_combo.blockSignals(True)
        self.filter_combo.blockSignals(True)
        self.value_combo.blockSignals(True)
        
        # Clear everything at once
        self.action_combo.clear()
        self.filter_combo.clear()
        self.value_combo.clear()
        
        if not category:
            self.filter_combo.setEnabled(False)
            self.action_combo.setEnabled(False)
            self.value_combo.setEnabled(False)
            self._implicit_filter_type = ""
            self.action_combo.blockSignals(False)
            self.filter_combo.blockSignals(False)
            self.value_combo.blockSignals(False)
            return
        
        cat_upper = category.upper()
        filter_type = SIGNATURE_TO_FILTER.get(cat_upper, "")
        self._implicit_filter_type = filter_type
        
        # ---- BOX 1: Actions (Verbs only) ----
        actions = FILTER_TO_ACTIONS.get(filter_type, [])
        self.action_combo.addItem("") 
        if actions:
            self.action_combo.addItems(actions)
            self.action_combo.setEnabled(True)
        else:
            self.action_combo.setEnabled(False)
        
        # ---- Filter Targets (INI keys from keywords.ini) ----
        targets = []
        if hasattr(self._md, 'controller') and self._md.controller:
            targets = self._md.controller.get_keywords_for_category(category)
        
        self.filter_combo.addItem("")
        self.filter_combo.addItems(targets)
        self.filter_combo.setEnabled(True)
        self.filter_combo.setEditable(True)
        
        # ---- BOX 3: Values (from keywords.ini) ----
        values = []
        if hasattr(self._md, 'controller') and self._md.controller:
            kw_cache = getattr(self._md.controller, '_keyword_cache', {})
            if cat_upper in kw_cache:
                for kw in kw_cache[cat_upper]:
                    values.append(kw)
        
        self.value_combo.addItem("")
        self.value_combo.addItems(values)
        self.value_combo.setEnabled(False) 
        self.value_combo.setEditable(True)

        # Unblock all signals at the end
        self.action_combo.blockSignals(False)
        self.filter_combo.blockSignals(False)
        self.value_combo.blockSignals(False)
        
        QTimer.singleShot(0, self._force_combo_refresh)

    def _force_combo_refresh(self) -> None:
        """Targeted realization for Mayhem's Madness - avoids flicker."""
        if not self.value_combo.isVisible() or not self.value_combo.isEnabled():
            return
        
        # Only kick the popup to force view rebuild
        self.value_combo.showPopup()
        self.value_combo.hidePopup()
        
        # Ensure LineEdit is focused and placeholder persists
        le = self.value_combo.lineEdit()
        if le and not self.value_combo.currentText():
            le.setCursorPosition(0)

    def _realize_value_combo(self) -> None:
        """Force view realization only when combo is active and visible."""
        if self.value_combo.isEnabled() and self.value_combo.isVisible():
            self.value_combo.showPopup()
            self.value_combo.hidePopup()
   
    def _update_action_combo(self, filter_type: str) -> None:
        """Update Action combo based on Filter selection."""
        self.action_combo.clear()
        actions = FILTER_TO_ACTIONS.get(filter_type, [])
        if actions:
            self.action_combo.addItems(actions)
            self.action_combo.setEnabled(True)
        else:
            self.action_combo.setEnabled(False)
    
    def _on_filter_changed(self, filter_target: str) -> None:
        if not filter_target:
            return
        controller = getattr(self._md, 'controller', None)
        if not controller or not hasattr(controller, 'one_ring') or not controller.one_ring:
            return
        has_action = bool(self.action_combo.currentText())
        self.value_combo.setEnabled(bool(filter_target) and has_action)
        controller.one_ring.apply_filter_change(self, filter_target)
    
    def _on_action_changed(self, action_type: str) -> None:
        """Box 1 selection enables Box 3 if Box 2 has selection."""
        has_action = bool(action_type)
        has_target = bool(self.filter_combo.currentText())
        
        # Enable value combo only when both target and action present
        self.value_combo.setEnabled(has_action and has_target)
        
        if has_action:
            self.log_debug(f"ACTION_SELECTED: {action_type}")

    def _on_activity_changed(self, active: bool) -> None:
        """Enable/disable buttons - both stay visible."""
        self.log_debug(f"🔥 ACTIVITY SIGNAL: active={active}")
        
        self.stop_button.setEnabled(active)
        self.generate_btn.setEnabled(not active)
        
        self.log_debug(f"Buttons: stop(enabled={self.stop_button.isEnabled()}), generate(enabled={self.generate_btn.isEnabled()})")

    def _on_cache_mode_changed(self) -> None:
        """Update cache mode in config when radio changes."""
        mode = "speed" if self.speed_mode_rb.isChecked() else "space_saver"
        if hasattr(self._md, 'controller'):
            self._md.controller.patch_settings.cache_mode = mode
            self.log_debug(f"Cache mode changed to: {mode}")
    
    def showEvent(self, event):
        super().showEvent(event)
        
        self.generate_btn.setVisible(True)
        
        # Wire up activity indicator if not done yet
        if not getattr(self, '_signal_connected', False):
            if hasattr(self._md, 'controller') and self._md.controller:
                self._md.controller.activity_indicator_toggle.connect(
                    self._on_activity_changed, Qt.ConnectionType.QueuedConnection
                )
                self._signal_connected = True

        # RESTORE: Sentence Builder from config
        if hasattr(self._md, 'controller'):
            ps = self._md.controller.patch_settings
            if ps.sp_filter_type:
                self.filter_combo.setCurrentText(ps.sp_filter_type)
            if ps.sp_action_type:
                self.action_combo.setCurrentText(ps.sp_action_type)
            if ps.sp_value_formid:
                self.value_combo.setCurrentText(ps.sp_value_formid)
            self.lmw_toggle.setChecked(getattr(ps, 'sp_lmw_winners_only', True))
        
        # RESTORE: Category triggers SB rebuild via _on_category_changed
        # which delegates to OR for sentence builder population
        
        # Wake up value combo if empty
        if self.value_combo.count() == 0:
            self.value_combo.addItem("")
            
        # Let Qt finish rendering then wake T&S combos
        QTimer.singleShot(50, self._wakeup_main_combos)

    def _wakeup_main_combos(self):
        """Force Qt view creation on all combos regardless of current enable state."""
        if not hasattr(self._md, 'controller') or not self._md.controller:
            return
        if not hasattr(self._md.controller, 'one_ring') or not self._md.controller.one_ring:
            return
        
        # Qt6 lazy view: temporarily enable to force internal QListView creation
        for combo in (self.target_mod_combo, self.source_mod_combo, self.category_combo):
            if combo.count() > 0:
                was_enabled = combo.isEnabled()
                combo.setEnabled(True)
                combo.setEditText(combo.currentText())
                combo.showPopup()
                combo.hidePopup()
                combo.setEnabled(was_enabled)
        
        self._md.controller.one_ring.wake_sp_combos(self)

    def get_implicit_filter_type(self) -> str:
        """Return the derived filterBy* type for INI generation."""
        return self._implicit_filter_type

    # ---------- Properties ----------
    @property
    def target_mod(self) -> str:
        return self.target_mod_combo.currentText()

    @target_mod.setter
    def target_mod(self, v: str) -> None:
        self.target_mod_combo.setCurrentText(v)

    @property
    def source_mod(self) -> str:
        return self.source_mod_combo.currentText()

    @source_mod.setter
    def source_mod(self, v: str) -> None:
        self.source_mod_combo.setCurrentText(v)

    @property
    def category(self) -> str:
        return self._category

    @category.setter
    def category(self, v: str) -> None:
        self.category_combo.setCurrentText(v)
        self._category = v.strip()

    @property
    def generate_all(self) -> bool:
        return self.gen_all_cats_cb.isChecked()

    @generate_all.setter
    def generate_all(self, v: bool) -> None:
        self.gen_all_cats_cb.setChecked(v)

    @property
    def output_folder_path(self) -> str:
        return self.output_folder_input.text()

    @output_folder_path.setter
    def output_folder_path(self, v: str) -> None:
        self.output_folder_input.setText(v)

    @property
    def generate_modlist(self) -> bool:
        return self.gen_modlist_cb.isChecked()

    @generate_modlist.setter
    def generate_modlist(self, v: bool) -> None:
        self.gen_modlist_cb.setChecked(v)

    @property
    def cache_mode(self) -> str:
        return "space_saver" if self.space_saver_mode_rb.isChecked() else "speed"

    @cache_mode.setter
    def cache_mode(self, v: str) -> None:
        if v == "space_saver":
            self.space_saver_mode_rb.setChecked(True)
        else:
            self.speed_mode_rb.setChecked(True)

    @property
    def inner_splitter(self):
        """Expose splitter under standard name for geometry save."""
        return self.settings_vertical_splitter

    @property
    def sp_value_formid(self) -> str:
        return self.value_combo.currentText() if self.value_combo.currentText() else ""

    @sp_value_formid.setter
    def sp_value_formid(self, v: str) -> None:
        self.value_combo.setCurrentText(v)

# ============================================
    # ---------- Generation ----------
# ============================================

    def _on_generate_clicked(self) -> None:
        """Delegate to controller – panel is UI-only per pattern."""
        if not self.output_folder_path:
            self.log_error("SP: No output folder selected – generation blocked")
            return
        
        self.log_info("SP: Delegating to controller.on_generate_sp_patch()")
        self._md.controller.on_generate_sp_patch()


    def _on_sp_worker_finished(self, success: bool, msg: str) -> None:
        """Handle SP generation completion."""
        self._generation_running = False
        self._md.controller.activity_indicator_toggle.emit(False)

        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait()
            self._worker_thread = None

        level = MO2_LOG_INFO if success else MO2_LOG_ERROR
        self.log_line(f"SP-GENERATION: {msg}", level)

    def _on_sp_worker_error(self, error: str) -> None:
        """Handle SP generation error."""
        self._generation_running = False
        self._md.controller.activity_indicator_toggle.emit(False)

        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait()
            self._worker_thread = None

        self.log_error(f"SP-GENERATION ERROR: {error}")

    # ---------- Readiness ----------
    def is_ready(self) -> bool:
        has_output   = bool(self.output_folder_input.text().strip())
        has_profile  = self._md.organizer_wrapper.profile_dir.exists()
        needs_category = not (self.gen_all_cats_cb.isChecked() or self.gen_modlist_cb.isChecked())
        has_category = bool(self.category_combo.currentText().strip()) if needs_category else True
        needs_target = not self.gen_modlist_cb.isChecked()
        has_target = bool(self.target_mod_combo.currentText().strip()) if needs_target else True
        ready = has_target and has_category and has_output and has_profile
        self.log_debug(f"[SP] is_ready: target={has_target} (needs={needs_target}), cat={has_category} (needs={needs_category}), out={has_output}, profile={has_profile} → {ready}")
        return ready
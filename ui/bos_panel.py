from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QGridLayout, QLabel, QCheckBox,
    QComboBox, QLineEdit, QPushButton, QHBoxLayout, QToolButton,
    QSizePolicy, QFileDialog, QSplitter, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView, QCompleter
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QFileSystemWatcher
from ..utils.logger import LoggingMixin, MO2_LOG_INFO, MO2_LOG_WARNING, MO2_LOG_ERROR, MO2_LOG_DEBUG
from .panel_base import PanelGeometryMixin
from ..utils.bos_processor import BosProcessor
from ..utils.bos_writer import BosWriter
import json
from ..core.constants import (BOS_CATEGORIES, BOS_SIGNATURES, BOS_RECORD_MAP,
                              BLESSED_CORE_FILES)
from ..extractors.reader import PluginReader

class BosPanel(QWidget, LoggingMixin, PanelGeometryMixin):
    """BOS panel – QTableWidget with UserRole mod name storage."""
    MIN_WIDTH = 940

    _requestBrowse = pyqtSignal(object)
    rows_changed = pyqtSignal(list)

    def __init__(self, main_dialog: QWidget) -> None:
        QWidget.__init__(self)
        LoggingMixin.__init__(self)
        PanelGeometryMixin.__init__(self, main_dialog)
        self._md = main_dialog
        self._json_path = Path(__file__).resolve().parent.parent / "data" / "BOS_FormIDs.json"
        self._watcher = QFileSystemWatcher(self)
        self._abort_scan = False
        self._is_loading = False
        self._extracted_mode = False

        # Source of truth: data list
        self._fid_data: List[Dict[str, Any]] = []

        self._processor = BosProcessor(main_dialog.organizer_wrapper)

        self._build_ui()
        self._wire_internal()
        self._reload_json_if_present()
        self._refresh_scan_btn()
        self.setAcceptDrops(True)

    # ---------- Data-centric row management ----------

    def _add_fid_row(self, data: str | dict, checked: bool = True, 
                     read_only: bool = True, mod_name: str = "",
                     is_asset_swap: bool = False) -> None:
        """Slap a new row in - handles both old string calls and new dicts."""
        # Normalize input (strings are legacy, dicts are current)
        if isinstance(data, str):
            data = {"source_fid": data, "source_mod": mod_name}
        else:
            data = dict(data)
        
        # Grab what we can from the dict, fallback to blanks
        target_mod = data.get('target_mod', data.get('target_plugin', self.target_mod or ""))
        target_fid = data.get('target_fid', data.get('target_form_id', ""))
        
        # Source fields come from scan results as form_id/plugin_name usually
        source_mod = (
            data.get('source_mod') or 
            data.get('plugin_name') or 
            data.get('sourceName') or 
            mod_name or 
            ""
        )
        source_fid = (
            data.get('source_fid') or 
            data.get('source_form_id') or
            data.get('form_id') or 
            data.get('formId') or 
            ""
        )
        
        # Stash clean copy for later export
        clean_data = {
            'target_mod': target_mod,
            'target_fid': target_fid,
            'source_mod': source_mod,
            'source_fid': source_fid,
            'is_asset_swap': is_asset_swap
        }
        
        # Make the row
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._fid_data.append(clean_data)

        # Col 0: Checkbox
        chk_item = QTableWidgetItem()
        chk_item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        
        # Col 1: Target plugin name
        tgt_mod_item = QTableWidgetItem(target_mod)
        tgt_mod_item.setData(Qt.ItemDataRole.UserRole, target_mod)
        if read_only:
            tgt_mod_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # Col 2: Target FormID
        tgt_fid_item = QTableWidgetItem(target_fid)
        if read_only:
            tgt_fid_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # Col 3: Source plugin name  
        src_mod_item = QTableWidgetItem(source_mod)
        src_mod_item.setData(Qt.ItemDataRole.UserRole, source_mod)
        if read_only:
            src_mod_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # Col 4: Source FormID
        src_fid_item = QTableWidgetItem(source_fid)
        if read_only:
            src_fid_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # Slam 'em in - NOW MATCHES HEADERS
        self._table.setItem(row, 0, chk_item)
        self._table.setItem(row, 1, src_mod_item)   # Was 3
        self._table.setItem(row, 2, src_fid_item)   # Was 4
        self._table.setItem(row, 3, tgt_mod_item)   # Was 1
        self._table.setItem(row, 4, tgt_fid_item)   # Was 2

    def _clear_fid_rows(self) -> None:
        """Clear all data and table rows."""
        self._fid_data.clear()
        self._table.setRowCount(0)

    def _get_fid_data(self) -> list[dict]:
        """Grab checked rows, pull live data from the table."""
        checked_records = []
        for row in range(self._table.rowCount()):
            chk_item = self._table.item(row, 0)
            if not (chk_item and chk_item.checkState() == Qt.CheckState.Checked):
                continue
                
            if row >= len(self._fid_data):
                continue
            
            # Table layout: 1=Source Plugin, 2=Source FID, 3=Target Plugin, 4=Target FID
            src_mod_item = self._table.item(row, 1)
            src_fid_item = self._table.item(row, 2)
            tgt_mod_item = self._table.item(row, 3)
            tgt_fid_item = self._table.item(row, 4)
            
            source_fid = src_fid_item.text() if src_fid_item else ""
            
            d = {
                'target_mod': tgt_mod_item.data(Qt.ItemDataRole.UserRole) or tgt_mod_item.text() if tgt_mod_item else "",
                'target_fid': tgt_fid_item.text() if tgt_fid_item else "",
                'source_mod': src_mod_item.data(Qt.ItemDataRole.UserRole) or src_mod_item.text() if src_mod_item else "",
                'source_fid': source_fid,
                'form_id': source_fid,  # Generation expects this key
                'is_asset_swap': self._fid_data[row].get('is_asset_swap', False),
            }
            checked_records.append(d)
        return checked_records

    def _get_fid_count(self) -> int:
        return len(self._fid_data)

    def _get_fid_checked_count(self) -> int:
        """Count checked rows by reading table state."""
        count = 0
        for i in range(min(len(self._fid_data), self._table.rowCount())):
            chk_item = self._table.item(i, 0)
            if chk_item and chk_item.checkState() == Qt.CheckState.Checked:
                count += 1
        return count

    # ---------- Life-cycle ----------

    def showEvent(self, event):
        super().showEvent(event)
        self.generate_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        
        # DEFERRED: Wake combos after Qt finishes render
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self._wakeup_combos)
        
    def _wakeup_combos(self):
        """Editable combo realization fix."""
        for combo in (self.target_combo, self.source_combo, self._m2m_cat_combo):
            if combo.count() > 0:
                was_enabled = combo.isEnabled()
                combo.setEnabled(True)
                combo.setEditText(combo.currentText())
                combo.showPopup()
                combo.hidePopup()
                combo.setEnabled(was_enabled)

    # ---------- UI Build ----------
    def _build_ui(self) -> None:
        grp = QGroupBox("BOS INI Settings")
        lay = QGridLayout(grp)

        # Mod Selection
        mod_group = QGroupBox("Mod Selection")
        mod_vbox = QVBoxLayout(mod_group)

        # M2M Controls - Row 1: Target | Source (side by side)
        mods_row = QHBoxLayout()
        
        # Target Mod (left)
        target_hbox = QHBoxLayout()
        target_label = QLabel("Target Mod:")
        target_label.setToolTip("The mod whose objects will be REPLACED (victim)")
        target_hbox.addWidget(target_label)
        
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setMinimumWidth(200)
        self.target_combo.setToolTip(
            "Victim mod: Its objects get swapped out. "
            "Example: JK's Dragonsreach (the furniture you want to replace)"
        )
        target_hbox.addWidget(self.target_combo)
        mods_row.addLayout(target_hbox)
        
        # Source Mod (right)
        source_hbox = QHBoxLayout()
        source_label = QLabel("Source Mod:")
        source_label.setToolTip("The mod providing the NEW objects (replacement)")
        source_hbox.addWidget(source_label)
        
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.setMinimumWidth(200)
        self.source_combo.setToolTip(
            "Replacement mod: Its objects will appear in-game instead. "
            "Example: EEKs Dragonsreach (the new furniture)"
        )
        source_hbox.addWidget(self.source_combo)
        mods_row.addLayout(source_hbox)
        
        mod_vbox.addLayout(mods_row)
        
        # M2M Controls - Row 2: Category | Chance (raw signatures)
        cat_row = QHBoxLayout()
        
        self._m2m_cat_combo = QComboBox()
        self._m2m_cat_combo.setMinimumWidth(100)
        self._m2m_cat_combo.setToolTip(
            "Category filter for M2M swap. "
            "Body=armor/race, Skin=armor/race+assets, Furniture=statics, etc."
        )
        # was dumping raw 4-letter sigs into the combo, filter looked up by friendly name — total mismatch
        self._m2m_cat_combo.addItem("All")
        self._m2m_cat_combo.addItems(sorted(BOS_CATEGORIES.keys()))
        
        cat_row.addWidget(QLabel("Category:"))
        cat_row.addWidget(self._m2m_cat_combo)
        cat_row.addSpacing(20)
        
        from PyQt6.QtWidgets import QSpinBox
        self._m2m_chance_spin = QSpinBox()
        self._m2m_chance_spin.setRange(0, 100)
        self._m2m_chance_spin.setValue(100)
        self._m2m_chance_spin.setSuffix("%")
        self._m2m_chance_spin.setFixedWidth(70)
        self._m2m_chance_spin.setToolTip(
            "0-100% chance each object gets swapped. "
            "100% = replace everything, 50% = coin flip per object"
        )
        cat_row.addWidget(QLabel("Swap Chance:"))
        cat_row.addWidget(self._m2m_chance_spin)
        cat_row.addStretch(1)
        
        mod_vbox.addLayout(cat_row)

        lay.addWidget(mod_group, 0, 0, 1, 6)

        # Output Folder
        output_layout = QHBoxLayout()
        output_layout.setSpacing(4)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_folder_input = QLineEdit()
        self.output_folder_input.setReadOnly(True)
        self.output_folder_browse_btn = QPushButton("Browse")
        self.output_folder_browse_btn.setToolTip(
            "Where the BOS INI gets written. Same folder for every generation."
        )
        output_layout.addWidget(QLabel("Output Folder:"))
        output_layout.addWidget(self.output_folder_input)
        output_layout.addWidget(self.output_folder_browse_btn)
        lay.addLayout(output_layout, 2, 0, 1, 6)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(grp)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setMinimumWidth(460)
        self.splitter.setHandleWidth(6)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)

        # FormID Overrides - QTableWidget (from original)
        fid_grp = QGroupBox("FormID Overrides")
        fid_vbox = QVBoxLayout(fid_grp)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([200, 600])

        # XYZ Row
        xyz_hbox = QHBoxLayout()
        xyz_hbox.setSpacing(4)
        xyz_hbox.setContentsMargins(0, 0, 0, 0)
        self.x_edit = QLineEdit("0.0")
        self.y_edit = QLineEdit("0.0")
        self.z_edit = QLineEdit("0.0")
        for lbl_text, edit in (("X:", self.x_edit), ("Y:", self.y_edit), ("Z:", self.z_edit)):
            lbl = QLabel(lbl_text)
            lbl.setMinimumWidth(10)
            edit.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
            edit.setMaximumWidth(60)
            xyz_hbox.addWidget(lbl)
            xyz_hbox.addWidget(edit)
        self.x_edit.setToolTip("X offset — shifts swapped object position east/west")
        self.y_edit.setToolTip("Y offset — shifts swapped object position north/south")
        self.z_edit.setToolTip("Z offset — shifts swapped object position up/down")
        xyz_hbox.addStretch(1)
        fid_vbox.addLayout(xyz_hbox)

        # QTableWidget - 5 columns: check, source plugin, source fid, target plugin, target fid
        self._table = QTableWidget(fid_grp)  # <-- parent here if not set elsewhere
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["✔️", "Source Plugin", "Source FID", "Target Plugin", "Target FID"])
        
        # Column widths - lock 'em so headers don't get smooshed when resizing, we'll handle it with stretch and size policies
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)      # Check: fixed tight
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)      # Source Plugin: fixed 200px min
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)      # Source FID: fixed 100px
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)      # Target Plugin: fixed 200px min  
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)      # Target FID: fixed 100px
        
        # Layout: Fixed widths for FIDs, Stretch for Plugin Names to kill dead space
        header = self._table.horizontalHeader()
        
        # 1. Lock narrow columns (Checkbox and FIDs)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 40)
        
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 110)
        
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 110)

        # 2. Stretch the Plugin Names to fill the right side of the window
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # 3. Table and Group constraints
        self._table.setMinimumWidth(800)
        self._table.verticalHeader().setDefaultSectionSize(24)
        fid_vbox.addWidget(self._table, stretch=1)

        fid_grp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        fid_grp.setMinimumHeight(80)
        self.splitter.addWidget(fid_grp)
        self.splitter.setStretchFactor(1, 1)

        # Button Bar
        btn_bar = QHBoxLayout()
        self.stop_btn = QToolButton()
        self.stop_btn.setText("✕")
        self.stop_btn.setFixedSize(22, 22)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._request_stop)

        self._clear_rows_btn = QPushButton("Clear List")
        self._clear_rows_btn.clicked.connect(self._on_clear_clicked)

        self._add_btn = QPushButton("+ Line")
        self._add_btn.clicked.connect(self._on_add_clicked)

        self._scan_btn = QPushButton("FormIDs Scan")
        self._scan_btn.clicked.connect(self._scan_formids)

        self._export_btn = QPushButton("Export FormIDs")
        self._export_btn.clicked.connect(self._export_formid_list)

        self._cat_combo = QComboBox()
        self._cat_combo.addItems(["All", "Tree", "Furniture", "Container", "Light", "Misc"])

        self._mode_lbl = QLabel("Manual mode")
        self.scan_all_cb = QCheckBox("Scan all mods")
        self._row_count_lbl = QLabel("0/0")
        self.generate_btn = QPushButton("Generate Patch")
        self.generate_btn.clicked.connect(self._on_generate_clicked)

        btn_bar.addWidget(self.stop_btn)
       
        # Scan chance spinbox (Section 2 control)
        from PyQt6.QtWidgets import QSpinBox
        self._scan_chance_spin = QSpinBox()
        self._scan_chance_spin.setRange(0, 100)
        self._scan_chance_spin.setValue(100)
        self._scan_chance_spin.setSuffix("%")
        self._scan_chance_spin.setFixedWidth(70)
        btn_bar.addWidget(QLabel("Chance:"))
        btn_bar.addWidget(self._scan_chance_spin)
        btn_bar.addSpacing(10)
        
        btn_bar.addWidget(self._clear_rows_btn)
        btn_bar.addWidget(self._add_btn)
        btn_bar.addWidget(self._scan_btn)
        btn_bar.addWidget(self.scan_all_cb)
        btn_bar.addWidget(self._export_btn)
        btn_bar.addWidget(QLabel("Filter:"))
        btn_bar.addWidget(self._cat_combo)
        btn_bar.addWidget(self._mode_lbl)
        btn_bar.addWidget(self._row_count_lbl)
        btn_bar.addStretch()
        btn_bar.addWidget(self.generate_btn)
        fid_vbox.addLayout(btn_bar)
        # Mode switcher — this is the one that confuses everyone
        self.scan_all_cb.setToolTip(
            "Checked = FID Scan mode (harvest FormIDs from load order). "
            "Unchecked = M2M mode (swap one mod's objects into another)."
        )
        
        self._scan_btn.setToolTip(
            "Harvest FormIDs from all active plugins into the table. "
            "Use the Filter dropdown to narrow by category."
        )
        
        # Only tooltip if the spinbox actually exists — SNM guard
        if hasattr(self, '_scan_chance_spin'):
            self._scan_chance_spin.setToolTip(
                "FID Scan only — 0-100% chance each harvested FormID gets checked for export."
            )
        
        self._clear_rows_btn.setToolTip("Nukes the entire table. No undo.")
        self._add_btn.setToolTip("Add a blank row for manual FormID entry.")
        self._export_btn.setToolTip("Dump checked rows to JSON for round-trip editing.")
        
        self._cat_combo.setToolTip(
            "FID Scan filter — only harvest records matching this category."
        )
        
        self.generate_btn.setToolTip(
            "M2M mode: writes a swap INI using Target→Source pairing. "
            "FID mode: writes an INI from checked table rows."
        ) 
        # Root Layout
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.splitter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ---------- Event Wiring ----------
    def _wire_internal(self) -> None:
        # Browse button: emit signal (connected to handler below)
        self.output_folder_browse_btn.clicked.connect(
            lambda: self._requestBrowse.emit(self.output_folder_input)
        )
        # Connect the signal to actual handler
        self._requestBrowse.connect(self._on_browse_answer)
        
        # SP-STYLE: Category is master - populates Target/Source when changed
        self._m2m_cat_combo.currentTextChanged.connect(self._on_m2m_category_changed)
        
        # Target/Source changes just persist, don't control category
        self.target_combo.currentTextChanged.connect(self._on_target_changed)
        self.source_combo.currentTextChanged.connect(self._on_source_changed)
        
        # Scan mode toggle
        self.scan_all_cb.toggled.connect(self._on_scan_mode_changed)
        
        # Generate button state updates
        self.target_combo.currentTextChanged.connect(self._update_button_state)
        self.source_combo.currentTextChanged.connect(self._update_button_state)
        self._m2m_cat_combo.currentTextChanged.connect(self._update_button_state)
        self.scan_all_cb.toggled.connect(self._update_button_state)

        # Table checkbox toggles need to refresh generate button too
        # otherwise checking a row doesn't unlock the gen button in scan mode
        self._table.itemChanged.connect(self._update_button_state)

        # JSON watcher
        if self._json_path.exists():
            self._watcher.addPath(str(self._json_path))
            self._watcher.fileChanged.connect(self._on_json_changed)
        
        # Initial state sync
        self._on_scan_mode_changed()

    def _on_m2m_category_changed(self, text: str = "") -> None:
        """
        M2M category switched - let the One Ring repopulate.
        """
        if self._is_loading:
            return
            
        has_category = bool(text.strip()) and text != "All"
        
        # Enable combos if we have a category (even "All" counts)
        self.target_combo.setEnabled(has_category or text == "All")
        self.source_combo.setEnabled(has_category or text == "All")
        
        # DIRECT to One Ring - no controller forwarding
        if hasattr(self._md, 'controller') and self._md.controller:
            if hasattr(self._md.controller, 'one_ring') and self._md.controller.one_ring:
                cat_filter = "" if text == "All" else text.strip()
                self._md.controller.one_ring.populate_bos_combos(cat_filter)
                self._md.controller.patch_settings.m2m_category = text.strip()

    def _update_button_state(self) -> None:
        self._refresh_scan_btn()
        self.generate_btn.setEnabled(self.is_ready())

    def _on_target_changed(self, text: str = "") -> None:
        """Persist target mod - category is master now."""
        if self._is_loading:
            return
        self._refresh_scan_btn()
        if hasattr(self._md, 'controller') and self._md.controller:
            self._md.controller.patch_settings.bos_target_mod = text.strip()

    def _on_source_changed(self, text: str = "") -> None:
        """Persist target mod - category is master now."""
        if self._is_loading:
            return
        self._refresh_scan_btn()
        if hasattr(self._md, 'controller') and self._md.controller:
            self._md.controller.patch_settings.bos_source_mod = text.strip()

    def _refresh_scan_btn(self) -> None:
        """Enable scan button only if we have a target or scan-all is checked."""
        ok = self.scan_all_cb.isChecked() or bool(self.target_combo.currentText().strip())
        self._scan_btn.setEnabled(ok)

    def _on_scan_mode_changed(self) -> None:
        scan_all = self.scan_all_cb.isChecked()
        
        # Section 2 (FID/Scan)
        self._cat_combo.setEnabled(scan_all)
        self._scan_chance_spin.setEnabled(scan_all)
        self._table.setEnabled(scan_all)
        self._scan_btn.setEnabled(scan_all)
        self._clear_rows_btn.setEnabled(scan_all)
        self._export_btn.setEnabled(scan_all)
        self._add_btn.setEnabled(scan_all)
        
        # Section 1 (M2M): Category always visible, controls target/source
        self._m2m_cat_combo.setEnabled(not scan_all)
        self._m2m_chance_spin.setEnabled(not scan_all)
        
        # Target/Source follow category selection
        has_category = bool(self._m2m_cat_combo.currentText().strip())
        self.target_combo.setEnabled(not scan_all and has_category)
        self.source_combo.setEnabled(not scan_all and has_category)
        
        self._refresh_scan_btn()
        self._update_button_state()

    def _request_stop(self) -> None:
        self._abort_scan = True
        self.stop_btn.setEnabled(False)
        self.log_info("Scan stop requested")

    def _on_browse_answer(self, line_edit: QLineEdit) -> None:
        """Handle browse button click for output folder selection."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            line_edit.text() or str(self._md.organizer_wrapper.organizer.basePath())
        )
        if folder:
            line_edit.setText(folder)
            if hasattr(self._md, 'controller') and self._md.controller:
                self._md.controller.patch_settings.bos_output_folder = folder

    def _on_clear_clicked(self) -> None:
        """Clear all rows."""
        self._clear_fid_rows()
        self._update_button_state()
        self._emit_rows()
        self._mode_lbl.setText("Manual mode (0 rows)")

    def _on_add_clicked(self) -> None:
        """Add empty row for manual entry."""
        self._add_fid_row({}, checked=True, read_only=False)  # empty dict, not strings
        self._update_button_state()
        self._emit_rows()

    # Properties
    # ------------------------------------------------------------------
    @property
    def target_mod(self) -> str:
        raw = self.target_combo.currentText().strip()
        # Strip MO2 prefixes
        if raw.startswith('+') or raw.startswith('-'):
            raw = raw[1:].strip()
        return raw

    @target_mod.setter
    def target_mod(self, v: str) -> None:
        self._set_combo_persist(self.target_combo, v)

    @property
    def source_mod(self) -> str:
        raw = self.source_combo.currentText().strip()
        if raw.startswith('+') or raw.startswith('-'):
            raw = raw[1:].strip()
        return raw

    @source_mod.setter
    def source_mod(self, v: str) -> None:
        self._set_combo_persist(self.source_combo, v)

    @property
    def output_folder(self) -> str:
        return self.output_folder_input.text().strip()

    @output_folder.setter
    def output_folder(self, v: str) -> None:
        self.output_folder_input.setText(v)

    @property
    def xyz(self) -> tuple[str, str, str]:
        return (self.x_edit.text().strip(), self.y_edit.text().strip(), self.z_edit.text().strip())

    @xyz.setter
    def xyz(self, xyz: tuple[str, str, str]) -> None:
        self.x_edit.setText(xyz[0])
        self.y_edit.setText(xyz[1])
        self.z_edit.setText(xyz[2])

    @property
    def inner_splitter(self):
        return self.splitter

    def supply_formids(self, formids: List[str]) -> None:
        self._clear_fid_rows()
        for fid in formids:
            self._add_fid_row(fid, "", "")

    @property
    def form_id_overrides(self) -> List[str]:
        """Read checked FormIDs from table."""
        result = []
        for i, row_data in enumerate(self._fid_data):
            if i < self._table.rowCount():
                chk_item = self._table.item(i, 0)
                if chk_item and chk_item.checkState() == Qt.CheckState.Checked:
                    if row_data.get("form_id"):
                        result.append(row_data["form_id"])
        return result

    @property
    def enable_scan(self) -> bool:
        return self.scan_all_cb.isChecked()

    @enable_scan.setter
    def enable_scan(self, v: bool) -> None:
        self.scan_all_cb.setChecked(v)

    @property
    def bos_inner_splitter(self):
        return self.splitter

#   ---------- Validation ----------

    def is_ready(self) -> bool:
        if not self.output_folder.strip():
            return False
        
        # SCAN/FID MODE: Need checked FormIDs
        if self.scan_all_cb.isChecked():
            return self._get_fid_checked_count() > 0
        
        # M2M MODE: Target + Source + Category all required
        has_target = bool(self.target_mod.strip())
        has_source = bool(self.source_mod.strip())
        has_category = bool(self._m2m_cat_combo.currentText().strip())  # "All" is valid, empty is not
        
        return has_target and has_source and has_category



    # ---------- Plugin Collection ----------
    def _collect_plugin_files(self) -> tuple[list[Path], list[str], dict[int, str]]:
        """Grab plugins for FID scan — drinks from BOS_MODS silo like OR does."""
        plugin_files: list[Path] = []
        mod_names: list[str] = []
        lo_map: dict[int, str] = {}
        
        def _get(entry, key, default=None):
            try:
                return entry.get(key, default)
            except (AttributeError, TypeError):
                pass
            try:
                return getattr(entry, key, default)
            except AttributeError:
                return default
        
        if self.scan_all_cb.isChecked():
            all_silos = self._md.controller._rich_silos
            
            # Controller stores BOS data under BOS_MODS — keys are mod folders, not plugins
            rich_bos = {}
            if all_silos and hasattr(all_silos, 'get'):
                rich_bos = (
                    all_silos.get("BOS_MODS") or 
                    all_silos.get("BOS_MOD") or 
                    all_silos.get("BOS", {})
                )
            
            if not rich_bos:
                self.log_debug("FID: BOS_MODS silo empty — nothing to scan")
                return [], [], {}
            
            # Need the real load order to know where each plugin actually sits
            full_lo_map = self._md.controller.profile_manager.get_load_order_map()
            
            # Collect (lo_index, plugin_path, mod_folder) tuples
            collected: list[tuple[int, Path, str]] = []
            
            for mod_folder, entry in rich_bos.items():
                # Explode mod folder into actual plugin files
                plugins = self._find_plugins_in_mod(mod_folder)
                
                for plugin_path in plugins:
                    plugin_name = plugin_path.name
                    # Hunt down this plugin's real seat in the load order
                    for idx, lo_plugin in full_lo_map.items():
                        if lo_plugin.lower() == plugin_name.lower():
                            # Cast to int — INI likes handing us strings
                            collected.append((int(idx), plugin_path, mod_folder))
                            break
            
            # Sort by load order so scan hits them in sequence
            collected.sort(key=lambda x: x[0])
            
            for idx, path, folder in collected:
                lo_map[idx] = path.name
                plugin_files.append(path)
                mod_names.append(folder)
                
        else:
            # Single mod scan — same as before
            target = self.target_mod
            if not target:
                return [], [], {}
            plugins = self._find_plugins_in_mod(target)
            plugin_files.extend(plugins)
            mod_names.extend([target] * len(plugins))
            
            # Build a dummy lo_map for single mode so prefix math doesn't choke
            for i, path in enumerate(plugins):
                lo_map[i] = path.name
        
        return plugin_files, mod_names, lo_map

    def _find_plugins_in_mod(self, mod_identifier: str) -> list[Path]:
        """Hunt for plugins - accepts mod name OR plugin name."""
        # Fast path: passed a plugin filename directly
        if mod_identifier.lower().endswith(('.esp', '.esm', '.esl')):
            plugin_path = self._md.organizer_wrapper.get_plugin_path(mod_identifier)
            if plugin_path:
                return [Path(plugin_path)]
            return []
        
        plugins: list[Path] = []
        
        # Path 1: Direct folder glob by exact name
        mods_root = self._md.organizer_wrapper.mods_path
        mod_path = mods_root / mod_identifier
        if mod_path.exists() and mod_path.is_dir():
            for pattern in ["*.esp", "*.esm", "*.esl"]:
                plugins.extend(mod_path.glob(pattern))
            data_path = mod_path / "Data"
            if data_path.exists():
                for pattern in ["*.esp", "*.esm", "*.esl"]:
                    plugins.extend(data_path.glob(pattern))
        
        # Path 2: LMW reverse resolve — walk LO, ask get_plugin_path where each plugin lives
        # Catches name mismatches where silo key != disk folder name (cleaned masters, etc.)
        if not plugins:
            lo_map = self._md.controller.profile_manager.get_load_order_map()
            for idx in sorted(lo_map.keys()):
                plugin_name = lo_map[idx]
                plugin_path = self._md.organizer_wrapper.get_plugin_path(plugin_name)
                if not plugin_path:
                    continue
                p = Path(plugin_path)
                # Check immediate parent (mod folder) and Data/ grandparent
                parent = p.parent.name
                grandparent = p.parent.parent.name if p.parent.parent else ""
                if parent.lower() == mod_identifier.lower() or grandparent.lower() == mod_identifier.lower():
                    plugins.append(p)
        
        # Deduplicate and validate
        seen: set[Path] = set()
        result: list[Path] = []
        for p in plugins:
            rp = p.resolve()
            if rp.is_file() and rp not in seen:
                seen.add(rp)
                result.append(rp)
        
        return result

    # ---------- Scanning ----------
    def _scan_formids(self) -> None:
        """Scan with activity indicator and logging (from original)."""
        self._md.controller.activity_indicator_toggle.emit(True)
        self._md.controller._handle_worker_log_line("BOS FormID Scan started", MO2_LOG_INFO)
        self._abort_scan = False
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)

        try:
            plugin_files, mod_names, lo_map = self._collect_plugin_files()

            # lo_map already came back correct from _collect_plugin_files
            # Don't rebuild it — the shadow was wiping it empty
            active_plugins = [lo_map[i] for i in sorted(lo_map.keys())]
            
            if not plugin_files:
                self._md.controller._handle_worker_log_line("BOS Scan: no plugins found", MO2_LOG_WARNING)
                return

            filtered = self._processor.scan_plugins(
                plugin_files=plugin_files,
                mod_names=mod_names,
                category=self._cat_combo.currentText(),
                abort_flag=self,
                progress_callback=self._scan_progress,
                 active_plugins=active_plugins
            )

            if self._abort_scan:
                self._md.controller._handle_worker_log_line("BOS Scan aborted", MO2_LOG_INFO)
                return
            if not filtered:
                self._md.controller._handle_worker_log_line("BOS Scan: no records matched", MO2_LOG_INFO)
                return

            self._populate_scan_results(filtered, lo_map)
            self._set_extracted_mode(True)
            self._refresh_scan_btn()
            self._md.controller._update_generate_button()
            self._emit_rows()

        finally:
            self.stop_btn.setVisible(False)
            self._md.controller.activity_indicator_toggle.emit(False)

    def _scan_progress(self, current: int, total: int, msg: str) -> None:
        if current % 100 == 0:
            self._md.controller._handle_worker_log_line(
                f"Scanned {current}/{total}... {msg}", MO2_LOG_DEBUG
            )

    def _populate_scan_results(self, records: list[dict], lo_map: dict[int, str]) -> None:
        """Fill table — uses passed lo_map from silo."""
        self._clear_fid_rows()
        if not records:
            return

        bridge = getattr(self._md.controller, '_plugin_to_mod_bridge', {})
        
        self._table.hide()
        self._table.blockSignals(True)
    
        try:
            for rec in records:
                form_id = rec.get('form_id') or rec.get('formId', '')
                clean_fid = str(form_id).replace("0x", "").replace("0X", "")
                short_fid = clean_fid[-6:].upper() if len(clean_fid) >= 6 else clean_fid.upper()
                
                # Source = scanned plugin (replacement)
                source_plugin = rec.get('plugin_name', 'Unknown')
                
                # --- BRIDGE LOOKUP: plugin -> mod folder ---
                # Blessed plugins (Data/) map to themselves via bridge
                source_mod = bridge.get(source_plugin, source_plugin)
                
                # --- ASSET SWAP DETECTION ---
                # Check manifest for body/skin signatures (pluginless mods)
                is_asset_swap = False
                manifest = getattr(self._md.controller.profile_manager, '_manifest', {})
                entry = manifest.get(source_plugin)
                if entry and ('ASSET_SKIN' in entry.signatures or 'ASSET_BODY' in entry.signatures):
                    is_asset_swap = True
                    
                # Target = LO-resolved owner (victim) via prefix math
                target_plugin = "Skyrim.esm"
                target_mod = "Skyrim.esm"
                
                if len(clean_fid) >= 2:
                    prefix = clean_fid[:2]
                    try:
                        lo_index = int(prefix, 16)
                        # LO map gives us plugin name from index
                        target_plugin = lo_map.get(lo_index, "Skyrim.esm")
                        # Bridge converts plugin to mod folder
                        # Blessed plugins (Skyrim.esm, etc.) stay as plugin names
                        target_mod = bridge.get(target_plugin, target_plugin)
                    except ValueError:
                        pass
                
                # --- MIRROR KILLER ---
                # Bail if source and target are the same folder/plugin
                if source_mod.lower() == target_mod.lower():
                    continue
                
                row_data = {
                    'source_mod': source_mod,
                    'source_fid': f"0x{short_fid}",
                    'target_mod': target_mod,
                    'target_fid': f"0x{short_fid}",
                    'source_plugin': source_plugin,
                    'target_plugin': target_plugin,
                }
                
                # Tooltip showing the swap
                tooltip = f"Replaces {short_fid} in {target_mod} with {source_mod}"
                
                self._add_fid_row(row_data, checked=True, read_only=True, is_asset_swap=is_asset_swap)
                
                # Slap tooltip on row
                row_idx = self._table.rowCount() - 1
                for col in range(5):
                    item = self._table.item(row_idx, col)
                    if item:
                        item.setToolTip(tooltip)
        finally:
            self._table.blockSignals(False)
            self._table.show()
        
        actual_rows = self._get_fid_count()
        self._mode_lbl.setText(f"Scanned mode ({actual_rows} rows)")
        self._update_button_state()
        self._emit_rows()

    # ---------- JSON Handling ----------
    def _reload_json_if_present(self) -> None:
        """Slurp JSON back in — nukes old rows first so we don't stack duplicates."""
        if not self._json_path.exists():
            return
        
        try:
            with open(self._json_path, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            
            recs = saved.get("records", [])
            if not recs:
                return
            
            # Clear first — otherwise we stack duplicates every reload
            self._clear_fid_rows()
            
            for r in recs:
                # Normalize old format (plugin_name -> source_mod)
                if "plugin_name" in r and "source_mod" not in r:
                    r["source_mod"] = r.pop("plugin_name")
                if "sourceName" in r and "source_mod" not in r:
                    r["source_mod"] = r.pop("sourceName")
                
                self._add_fid_row(r, checked=True, read_only=True)
                
            self.log_info(f"Reloaded {len(recs)} FormIDs from {self._json_path.name}")
            
        except Exception as e:
            self.log_warning(f"JSON reload borked: {e}")

    def _on_json_changed(self) -> None:
        """File watcher callback — debounce so we don't thrash on rapid saves."""
        QTimer.singleShot(100, self._reload_json_if_present)


    # ---------- Export ----------
    def _export_formid_list(self) -> None:
        """Dump checked rows to JSON — reads live table state, not stale shadows."""
        live_records = self._get_fid_data()
        if not live_records:
            self.log_info("No checked FormIDs to export")
            return
        
        # Mute the watcher so we don't trigger a reload loop on our own write
        self._watcher.removePath(str(self._json_path))
        
        try:
            # Build export payload from live data — includes targets for round-trip
            records = []
            for d in live_records:
                records.append({
                    "form_id": d.get("form_id", ""),
                    "source_mod": d.get("source_mod", "Unknown"),
                    "source_fid": d.get("source_fid", ""),
                    "target_mod": d.get("target_mod", ""),
                    "target_fid": d.get("target_fid", ""),
                    "category": self._cat_combo.currentText(),
                    "is_asset_swap": d.get("is_asset_swap", False),
                })
            
            payload = {"records": records}
            self._json_path.parent.mkdir(parents=True, exist_ok=True)
            with self._json_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            
            self.log_info(f"Exported {len(records)} FormIDs to {self._json_path.name}")
            
        finally:
            # Re-arm the watcher
            if self._json_path.exists():
                self._watcher.addPath(str(self._json_path))

    # ---------- Generation ----------
    def _on_generate_clicked(self) -> None:
        if not self.output_folder:
            self.log_warning("No output folder selected")
            return

        self._md.controller._handle_worker_log_line("BOS generation started", MO2_LOG_INFO)
        self._md.controller.activity_indicator_toggle.emit(True)

        success, msg = self.generate_patch(Path(self.output_folder), self._md.controller._handle_worker_log_line)

        if hasattr(self._md, 'log_viewer_widget'):
            level = MO2_LOG_INFO if success else MO2_LOG_ERROR
            self._md.log_viewer_widget.append_line(f"BOS-GENERATION: {msg}", level)

        self._md.controller.activity_indicator_toggle.emit(False)

        if success:
            self.log_info(f"BOS INI generated: {msg}")
        else:
            self.log_error(f"BOS generation failed: {msg}")

    def generate_patch(self, output_folder: Path, log_callback) -> tuple[bool, str]:
        """Route to appropriate generator based on mode."""
        # Scan/FID mode takes priority if checked
        if self.scan_all_cb.isChecked():
            return self._generate_from_scanned(output_folder, log_callback)
        
        # M2M mode: requires target, source, AND category selected
        has_target = bool(self.target_mod.strip())
        has_source = bool(self.source_mod.strip())
        has_category = bool(self._m2m_cat_combo.currentText().strip())
        
        if has_target and has_source and has_category:
            return self._generate_mod_to_mod(output_folder, log_callback)
        
        # Fallback to scanned if somehow called without proper setup
        return self._generate_from_scanned(output_folder, log_callback)

    def _generate_from_scanned(self, output_folder: Path, log_callback) -> tuple[bool, str]:
        """Generate BOS INI with LO-resolved targets - blessed plugins handled."""
        records = self._get_fid_data()
        if not records:
            return False, "No FormIDs selected"
        
        # Get LO map and bridge from controller
        lo_map = self._md.controller.profile_manager.get_load_order_map()
        bridge = getattr(self._md.controller, '_plugin_to_mod_bridge', {})
        
        writer_records = []
        for d in records:
            form_id = d.get("form_id", "")
            source_mod = d.get("source_mod", "Unknown")  # Already bridged in populate           
            clean_fid = form_id.replace("0x", "").replace("0X", "")
            if len(clean_fid) >= 6:
                prefix = clean_fid[:2]
                try:
                    lo_index = int(prefix, 16)
                    # LO map gives plugin name from index
                    target_plugin = lo_map.get(lo_index, "Skyrim.esm")
                    # Bridge gives mod folder, blessed plugins (Data/) map to themselves
                    target_mod = bridge.get(target_plugin, target_plugin)
                except ValueError:
                    target_mod = "Skyrim.esm"
            else:
                target_mod = "Skyrim.esm"
            
            writer_records.append({
                "formId": form_id,
                "plugin_name": source_mod,  # Mod folder or plugin name
                "target_plugin": target_mod,  # Mod folder or blessed plugin name
                "is_asset_swap": d.get("is_asset_swap", False),
            })
        
        out_file = output_folder / "BOS_Swap.ini"
        writer = BosWriter()
        
        return writer.write_ini(
            writer_records, 
            out_file, 
            mode="scanned", 
            target_mod=self.target_mod,
            xyz=self.xyz,
            chance=self._scan_chance_spin.value()
        )

    def _generate_mod_to_mod(self, output_folder: Path, log_callback) -> tuple[bool, str]:
        """Generate BOS M2M swap: Source mod objects → Target mod victims."""
        if not self.target_mod or not self.source_mod:
            return False, "Target and Source mods required"
        
        # --- MIRROR KILLER AT GENERATION ---
        if self.source_mod.lower() == self.target_mod.lower():
            return False, "Source and Target are the same mod (no swap needed)"
        
        log_callback(f"BOS M2M: {self.source_mod} → {self.target_mod}", MO2_LOG_INFO)
        
        # Get category and chance from M2M UI
        category = self._m2m_cat_combo.currentText()
        chance = self._m2m_chance_spin.value()
        
        # Find plugins in source mod folder — pluginless mods return empty here
        source_plugins = self._find_plugins_in_mod(self.source_mod)
        
        # Pluginless check — asset-only mods have no plugins but are valid sources
        pluginless = getattr(self._md.controller, '_rich_silos', {}).get("BOS_MOD", {})
        is_pluginless = self.source_mod in pluginless
        
        if not source_plugins and not is_pluginless:
            return False, f"No plugins found in source mod: {self.source_mod}"
        
        if is_pluginless:
            log_callback(f"BOS M2M: {self.source_mod} is pluginless — asset swap mode", MO2_LOG_INFO)
        
        log_callback(f"BOS M2M: Found {len(source_plugins)} plugins in {self.source_mod}", MO2_LOG_DEBUG)
        
        # Get active plugins for reader context
        audit = self._md.controller.profile_manager.get_audit_cache()
        active_plugins = list(audit.keys())
        
        # Scan with M2M logic — processor handles pluginless internally now
        log_callback(f"BOS M2M: Scanning for {category} records...", MO2_LOG_INFO)
        m2m_records = self._processor.scan_m2m(
            source_plugins=source_plugins,
            source_mod_name=self.source_mod,
            target_mod_name=self.target_mod,
            category=category,
            abort_flag=self,
            progress_callback=lambda current, total, msg: log_callback(
                f"BOS M2M scan: {current}/{total} — {msg}", MO2_LOG_DEBUG
            ),
            active_plugins=active_plugins
        )
        
        if not m2m_records:
            return False, f"No {category} records found for M2M pairing"
        
        log_callback(f"BOS M2M: Pairing {len(m2m_records)} records", MO2_LOG_INFO)
        
        # Build writer records...
        writer_records = []
        for rec in m2m_records:
            writer_records.append({
                "formId": rec["form_id"],                    
                "target_form_id": rec["target_form_id"],     
                "plugin_name": self.source_mod if is_pluginless else rec["plugin_name"],           
                "target_plugin": rec["target_plugin_file"], 
                "is_asset_swap": is_pluginless or rec.get("is_asset_swap", False),
                "chance_percent": chance,
            })
        
        # ... filename building ...
        def safe_name(name):
            cleaned = "".join(c if c.isalnum() else "_" for c in name).strip("_")
            return cleaned[:25]
        
        safe_target = safe_name(self.target_mod)
        safe_source = safe_name(self.source_mod)
        out_file = output_folder / f"BOS_{safe_target}_to_{safe_source}_SWAP.ini"
        
        log_callback(f"BOS M2M: Writing {len(writer_records)} swaps to {out_file.name}", MO2_LOG_INFO)
        
        writer = BosWriter()
        success, msg = writer.write_ini(
            writer_records, 
            out_file, 
            mode="modswap", 
            target_mod=self.target_mod,
            xyz=self.xyz,
            chance=chance
        )
        
        if success:
            log_callback(f"BOS M2M: Complete – {out_file.name}", MO2_LOG_INFO)
        else:
            log_callback(f"BOS M2M: Write failed – {msg}", MO2_LOG_ERROR)
        
        return success, msg

    # ---------- Helpers ----------
    def _set_combo_persist(self, combo: QComboBox, value: str) -> None:
        if not value:
            combo.setCurrentIndex(-1)
            return
        index = combo.findText(value)
        if index == -1:
            combo.addItem(value)
            index = combo.findText(value)
        combo.setCurrentIndex(index)
        combo.setEditText(value)

    def _emit_rows(self) -> None:
        self._row_count_lbl.setText(f"{self._get_fid_checked_count()}/{self._get_fid_count()}")
        self.rows_changed.emit(self._get_fid_data())
    
class StopScan(Exception):
    pass
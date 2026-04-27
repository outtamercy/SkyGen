"""
patch_settings.py – stripped-down version  
Keeps only generic file / path helpers;  
Sky-Patcher-specific widgets live **exclusively** in SkyPatcherPanel.
"""
from __future__ import annotations

from PyQt6.QtWidgets import ( # type: ignore
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal # type: ignore
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from ..utils.logger import LoggingMixin, SkyGenLogger
from ..core.constants import GAME_VERSIONS, OUTPUT_TYPES   # still used for output-type logic

if TYPE_CHECKING:
    from ..src.organizer_wrapper import OrganizerWrapper


class PatchSettingsWidget(QWidget, LoggingMixin):
    """
    Generic helper panel:
    – target / source mod  (plugins OR mods)
    – output folder
    – generate-modlist checkbox
    – broad-category-swap checkbox
    NO category, NO keywords, NO generate-all – those belong to SkyPatcherPanel.
    """

    # ---------- generic signals ----------
    target_mod_changed = pyqtSignal(str)
    source_mod_changed = pyqtSignal(str)
    output_folder_changed = pyqtSignal(str)
    generate_modlist_toggled = pyqtSignal(bool)
    broad_category_swap_toggled = pyqtSignal(bool)

    # Sentence Builder fields for SkyPatcher
    sp_filter_type: str = ""      # e.g., "filterByKeywords"
    sp_action_type: str = ""      # e.g., "addKeywords" 
    sp_value_formid: str = ""     # e.g., "00012345"
    sp_lmw_winners_only: bool = True   # Last Mod Wins toggle
    sp_use_sentence_builder: bool = True  # <-- ADD: Gate for manual override vs auto-detect

    # --------------------------------------------------
    # --------------------------------------------------
    def __init__(
        self,
        organizer_wrapper: OrganizerWrapper,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        LoggingMixin.__init__(self)
        self.logger = SkyGenLogger.get_instance()
        self.log_info("PatchSettingsWidget (generic) initialized.")

        self.organizer_wrapper = organizer_wrapper
        self._setup_ui()
        self._connect_signals()

    # --------------------------------------------------
    def _setup_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Target mod/plugin
        self.target_mod_group = QGroupBox("Target Mod / Plugin")
        target_layout = QVBoxLayout(self.target_mod_group)
        self.main_layout.addWidget(self.target_mod_group)

        self.target_mod_label = QLabel("Target mod/plugin name:")
        target_layout.addWidget(self.target_mod_label)
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.setEditable(True)
        target_layout.addWidget(self.target_mod_combo)

        # Source mod/plugin (optional)
        self.source_mod_group = QGroupBox("Source Mod / Plugin (optional)")
        source_layout = QVBoxLayout(self.source_mod_group)
        self.main_layout.addWidget(self.source_mod_group)

        self.source_mod_label = QLabel("Source mod/plugin name:")
        source_layout.addWidget(self.source_mod_label)
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.setEditable(True)
        source_layout.addWidget(self.source_mod_combo)

        # Output folder
        self.output_group = QGroupBox("Output")
        out_layout = QVBoxLayout(self.output_group)
        self.main_layout.addWidget(self.output_group)

        out_row = QHBoxLayout()
        self.output_folder_label = QLabel("Output folder:")
        out_row.addWidget(self.output_folder_label)
        self.output_folder_input = QLineEdit()
        out_row.addWidget(self.output_folder_input)
        self.output_folder_browse_btn = QPushButton("Browse")
        self.output_folder_browse_btn.clicked.connect(
            lambda: self._browse_directory(self.output_folder_input)
        )
        out_row.addWidget(self.output_folder_browse_btn)
        out_layout.addLayout(out_row)

        # Generic options
        opts_group = QGroupBox("Generic Options")
        opts_layout = QVBoxLayout(opts_group)
        self.main_layout.addWidget(opts_group)

        self.generate_modlist_checkbox = QCheckBox("Generate modlist.txt alongside patch")
        opts_layout.addWidget(self.generate_modlist_checkbox)

        self.broad_category_swap_checkbox = QCheckBox(
            "Enable broad-category item swapping (may include more items)"
        )
        opts_layout.addWidget(self.broad_category_swap_checkbox)

        self.main_layout.addStretch(1)

    # --------------------------------------------------
    def _connect_signals(self) -> None:
        self.target_mod_combo.currentTextChanged.connect(self.target_mod_changed.emit)
        self.source_mod_combo.currentTextChanged.connect(self.source_mod_changed.emit)
        self.output_folder_input.textChanged.connect(self.output_folder_changed.emit)
        self.generate_modlist_checkbox.toggled.connect(self.generate_modlist_toggled.emit)
        self.broad_category_swap_checkbox.toggled.connect(self.broad_category_swap_toggled.emit)

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------
    def _browse_directory(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            line_edit.setText(path)

    # --------------------------------------------------
    # Getters / setters – generic only
    # --------------------------------------------------
    def get_target_mod(self) -> str:
        return self.target_mod_combo.currentText()

    def set_target_mod(self, text: str) -> None:
        idx = self.target_mod_combo.findText(text)
        if idx != -1:
            self.target_mod_combo.setCurrentIndex(idx)
        else:
            self.target_mod_combo.setEditText(text)

    def get_source_mod(self) -> str:
        return self.source_mod_combo.currentText()

    def set_source_mod(self, text: str) -> None:
        idx = self.source_mod_combo.findText(text)
        if idx != -1:
            self.source_mod_combo.setCurrentIndex(idx)
        else:
            self.source_mod_combo.setEditText(text)

    def get_output_folder(self) -> str:
        return self.output_folder_input.text()

    def set_output_folder(self, text: str) -> None:
        self.output_folder_input.setText(text)

    def get_generate_modlist(self) -> bool:
        return self.generate_modlist_checkbox.isChecked()

    def set_generate_modlist(self, checked: bool) -> None:
        self.generate_modlist_checkbox.setChecked(checked)

    def get_broad_category_swap(self) -> bool:
        return self.broad_category_swap_checkbox.isChecked()

    def set_broad_category_swap(self, checked: bool) -> None:
        self.broad_category_swap_checkbox.setChecked(checked)

    # --------------------------------------------------
    # Dynamic population – called by controller
    # --------------------------------------------------
    def set_available_mods(self, names: List[str]) -> None:
        """Fill both combos while preserving user-typed text."""
        for combo in (self.target_mod_combo, self.source_mod_combo):
            current = combo.currentText()
            combo.clear()
            combo.addItem("")
            combo.addItems(names)
            if current in names:
                combo.setCurrentText(current)
            else:
                combo.setEditText(current)
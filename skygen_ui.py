import mobase
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QCheckBox, QGroupBox, QRadioButton, QWidget, QSizePolicy,
    QListWidget, QListWidgetItem
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QSize
from pathlib import Path
import os
import json
import logging
from typing import Any, Optional, Union

# Import necessary functions from skygen_file_utilities
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    # safe_launch_xedit, # <--- REMOVED THIS LINE
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
)

# Import MO2_LOG_* constants from skygen_constants
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
)


class OrganizerWrapper:
    """
    A wrapper class for the mobase.IOrganizer interface to handle logging.
    """
    def __init__(self, organizer: 'mobase.IOrganizer'):
        self._organizer = organizer
        self.dialog_instance: Optional[Any] = None
        self._logger = logging.getLogger('skygen')

    def set_log_file_path(self, path: Path):
        self._logger.info(f"SkyGen: (Wrapper) Log file path set to: {path}. Logging handled by main logger setup.")

    def log(self, mo2_log_level: int, message: str):
        log_level_map = {
            MO2_LOG_CRITICAL: logging.CRITICAL,
            MO2_LOG_ERROR: logging.ERROR,
            MO2_LOG_WARNING: logging.WARNING,
            MO2_LOG_INFO: logging.INFO,
            MO2_LOG_DEBUG: logging.DEBUG,
            MO2_LOG_TRACE: logging.DEBUG
        }
        python_log_level = log_level_map.get(mo2_log_level, logging.INFO)
        self._logger.log(python_log_level, message)

    def close_log_file(self):
        self._logger.info("SkyGen: (Wrapper) Close log file called. Main logger handles file lifecycle.")

    def pluginList(self):
        try:
            return self._organizer.pluginList()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in pluginList: {e}")
            return []
    
    def getExecutables(self):
        """
        Returns a dictionary of MO2's configured executables.
        This is needed by get_xedit_exe_path in skygen_file_utilities.py.
        """
        try:
            return self._organizer.getExecutables()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in getExecutables: {e}"); return {}
    
    def modsPath(self):
        try:
            return self._organizer.modsPath()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in modsPath: {e}")
            return ""

    def startApplication(self, name, args, cwd):
        try:
            return self._organizer.startApplication(name, args, cwd)
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error starting application: {e}")
            return None

    def basePath(self):
        try:
            return self._organizer.basePath()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in basePath: {e}")
            return ""

    def pluginDataPath(self):
        try:
            return self._organizer.pluginDataPath()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in pluginDataPath: {e}")
            return ""

    def gameInfo(self):
        """Delegates to mobase.IOrganizer.gameInfo()."""
        try:
            return self._organizer.gameInfo()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in gameInfo: {e}")
            return None

    def gameFeatures(self):
        try:
            return self._organizer.gameFeatures()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in gameFeatures: {e}")
            return None

    def modList(self):
        try:
            return self._organizer.modList()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in modList: {e}")
            return []

    def modPath(self, mod_name: str) -> str:
        try:
            return self._organizer.modPath(mod_name)
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in modPath: {e}")
            return ""
    
    def currentGame(self):
        """Delegates to mobase.IOrganizer.currentGame()."""
        try:
            return self._organizer.currentGame()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in currentGame: {e}")
            return None

    def profile(self):
        try:
            return self._organizer.profile()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in profile: {e}")
            return None


# Dummy classes for PyQt6 if not available.
try:
    from PyQt6.QtWidgets import QWidget, QApplication, QMessageBox, QLabel, QLineEdit, QPushButton, QComboBox, QVBoxLayout, QHBoxLayout, QFileDialog, QCheckBox, QGroupBox, QRadioButton, QSizePolicy, QListWidget, QListWidgetItem
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import Qt, QSize
except ImportError:
    class QWidget:
        def __init__(self, *args, **kwargs):
            pass

    class QApplication:
        def __init__(self, *args, **kwargs):
            pass

    class QMessageBox:
        def __init__(self, *args, **kwargs):
            pass

    class QLabel:
        def __init__(self, *args, **kwargs):
            pass

    class QLineEdit:
        def __init__(self, *args, **kwargs):
            pass

    class QPushButton:
        def __init__(self, *args, **kwargs):
            pass

    class QComboBox:
        def __init__(self, *args, **kwargs):
            pass

    class QVBoxLayout:
        def __init__(self, *args, **kwargs):
            pass

    class QHBoxLayout:
        def __init__(self, *args, **kwargs):
            pass

    class QFileDialog:
        def __init__(self, *args, **kwargs):
            pass

    class QCheckBox:
        def __init__(self, *args, **kwargs):
            pass

    class QGroupBox:
        def __init__(self, *args, **kwargs):
            pass

    class QRadioButton:
        def __init__(self, *args, **kwargs):
            pass

    class QSizePolicy:
        def __init__(self, *args, **kwargs):
            pass

    class QListWidget:
        def __init__(self, *args, **kwargs):
            pass

    class QListWidgetItem:
        def __init__(self, *args, **kwargs):
            pass

    class QIcon:
        def __init__(self, *args, **kwargs):
            pass

    class QSize:
        def __init__(self, *args, **kwargs):
            pass

    class Qt:
        WindowContextHelpButtonHint = 0
        CheckState = type('CheckState', (object,), {'Checked': type('Checked', (object,), {'value': 2})})
        WindowStaysOnTopHint = 0


class SkyGenToolDialog(QDialog):
    """
    The main UI dialog for the SkyGen plugin tool.
    """
    def __init__(self, wrapped_organizer: OrganizerWrapper, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.wrapped_organizer = wrapped_organizer
        self.setWindowTitle("SkyGen - Automate Your Modding!")
        self.setFixedSize(500, 600)
        if hasattr(Qt, 'WindowContextHelpButtonHint'):
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        else:
            self.wrapped_organizer.log(2, "SkyGen: WARNING: Qt.WindowContextHelpButtonHint not found. Skipping context help button removal.")
        
        self.selected_output_type = "SkyPatcher YAML"
        self.selected_game_version = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.selected_category = ""
        self.output_folder_path = ""
        self.igpc_json_path = ""
        self.determined_xedit_exe_path: Optional[Path] = None
        self.determined_xedit_executable_name: str = ""
        self.game_root_path: Optional[Path] = None
        self.generate_all = False
        self.executables_dict = {}
        self.pre_exported_xedit_json_path = ""

        self._setup_ui()
        self._populate_game_versions()
        self._populate_categories()
        self._populate_mods()
        self._load_config()


    def _setup_ui(self):
        """Sets up the layout and widgets of the dialog."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)

        output_type_group = QGroupBox("Select Output Type")
        output_type_layout = QHBoxLayout()
        self.yaml_radio = QRadioButton("SkyPatcher YAML")
        self.bos_ini_radio = QRadioButton("BOS INI")
        
        self.yaml_radio.setChecked(True)
        self.yaml_radio.toggled.connect(self._on_output_type_toggled)
        self.bos_ini_radio.toggled.connect(self._on_output_type_toggled)
        
        output_type_layout.addWidget(self.yaml_radio)
        output_type_layout.addWidget(self.bos_ini_radio)
        output_type_layout.addStretch(1)
        output_type_group.setLayout(output_type_layout)
        main_layout.addWidget(output_type_group)

        general_settings_group = QGroupBox("General Settings")
        general_settings_layout = QVBoxLayout()

        game_version_group = QGroupBox("Game Version")
        game_version_layout = QHBoxLayout()
        self.sse_radio = QRadioButton("SkyrimSE")
        self.skyrimvr_radio = QRadioButton("SkyrimVR")

        self.sse_radio.toggled.connect(self._on_game_version_toggled)
        self.skyrimvr_radio.toggled.connect(self._on_game_version_toggled)

        game_version_layout.addWidget(self.sse_radio)
        game_version_layout.addWidget(self.skyrimvr_radio)
        game_version_layout.addStretch(1)
        game_version_group.setLayout(game_version_layout)
        general_settings_layout.addWidget(game_version_group)

        output_folder_layout = QHBoxLayout()
        output_folder_label = QLabel("Output Folder:")
        self.output_folder_lineEdit = QLineEdit()
        self.output_folder_lineEdit.setPlaceholderText("Path where generated files will be saved")
        self.output_folder_browse_button = QPushButton("Browse...")
        self.output_folder_browse_button.clicked.connect(self._browse_output_folder)
        
        output_folder_layout.addWidget(output_folder_label)
        output_folder_layout.addWidget(self.output_folder_lineEdit)
        output_folder_layout.addWidget(self.output_folder_browse_button)
        general_settings_layout.addLayout(output_folder_layout)

        general_settings_group.setLayout(general_settings_layout)
        main_layout.addWidget(general_settings_group)


        self.yaml_settings_group = QGroupBox("SkyPatcher YAML Settings")
        yaml_settings_layout = QVBoxLayout()

        target_mod_layout = QHBoxLayout()
        target_mod_label = QLabel("Target Mod:")
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.setEditable(True)
        self.target_mod_combo.setPlaceholderText("Select the mod you are patching TO (e.g., DynDOLOD Output)")
        self.target_mod_combo.activated.connect(self._on_target_mod_selected)
        target_mod_layout.addWidget(target_mod_label)
        target_mod_layout.addWidget(self.target_mod_combo)
        yaml_settings_layout.addLayout(target_mod_layout)

        source_mod_layout = QHBoxLayout()
        source_mod_label = QLabel("Source Mod:")
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.setEditable(True)
        self.source_mod_combo.setPlaceholderText("Select the mod you are patching FROM (e.g., Enhanced Landscapes)")
        self.source_mod_combo.activated.connect(self._on_source_mod_selected)
        source_mod_layout.addWidget(source_mod_label)
        source_mod_layout.addWidget(self.source_mod_combo)
        yaml_settings_layout.addLayout(source_mod_layout)

        self.generate_all_checkbox = QCheckBox("Generate YAML for all compatible source mods (vs. selected source)")
        self.generate_all_checkbox.setChecked(False)
        self.generate_all_checkbox.stateChanged.connect(self._on_generate_all_toggled)
        yaml_settings_layout.addWidget(self.generate_all_checkbox)

        category_layout = QHBoxLayout()
        category_label = QLabel("Category (Record Type):")
        self.category_combo = QComboBox()
        self.category_combo.setPlaceholderText("e.g., STAT, TREE, GRAS")
        self.category_combo.setEditable(True)
        self.category_combo.activated.connect(self._on_category_selected)
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo)
        yaml_settings_layout.addLayout(category_layout)

        keywords_layout = QHBoxLayout()
        keywords_label = QLabel("Keywords (comma-separated):")
        self.keywords_lineEdit = QLineEdit()
        self.keywords_lineEdit.setPlaceholderText("Optional: e.g., pine, oak, rock")
        self.keywords_lineEdit.textChanged.connect(self._on_keywords_changed)
        keywords_layout.addWidget(keywords_label)
        keywords_layout.addWidget(self.keywords_lineEdit)
        yaml_settings_layout.addLayout(keywords_layout)
        
        self.broad_category_swap_checkbox = QCheckBox("Enable Broad Category Swap (experimental)")
        self.broad_category_swap_checkbox.setChecked(False)
        yaml_settings_layout.addWidget(self.broad_category_swap_checkbox)

        self.yaml_settings_group.setLayout(yaml_settings_layout)
        main_layout.addWidget(self.yaml_settings_group)


        self.bos_ini_settings_group = QGroupBox("BOS INI Settings")
        bos_ini_layout = QVBoxLayout()
        
        igpc_json_layout = QHBoxLayout()
        igpc_json_label = QLabel("IGPC JSON Path:")
        self.igpc_json_lineEdit = QLineEdit()
        self.igpc_json_lineEdit.setPlaceholderText("Path to IGPC_DynaDOLOD.json")
        self.igpc_json_browse_button = QPushButton("Browse...")
        self.igpc_json_browse_button.clicked.connect(self._browse_igpc_json)

        igpc_json_layout.addWidget(igpc_json_label)
        igpc_json_layout.addWidget(self.igpc_json_lineEdit)
        igpc_json_layout.addWidget(self.igpc_json_browse_button)
        bos_ini_layout.addLayout(igpc_json_layout)

        self.bos_ini_settings_group.setLayout(bos_ini_layout)
        main_layout.addWidget(self.bos_ini_settings_group)
        self.bos_ini_settings_group.setVisible(False)


        button_layout = QHBoxLayout()
        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self.accept)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addStretch(1)
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)


    def _populate_game_versions(self):
        """Populates the game version radio buttons with supported game types (SkyrimSE, SkyrimVR)."""
        current_game_type_enum = None
        current_game_name = ""

        try:
            current_game = self.wrapped_organizer.currentGame()
            if current_game is not None:
                current_game_type_enum = current_game.type()
                if hasattr(mobase.GameType, 'SSE') and current_game_type_enum == mobase.GameType.SSE:
                    current_game_name = "SkyrimSE"
                elif hasattr(mobase.GameType, 'SkyrimVR') and current_game_type_enum == mobase.GameType.SkyrimVR:
                    current_game_name = "SkyrimVR"
        except Exception as e:
            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not determine current game type from organizer: {e}. Defaulting to no specific current game.")

        if current_game_name == "SkyrimSE":
            self.sse_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"
        elif current_game_name == "SkyrimVR":
            self.skyrimvr_radio.setChecked(True)
            self.selected_game_version = "SkyrimVR"
        else:
            self.sse_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"
            self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Defaulting game version to SkyrimSE as current game not detected or supported.")
        
        self.wrapped_organizer.log(0, f"SkyGen: Initial game version selected: {self.selected_game_version}")


    def _populate_categories(self):
        """Populates the category combobox with common record types."""
        common_categories = [
            "ARMO", "WEAP", "AMMO", "MISC", "STAT", "TREE", "GRAS", "FLOR", "CONT",
            "LIGH", "CELL", "WRLD", "QUST", "SPEL", "ENCH", "COBJ", "ALCH", "BOOK",
            "KEYM", "SCRL", "SLGM", "SOUL", "LVLI", "ACTI", "APPA", "ARMA", "CCEM",
            "CSTY", "DOOR", "EFSH", "IDLE", "IMAD", "LCTN", "MGEF", "MOVE", "MSTT",
            "PMIS", "PROJ", "PWAT", "REGN", "SGST", "SMQN", "SNCT", "SNDR", "TXST",
            "VTYP", "WATR", "WRLD", "ZOOM", "GMST"
        ]
        self.category_combo.addItems(sorted(common_categories))
        if common_categories:
            self.selected_category = self.category_combo.currentText()


    def _populate_mods(self):
        """
        Populates the mod comboboxes with active mods, conditionally filtering for plugins
        based on the selected output type (SkyPatcher requires plugins, BOS does not).
        """
        mod_list = self.wrapped_organizer.modList()
        active_mods_for_display = []
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Starting mod population for UI dropdowns.") 

        enabled_mods_internal_names = set()
        try:
            profile_obj = self.wrapped_organizer._organizer.profile()
            if profile_obj:
                enabled_mods_internal_names = set(profile_obj.enabledMods())
                self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Found {len(enabled_mods_internal_names)} mods enabled in current profile.")
            else:
                self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: Could not retrieve active MO2 profile. Mod list might be incomplete.")
        except Exception as e:
            self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: Error getting enabled mods from profile: {e}")

        filter_for_plugins = (self.selected_output_type == "SkyPatcher YAML")

        for mod_internal_name in mod_list.allMods():
            if mod_internal_name in enabled_mods_internal_names:
                display_name = mod_list.displayName(mod_internal_name)
                
                if filter_for_plugins:
                    plugin_name = self._get_plugin_name_from_mod_name(display_name, mod_internal_name)
                    if plugin_name:
                        active_mods_for_display.append(display_name)
                else:
                    active_mods_for_display.append(display_name)

        active_mods_for_display.sort(key=str.lower)
        
        self.target_mod_combo.clear()
        self.source_mod_combo.clear()

        self.target_mod_combo.addItem("")
        self.source_mod_combo.addItem("")

        self.target_mod_combo.addItems(active_mods_for_display)
        self.source_mod_combo.addItems(active_mods_for_display)

        if active_mods_for_display:
            default_target_mods = ["DynDOLOD Output", "TexGen Output", "MergePlugins", "Smashed Patch"]
            for default_mod in default_target_mods:
                if default_mod in active_mods_for_display:
                    self.target_mod_combo.setCurrentIndex(self.target_mod_combo.findText(default_mod))
                    self.selected_target_mod_name = default_mod
                    break
            
            if not self.selected_target_mod_name and active_mods_for_display:
                self.target_mod_combo.setCurrentIndex(1)
                self.selected_target_mod_name = self.target_mod_combo.currentText()

            if active_mods_for_display:
                self.source_mod_combo.setCurrentIndex(1)
                self.selected_source_mod_name = self.source_mod_combo.currentText()
        
        self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: UI mod population complete. Found {len(active_mods_for_display)} active mods for display.")


    def _get_plugin_name_from_mod_name(self, mod_display_name: str, mod_internal_name: str) -> Optional[str]:
        """
        Attempts to find the primary plugin file (.esp, .esm, .esl) for a given mod.
        Performs a recursive search within the mod's directory.
        """
        mod_obj = self.wrapped_organizer._organizer.modList().getMod(mod_internal_name) 
        if not mod_obj:
            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not find IMod object for '{mod_display_name}' (Internal: '{mod_internal_name}').")
            return None

        mod_path = Path(mod_obj.absolutePath()) 
        if not mod_path.is_dir():
            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Mod directory for '{mod_display_name}' not found or not a directory at: {mod_path}.")
            return None

        plugin_files = []
        plugin_files.extend(mod_path.glob("**/*.esm"))
        plugin_files.extend(mod_path.glob("**/*.esp"))
        plugin_files.extend(mod_path.glob("**/*.esl"))
        
        for p_file in plugin_files:
            if p_file.stem.lower() == mod_internal_name.lower():
                self.wrapped_organizer.log(MO2_LOG_TRACE, f"SkyGen: DEBUG: Found exact plugin match for '{mod_display_name}': {p_file.name}")
                return p_file.name

        if len(plugin_files) == 1:
            # Corrected: Access the first element of the list before getting its name
            self.wrapped_organizer.log(MO2_LOG_TRACE, f"SkyGen: DEBUG: Found single plugin file for '{mod_display_name}': {plugin_files[0].name}")
            return plugin_files[0].name
        elif plugin_files:
            # Corrected: Access the first element of the sorted list before getting its name
            sorted_plugins = sorted(plugin_files, key=lambda p: p.name.lower())
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: INFO: Multiple plugin files found for '{mod_display_name}' and no exact match. Picking '{sorted_plugins[0].name}'.")
            return sorted_plugins[0].name
        
        self.wrapped_organizer.log(MO2_LOG_TRACE, f"SkyGen: No plugin file (.esp, .esm, .esl) found after recursive search for mod '{mod_display_name}' (Internal: '{mod_internal_name}').")
        return None


    def _browse_output_folder(self):
        """Opens a dialog to select the output folder."""
        current_path = self.output_folder_lineEdit.text() if self.output_folder_lineEdit.text() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", current_path)
        if folder:
            self.output_folder_path = folder
            self.output_folder_lineEdit.setText(folder)
            self.wrapped_organizer.log(1, f"SkyGen: Output folder set to: {folder}")


    def _browse_igpc_json(self):
        """Opens a dialog to select the IGPC JSON file."""
        current_path = self.igpc_json_lineEdit.text() if self.igpc_json_lineEdit.text() else str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(self, "Select IGPC JSON File", current_path, "JSON Files (*.json)")
        if file_path:
            self.igpc_json_path = file_path
            self.igpc_json_lineEdit.setText(file_path)
            self.wrapped_organizer.log(1, f"SkyGen: IGPC JSON file set to: {file_path}")


    def _on_output_type_toggled(self):
        """Handles changes in the output type radio buttons."""
        if self.yaml_radio.isChecked():
            self.selected_output_type = "SkyPatcher YAML"
            self.yaml_settings_group.setVisible(True)
            self.bos_ini_settings_group.setVisible(False)
            self.generate_all_checkbox.setVisible(True)
            self.wrapped_organizer.log(0, "SkyGen: Output type set to SkyPatcher YAML.")
        elif self.bos_ini_radio.isChecked():
            self.selected_output_type = "BOS INI"
            self.yaml_settings_group.setVisible(False)
            self.bos_ini_settings_group.setVisible(True)
            self.generate_all_checkbox.setVisible(False)
            self.wrapped_organizer.log(0, "SkyGen: Output type set to BOS INI.")
        self._populate_mods()
        self._save_config()


    def _on_game_version_toggled(self):
        """Handles changes in the game version radio buttons."""
        if self.sse_radio.isChecked():
            self.selected_game_version = "SkyrimSE"
        elif self.skyrimvr_radio.isChecked():
            self.selected_game_version = "SkyrimVR"
        self.wrapped_organizer.log(0, f"SkyGen: Game version selected: {self.selected_game_version}")
        self._save_config()


    def _on_target_mod_selected(self):
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Target mod selected: {self.selected_target_mod_name}")
        self._save_config()


    def _on_source_mod_selected(self):
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Source mod selected: {self.selected_source_mod_name}")
        self._save_config()


    def _on_category_selected(self):
        self.selected_category = self.category_combo.currentText().upper()
        self.wrapped_organizer.log(0, f"SkyGen: Category selected: {self.selected_category}")
        self.category_combo.setCurrentText(self.selected_category)
        self._save_config()


    def _on_keywords_changed(self):
        self.keywords_lineEdit.setText(self.keywords_lineEdit.text().lower())
        self._save_config()


    def _on_generate_all_toggled(self, state):
        self.generate_all = (state == Qt.CheckState.Checked.value)
        self.source_mod_combo.setEnabled(not self.generate_all)
        self.wrapped_organizer.log(0, f"SkyGen: Generate All checkbox toggled: {self.generate_all}")
        self._save_config()


    def _get_config_path(self) -> Path:
        """Returns the path to the plugin's config.json file."""
        return Path(self.wrapped_organizer.pluginDataPath()) / "SkyGen" / "config.json"


    def _load_config(self):
        """Loads saved settings from config.json."""
        config_path = self._get_config_path()
        if config_path.is_file():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                output_type = config.get("output_type", "SkyPatcher YAML")
                if output_type == "SkyPatcher YAML":
                    self.yaml_radio.setChecked(True)
                else:
                    self.bos_ini_radio.setChecked(True)
                self._on_output_type_toggled()
                
                saved_game_version = config.get("game_version", "SkyrimSE")
                if saved_game_version == "SkyrimSE":
                    self.sse_radio.setChecked(True)
                elif saved_game_version == "SkyrimVR":
                    self.skyrimvr_radio.setChecked(True)
                self._on_game_version_toggled()
                
                self.output_folder_lineEdit.setText(config.get("output_folder_path", str(Path(self.wrapped_organizer.basePath()) / "overwrite")))
                self.output_folder_path = self.output_folder_lineEdit.text()

                self.target_mod_combo.setCurrentIndex(
                    self.target_mod_combo.findText(config.get("target_mod_name", ""))
                )
                self.source_mod_combo.setCurrentIndex(
                    self.source_mod_combo.findText(config.get("source_mod_name", ""))
                )
                self.category_combo.setCurrentIndex(
                    self.category_combo.findText(config.get("category", ""))
                )
                self.keywords_lineEdit.setText(config.get("keywords", ""))
                self.broad_category_swap_checkbox.setChecked(config.get("broad_category_swap_enabled", False))
                self.generate_all_checkbox.setChecked(config.get("generate_all", False))

                self.igpc_json_lineEdit.setText(config.get("igpc_json_path", ""))
                self.igpc_json_path = self.igpc_json_lineEdit.text()

                self.determined_xedit_exe_path = Path(config.get("xedit_exe_path", "")) if config.get("xedit_exe_path") else None
                self.determined_xedit_executable_name = config.get("xedit_mo2_name", "")

                self.wrapped_organizer.log(1, "SkyGen: Settings loaded successfully.")
            except Exception as e:
                self.wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to load settings from config.json: {e}")
        else:
            self.wrapped_organizer.log(1, "SkyGen: config.json not found, using default settings.")
            self.output_folder_path = str(Path(self.wrapped_organizer.basePath()) / "overwrite")
            self.output_folder_lineEdit.setText(self.output_folder_path)


    def _save_config(self):
        """Saves current settings to config.json."""
        config_path = self._get_config_path()
        config_data = {
            "output_type": self.selected_output_type,
            "game_version": self.selected_game_version,
            "output_folder_path": self.output_folder_lineEdit.text(),
            "target_mod_name": self.target_mod_combo.currentText(),
            "source_mod_name": self.source_mod_combo.currentText(),
            "category": self.category_combo.currentText(),
            "keywords": self.keywords_lineEdit.text(),
            "broad_category_swap_enabled": self.broad_category_swap_checkbox.isChecked(),
            "generate_all": self.generate_all_checkbox.isChecked(),
            "igpc_json_path": self.igpc_json_lineEdit.text(),
            "xedit_exe_path": str(self.determined_xedit_exe_path) if self.determined_xedit_exe_path else "",
            "xedit_mo2_name": self.determined_xedit_executable_name
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
            self.wrapped_organizer.log(0, "SkyGen: Settings saved.")
        except Exception as e:
            self.wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to save settings to config.json: {e}")
            self.showError("Save Error", f"Failed to save settings: {e}")


    def showError(self, title: str, message: str):
        """Displays an error message box."""
        QMessageBox.critical(self, title, message)
        self.wrapped_organizer.log(4, f"SkyGen: UI Error: {title} - {message}")

    def showWarning(self, title: str, message: str):
        """Displays a warning message box."""
        QMessageBox.warning(self, title, message)
        self.wrapped_organizer.log(3, f"SkyGen: UI Warning: {title} - {message}")

    def showInformation(self, title: str, message: str):
        """Displays an information message box."""
        QMessageBox.information(self, title, message)
        self.wrapped_organizer.log(2, f"SkyGen: UI Info: {title} - {message}")

    def _generate_skypatcher_yaml_internal(self) -> Optional[dict]:
        """
        Internal method to gather all necessary parameters for SkyPatcher YAML generation
        and return them. It no longer performs the xEdit launch or YAML writing directly.
        """
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Preparing parameters for SkyPatcher YAML generation.")

        target_mod_display_name = self.selected_target_mod_name
        source_mod_display_name = self.selected_source_mod_name
        category = self.selected_category
        keywords_str = self.keywords_lineEdit.text().strip()
        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
        broad_category_swap_enabled = self.broad_category_swap_checkbox.isChecked()
        output_folder_path = Path(self.output_folder_path)

        if not target_mod_display_name:
            self.showError("Input Error", "Please select a Target Mod.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Target Mod not selected. Aborting YAML generation parameter preparation.")
            return None

        if not category:
            self.showError("Input Error", "Please select or enter a Category (Record Type).")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Category not selected. Aborting YAML generation parameter preparation.")
            return None

        # Determine game mode flag for xEdit (e.g., -SE, -VR)
        game_mode_flag = ""
        if self.selected_game_version == "SkyrimSE":
            game_mode_flag = "SE"
        elif self.selected_game_version == "SkyrimVR":
            game_mode_flag = "VR"
        else:
            self.showError("Game Version Error", "Could not determine game version. Please select SkyrimSE or SkyrimVR.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Invalid or unselected game version.")
            return None

        # Check if xEdit path and name are available
        if not self.determined_xedit_exe_path or not self.determined_xedit_executable_name:
            self.showError("xEdit Not Configured", "xEdit executable not found or configured. Please add it to MO2's executables and restart SkyGen.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: CRITICAL: xEdit not found. Aborting generation parameter preparation.")
            return None

        xedit_script_filename = "ExportPluginData.pas"
        
        # Ensure output directory exists (needed here for validation, actual creation in __init__.py)
        if not output_folder_path.is_dir():
            try:
                output_folder_path.mkdir(parents=True, exist_ok=True)
                self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Created output directory: {output_folder_path}")
            except Exception as e:
                self.showError("Directory Creation Error", f"Failed to create output directory: {output_folder_path}\n{e}")
                self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to create output directory {output_folder_path}: {e}")
                return None

        target_plugin_filename = self._get_plugin_name_from_mod_name(target_mod_display_name, self._get_internal_mod_name_from_display_name(target_mod_display_name))
        if not target_plugin_filename:
            self.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
            self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: Target mod '{target_mod_display_name}' has no primary plugin. Aborting YAML generation parameter preparation.")
            return None

        return {
            "target_mod_display_name": target_mod_display_name,
            "source_mod_display_name": source_mod_display_name,
            "category": category,
            "keywords": keywords,
            "broad_category_swap_enabled": broad_category_swap_enabled,
            "output_folder_path": output_folder_path,
            "game_mode_flag": game_mode_flag,
            "xedit_exe_path": self.determined_xedit_exe_path,
            "xedit_executable_name": self.determined_xedit_executable_name,
            "xedit_script_filename": xedit_script_filename,
            "target_plugin_filename": target_plugin_filename,
            "generate_all": self.generate_all,
            "all_exported_target_bases_by_formid": self.all_exported_target_bases_by_formid # Pass this through
        }

    # Helper method to get internal mod name, moved from __init__.py display()
    def _get_internal_mod_name_from_display_name(self, display_name: str) -> Optional[str]:
        """
        Retrieves the internal (folder) name of a mod from its display name.
        """
        mod_list = self.wrapped_organizer.modList()
        for mod_internal_name in mod_list.allMods():
            if mod_list.displayName(mod_internal_name) == display_name:
                return mod_internal_name
        return None


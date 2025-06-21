import mobase
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QComboBox, QFileDialog, QCheckBox, QGroupBox, QRadioButton, QWidget, QSizePolicy,
    QListWidget, QListWidgetItem
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QSize
from pathlib import Path
import os
import json
from typing import Any, Optional, Union

# Import necessary functions from skygen_file_utilities
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    safe_launch_xedit,
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
)

# Import MO2_LOG_* constants from the new constants file
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
)


class OrganizerWrapper:
    """
    A wrapper class for the mobase.IOrganizer interface to handle logging.
    """
    def __init__(self, organizer: 'mobase.IOrganizer'):
        super().__init__()
        self._organizer = organizer
        self._log_file_path: Optional[Path] = None
        self._log_file_handle: Optional[Any] = None
        self._log_initialized = False
        self.dialog_instance: Optional[Any] = None # Added for logging UI errors directly


    def set_log_file_path(self, path: Path):
        self._log_file_path = path
        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._log_file_handle = open(path, 'a', encoding='utf-8')
            self._log_initialized = True
            self.log(MO2_LOG_INFO, f"SkyGen: Log file initialized at: {path}")
        except Exception as e:
            # Fallback if file logging fails
            print(f"SkyGen: ERROR: Failed to open log file {path}: {e}")
            self._log_file_handle = None
            self._log_initialized = False

    def log(self, mo2_log_level: int, message: str):
        full_message = f"[{self.get_level_name(mo2_log_level)}] {message}"
        
        # Log to custom debug file
        if self._log_file_handle and self._log_initialized:
            try:
                self._log_file_handle.write(f"{full_message}\n")
                self._log_file_handle.flush() # Ensure immediate write
            except Exception as e:
                # Fallback if writing to log file fails
                print(f"SkyGen: ERROR: Failed to write to log file: {e}")
                self._log_file_handle = None # Disable further attempts for this session
        else:
            # Fallback to console print if custom log file is not initialized
            print(full_message)


    def close_log_file(self):
        if self._log_file_handle:
            self.log(MO2_LOG_INFO, "SkyGen: Closing debug log file.")
            self._log_file_handle.close()
            self._log_file_handle = None
            self._log_initialized = False

    def get_level_name(self, level: int) -> str:
        if level == MO2_LOG_CRITICAL:
            return "CRITICAL"
        if level == MO2_LOG_ERROR:
            return "ERROR"
        if level == MO2_LOG_WARNING:
            return "WARNING"
        if level == MO2_LOG_INFO:
            return "INFO"
        if level == MO2_LOG_DEBUG:
            return "DEBUG"
        if level == MO2_LOG_TRACE:
            return "TRACE"
        return "UNKNOWN"
    
    def pluginList(self):
        try:
            return self._organizer.pluginList()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in pluginList: {e}")
            return []
    
    def getExecutables(self):
        try:
            return self._organizer.getExecutables()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in getExecutables: {e}")
            return {}
    
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

    def profilePath(self):
        """Delegates to mobase.IOrganizer.profilePath()."""
        try:
            return self._organizer.profilePath()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in profilePath: {e}")
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
    
    # NEW METHOD: currentGame
    def currentGame(self):
        """Delegates to mobase.IOrganizer.currentGame()."""
        try:
            return self._organizer.currentGame()
        except Exception as e:
            self.log(MO2_LOG_ERROR, f"Error in currentGame: {e}")
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
        @staticmethod
        def critical(parent, title, message): print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message): print(f"WARNING: {title}: {message}")
        @staticmethod
        def information(parent, title, message): print(f"INFORMATION: {title}: {message}")

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
        WindowStaysOnTopHint = 0 # Added for safety


class SkyGenToolDialog(QDialog):
    """
    The main UI dialog for the SkyGen plugin tool.
    """
    def __init__(self, wrapped_organizer: OrganizerWrapper, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.wrapped_organizer = wrapped_organizer
        self.setWindowTitle("SkyGen - Automate Your Modding!")
        self.setFixedSize(500, 600) # Fixed size for consistency
        # Make removal of context help button robust against missing Qt attribute
        if hasattr(Qt, 'WindowContextHelpButtonHint'):
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint) # Remove help button
        else:
            self.wrapped_organizer.log(2, "SkyGen: WARNING: Qt.WindowContextHelpButtonHint not found. Skipping context help button removal.")
        
        # Internal state variables
        self.selected_output_type = "SkyPatcher YAML" # Default
        self.selected_game_version = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.selected_category = ""
        self.output_folder_path = ""
        self.igpc_json_path = ""
        self.determined_xedit_exe_path: Optional[Path] = None
        self.determined_xedit_executable_name: str = ""
        self.game_root_path: Optional[Path] = None
        self.generate_all = False # For 'Generate All' checkbox state
        self.executables_dict = {} # Initialize dictionary to store executables from INI parsing
        self.pre_exported_xedit_json_path = "" # Added this as it's referenced in plugin.py


        self._setup_ui()
        self._populate_game_versions()
        self._populate_categories()
        # self._populate_mods() # REMOVED from __init__
        self._load_config() # Load saved settings


    def showEvent(self, event):
        """
        Called when the dialog is shown. We populate mods here to ensure MO2 is fully initialized.
        """
        super().showEvent(event) # Always call the base class implementation
        self.wrapped_organizer.log(0, "SkyGen: DEBUG: showEvent triggered. Populating mods now.")
        self._populate_mods() # Call _populate_mods here
        # We might want to save config here too if initial population changes selections
        # self._save_config() # Uncomment if you want to save default selections on first show


    def _setup_ui(self):
        """Sets up the layout and widgets of the dialog."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20) # Add some padding

        # --- Output Type Selection Group ---
        output_type_group = QGroupBox("Select Output Type")
        output_type_layout = QHBoxLayout()
        self.yaml_radio = QRadioButton("SkyPatcher YAML")
        self.bos_ini_radio = QRadioButton("BOS INI")
        
        self.yaml_radio.setChecked(True) # Default selection
        self.yaml_radio.toggled.connect(self._on_output_type_toggled)
        self.bos_ini_radio.toggled.connect(self._on_output_type_toggled)
        
        output_type_layout.addWidget(self.yaml_radio)
        output_type_layout.addWidget(self.bos_ini_radio)
        output_type_layout.addStretch(1) # Push radios to the left
        output_type_group.setLayout(output_type_layout)
        main_layout.addWidget(output_type_group)

        # --- General Settings Group ---
        general_settings_group = QGroupBox("General Settings")
        general_settings_layout = QVBoxLayout()

        # Game Version Radio Buttons (replacing old QComboBox)
        game_version_group = QGroupBox("Game Version")
        game_version_layout = QHBoxLayout()
        self.sse_radio = QRadioButton("SkyrimSE/AE")
        self.vr_radio = QRadioButton("SkyrimVR")
        
        self.sse_radio.toggled.connect(lambda: self._on_game_version_radio_toggled("SkyrimSE"))
        self.vr_radio.toggled.connect(lambda: self._on_game_version_radio_toggled("SkyrimVR"))

        game_version_layout.addWidget(self.sse_radio)
        game_version_layout.addWidget(self.vr_radio)
        game_version_layout.addStretch(1)
        game_version_group.setLayout(game_version_layout)
        general_settings_layout.addWidget(game_version_group)

        # Output Folder
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


        # --- SkyPatcher YAML Specific Settings Group ---
        self.yaml_settings_group = QGroupBox("SkyPatcher YAML Settings")
        yaml_settings_layout = QVBoxLayout()

        # Target Mod
        target_mod_layout = QHBoxLayout()
        target_mod_label = QLabel("Target Mod:")
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.setEditable(True)
        self.target_mod_combo.setPlaceholderText("Select the mod you are patching TO (e.g., DynDOLOD Output)")
        self.target_mod_combo.activated.connect(self._on_target_mod_selected)
        target_mod_layout.addWidget(target_mod_label)
        target_mod_layout.addWidget(self.target_mod_combo)
        yaml_settings_layout.addLayout(target_mod_layout)

        # Source Mod
        source_mod_layout = QHBoxLayout()
        source_mod_label = QLabel("Source Mod:")
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.setEditable(True)
        self.source_mod_combo.setPlaceholderText("Select the mod you are patching FROM (e.g., Enhanced Landscapes)")
        self.source_mod_combo.activated.connect(self._on_source_mod_selected)
        source_mod_layout.addWidget(source_mod_label)
        source_mod_layout.addWidget(self.source_mod_combo)
        yaml_settings_layout.addLayout(source_mod_layout)

        # Generate All Checkbox (positioned correctly)
        self.generate_all_checkbox = QCheckBox("Generate YAML for all compatible source mods (vs. selected source)")
        self.generate_all_checkbox.setChecked(False)
        self.generate_all_checkbox.stateChanged.connect(self._on_generate_all_toggled)
        yaml_settings_layout.addWidget(self.generate_all_checkbox)

        # Category Selection
        category_layout = QHBoxLayout()
        category_label = QLabel("Category (Record Type):")
        self.category_combo = QComboBox()
        self.category_combo.setPlaceholderText("e.g., STAT, TREE, GRAS")
        self.category_combo.setEditable(True) # Allow custom input
        self.category_combo.activated.connect(self._on_category_selected)
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo)
        yaml_settings_layout.addLayout(category_layout)

        # Keywords
        keywords_layout = QHBoxLayout()
        keywords_label = QLabel("Keywords (comma-separated):")
        self.keywords_lineEdit = QLineEdit()
        self.keywords_lineEdit.setPlaceholderText("Optional: e.g., pine, oak, rock")
        self.keywords_lineEdit.textChanged.connect(self._on_keywords_changed)
        keywords_layout.addWidget(keywords_label)
        keywords_layout.addWidget(self.keywords_lineEdit)
        yaml_settings_layout.addLayout(keywords_layout)
        
        # Broad Category Swap
        self.broad_category_swap_checkbox = QCheckBox("Enable Broad Category Swap (experimental)")
        self.broad_category_swap_checkbox.setChecked(False) # Default to off
        yaml_settings_layout.addWidget(self.broad_category_swap_checkbox)

        self.yaml_settings_group.setLayout(yaml_settings_layout)
        main_layout.addWidget(self.yaml_settings_group)


        # --- BOS INI Specific Settings Group ---
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
        self.bos_ini_settings_group.setVisible(False) # Hidden by default


        # --- Action Buttons ---
        button_layout = QHBoxLayout()
        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self.accept) # Accept dialog on generate
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject) # Reject dialog on cancel

        button_layout.addStretch(1) # Push buttons to the right
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        # Set size policy to preferred and expanding to allow flexible sizing
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)


    def _populate_game_versions(self):
        """
        Detects the current game and sets the appropriate radio button.
        Defaults to SkyrimSE/AE if detection fails or is not supported.
        """
        current_game_type = None
        current_game_name = "SkyrimSE" # Default to SkyrimSE if detection fails

        try:
            if hasattr(self.wrapped_organizer, 'currentGame') and self.wrapped_organizer.currentGame() is not None:
                current_game_type = self.wrapped_organizer.currentGame().type()
                if hasattr(mobase, 'GameType'):
                    if current_game_type == mobase.GameType.SSE:
                        current_game_name = "SkyrimSE"
                    elif current_game_type == mobase.GameType.SkyrimVR:
                        current_game_name = "SkyrimVR"
                    else:
                        self.wrapped_organizer.log(2, f"SkyGen: INFO: Current game type {current_game_type} not explicitly supported by SkyGen. Defaulting to SkyrimSE/AE.")
                        current_game_name = "SkyrimSE" # Fallback for unsupported MO2 GameType
                else:
                    self.wrapped_organizer.log(3, "SkyGen: WARNING: mobase.GameType not found. Assuming current game is SkyrimSE/AE for initial UI setup.")
                    current_game_name = "SkyrimSE" # Fallback if GameType enum is missing
        except Exception as e:
            self.wrapped_organizer.log(3, f"SkyGen: WARNING: Could not determine current game type from organizer: {e}. Defaulting to SkyrimSE/AE.")
            current_game_name = "SkyrimSE" # Default on error

        if current_game_name == "SkyrimSE":
            self.sse_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"
        elif current_game_name == "SkyrimVR":
            self.vr_radio.setChecked(True)
            self.selected_game_version = "SkyrimVR"
        else: # Should not happen with the default, but as a safeguard
            self.sse_radio.setChecked(True)
            self.selected_game_version = "SkyrimSE"

        self.wrapped_organizer.log(0, f"SkyGen: Initial game version set to: {self.selected_game_version} (via radio buttons).")


    def _on_game_version_radio_toggled(self, version: str):
        """Handles changes in the game version radio buttons."""
        if (version == "SkyrimSE" and self.sse_radio.isChecked()) or \
           (version == "SkyrimVR" and self.vr_radio.isChecked()):
            self.selected_game_version = version
            self.wrapped_organizer.log(0, f"SkyGen: Game version selected via radio: {self.selected_game_version}")
            self._save_config()


    def _populate_categories(self):
        """Populates the category combobox with common record types."""
        common_categories = [
            "ARMO", "WEAP", "AMMO", "MISC", "STAT", "TREE", "GRAS", "FLOR", "CONT",
            "LIGH", "CELL", "WRLD", "QUST", "SPEL", "ENCH", "COBJ", "ALCH", "BOOK",
            "KEYM", "SCRL", "SLGM", "SOUL", "LVLI", "ACTI", "APPA", "ARMA", "CCEM",
            "CSTY", "DOOR", "EFSH", "IDLE", "IMAD", "LCTN", "MGEF", "MOVE", "MSTT",
            "PMIS", "PROJ", "PWAT", "REGN", "SGST", "SMQN", "SNCT", "SNDR", "TXST",
            "VTYP", "WATR", "WRLD", "ZOOM", "GMST" # Added more common types
        ]
        self.category_combo.addItems(sorted(common_categories))
        if common_categories:
            self.selected_category = self.category_combo.currentText() # Set initial selection


    def _populate_mods(self):
        """Populates the mod comboboxes with active mods."""
        mod_list = self.wrapped_organizer.modList()
        active_mods = []
        for mod_name in mod_list.allMods():
            if mod_list.state(mod_name) & mobase.ModState.ACTIVE:
                display_name = mod_list.displayName(mod_name)
                # Attempt to get the plugin name associated with the mod
                plugin_name = self._get_plugin_name_from_mod_name(display_name, mod_name)
                if plugin_name:
                    active_mods.append(display_name)
                    self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found active mod with plugin: {display_name} ({plugin_name})")
                else:
                    self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping active mod without detectable plugin: {display_name}")

        active_mods.sort(key=str.lower) # Sort alphabetically
        
        self.target_mod_combo.clear()
        self.source_mod_combo.clear()

        # Add an empty/default option
        self.target_mod_combo.addItem("")
        self.source_mod_combo.addItem("")

        self.target_mod_combo.addItems(active_mods)
        self.source_mod_combo.addItems(active_mods)

        # Set initial selections if available
        if active_mods:
            # Attempt to set DynDOLOD Output or similar as default target
            default_target_mods = ["DynDOLOD Output", "TexGen Output", "MergePlugins", "Smashed Patch"]
            for default_mod in default_target_mods:
                if default_mod in active_mods:
                    self.target_mod_combo.setCurrentIndex(self.target_mod_combo.findText(default_mod))
                    self.selected_target_mod_name = default_mod
                    break
            
            # If no default target found, set to first mod (if any)
            if not self.selected_target_mod_name and active_mods:
                self.target_mod_combo.setCurrentIndex(1) # Skip empty string
                self.selected_target_mod_name = self.target_mod_combo.currentText()

            # For source, typically the first active mod alphabetically or specific common source
            if active_mods:
                self.source_mod_combo.setCurrentIndex(1) # Skip empty string
                self.selected_source_mod_name = self.source_mod_combo.currentText()


    def _get_plugin_name_from_mod_name(self, mod_display_name: str, mod_internal_name: str) -> Optional[str]:
        """
        Attempts to find the primary plugin file (.esp, .esm, .esl) for a given mod.
        Uses organizer.modList().mod().absolutePath() to get the mod's directory.
        """
        # Get the IMod object
        mod_obj = self.wrapped_organizer.modList().getMod(mod_internal_name) # Corrected: used wrapped_organizer
        if not mod_obj:
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Could not find IMod object for '{mod_display_name}' ({mod_internal_name}).")
            return None

        mod_path = Path(mod_obj.absolutePath()) # Use absolutePath from IMod object
        if not mod_path.is_dir():
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Mod directory for '{mod_display_name}' ({mod_internal_name}) not found at: {mod_path}.")
            return None

        # Try to find a plugin file within the mod's directory
        plugin_files = list(mod_path.glob("*.esm")) + \
                       list(mod_path.glob("*.esp")) + \
                       list(mod_path.glob("*.esl"))
        
        # Prefer plugins that exactly match the mod's internal name (case-insensitive)
        for p_file in plugin_files:
            if p_file.stem.lower() == mod_internal_name.lower():
                self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found exact plugin match for '{mod_display_name}': {p_file.name}")
                return p_file.name

        # If no exact stem match, but only one plugin file exists, use that
        if len(plugin_files) == 1:
            self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found single plugin file for '{mod_display_name}': {plugin_files[0].name}")
            return plugin_files[0].name
        elif plugin_files:
            # Fallback: if multiple plugins and no exact match, pick the first one alphabetically.
            # This might not always be correct for complex mods, but is a reasonable default.
            sorted_plugins = sorted(plugin_files, key=lambda p: p.name.lower())
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Multiple plugin files found for '{mod_display_name}' and no exact match. Picking '{sorted_plugins[0].name}'.")
            return sorted_plugins[0].name
        
        self.wrapped_organizer.log(2, f"SkyGen: WARNING: No plugin file (.esp, .esm, .esl) found for active mod '{mod_display_name}' ({mod_internal_name}).")
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
            self.generate_all_checkbox.setVisible(True) # Only show for YAML
            self.wrapped_organizer.log(0, "SkyGen: Output type set to SkyPatcher YAML.")
        elif self.bos_ini_radio.isChecked():
            self.selected_output_type = "BOS INI"
            self.yaml_settings_group.setVisible(False)
            self.bos_ini_settings_group.setVisible(True)
            self.generate_all_checkbox.setVisible(False) # Hide for BOS INI
            self.wrapped_organizer.log(0, "SkyGen: Output type set to BOS INI.")
        self._save_config() # Save setting when toggled


    def _on_target_mod_selected(self):
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Target mod selected: {self.selected_target_mod_name}")
        self._save_config()


    def _on_source_mod_selected(self):
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self.wrapped_organizer.log(0, f"SkyGen: Source mod selected: {self.selected_source_mod_name}")
        self._save_config()


    def _on_category_selected(self):
        self.selected_category = self.category_combo.currentText().upper() # Ensure uppercase
        self.wrapped_organizer.log(0, f"SkyGen: Category selected: {self.selected_category}")
        self.category_combo.setCurrentText(self.selected_category) # Update field to uppercase
        self._save_config()


    def _on_keywords_changed(self):
        self.keywords_lineEdit.setText(self.keywords_lineEdit.text().lower()) # Convert to lowercase as per Pascal script
        self._save_config() # Save on text change for keywords


    def _on_generate_all_toggled(self, state):
        self.generate_all = (state == Qt.CheckState.Checked.value)
        # Disable source mod combo if "Generate All" is checked
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
                
                # Apply settings for output type
                output_type = config.get("output_type", "SkyPatcher YAML")
                if output_type == "SkyPatcher YAML":
                    self.yaml_radio.setChecked(True)
                else:
                    self.bos_ini_radio.setChecked(True)
                self._on_output_type_toggled() # Trigger visibility update
                
                # Apply general settings
                loaded_game_version = config.get("game_version", "SkyrimSE")
                if loaded_game_version == "SkyrimSE":
                    self.sse_radio.setChecked(True)
                elif loaded_game_version == "SkyrimVR":
                    self.vr_radio.setChecked(True)
                self.selected_game_version = loaded_game_version # Ensure internal state is set


                self.output_folder_lineEdit.setText(config.get("output_folder_path", str(Path(self.wrapped_organizer.basePath()) / "overwrite")))
                self.output_folder_path = self.output_folder_lineEdit.text()

                # Apply YAML settings
                self.target_mod_combo.setCurrentIndex(
                    self.target_mod_combo.findText(config.get("target_mod_name", ""))
                )
                # MODIFIED: Changed find() to findText() for source_mod_combo
                self.source_mod_combo.setCurrentIndex(
                    self.source_mod_combo.findText(config.get("source_mod_name", ""))
                )
                self.category_combo.setCurrentIndex(
                    self.category_combo.findText(config.get("category", ""))
                )
                self.keywords_lineEdit.setText(config.get("keywords", ""))
                self.broad_category_swap_checkbox.setChecked(config.get("broad_category_swap_enabled", False))
                self.generate_all_checkbox.setChecked(config.get("generate_all", False))

                # Apply BOS INI settings
                self.igpc_json_lineEdit.setText(config.get("igpc_json_path", ""))
                self.igpc_json_path = self.igpc_json_lineEdit.text()

                # Load xedit paths if they exist
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
            "game_version": self.selected_game_version, # MODIFIED: Use selected_game_version
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
            # Ensure the directory exists before writing
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

    def _generate_skypatcher_yaml_internal(self):
        """
        Internal method to handle the SkyPatcher YAML generation logic.
        This method is called by the display() method in __init__.py.
        """
        self.wrapped_organizer.log(1, "SkyGen: Starting SkyPatcher YAML generation (internal).")

        target_mod_display_name = self.selected_target_mod_name
        source_mod_display_name = self.selected_source_mod_name
        category = self.selected_category
        keywords_str = self.keywords_lineEdit.text().strip()
        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
        broad_category_swap_enabled = self.broad_category_swap_checkbox.isChecked()
        output_folder_path = Path(self.output_folder_path)

        if not target_mod_display_name:
            self.showError("Input Error", "Please select a Target Mod.")
            self.wrapped_organizer.log(3, "SkyGen: Target Mod not selected. Aborting YAML generation.")
            return

        if not category:
            self.showError("Input Error", "Please select or enter a Category (Record Type).")
            self.wrapped_organizer.log(3, "SkyGen: Category not selected. Aborting YAML generation.")
            return

        # Determine game mode flag for xEdit (e.g., -SE, -VR)
        game_mode_flag = ""
        if self.selected_game_version == "SkyrimSE":
            game_mode_flag = "SE"
        elif self.selected_game_version == "SkyrimVR":
            game_mode_flag = "VR"
        else:
            self.showError("Game Version Error", "Could not determine game version. Please select SkyrimSE/AE or SkyrimVR.")
            self.wrapped_organizer.log(4, "SkyGen: ERROR: Invalid or unselected game version.")
            return

        # Check if xEdit path and name are available
        if not self.determined_xedit_exe_path or not self.determined_xedit_executable_name:
            self.showError("xEdit Not Configured", "xEdit executable not found or configured. Please add it to MO2's executables and restart SkyGen.")
            self.wrapped_organizer.log(4, "SkyGen: CRITICAL: xEdit not found. Aborting generation.")
            return

        xedit_script_filename = "ExportPluginData.pas" # Pascal script name
        xedit_ini_filename = "ExportPluginData.ini" # INI file name for Pascal script

        # Ensure output directory exists
        if not output_folder_path.is_dir():
            try:
                output_folder_path.mkdir(parents=True, exist_ok=True)
                self.wrapped_organizer.log(1, f"SkyGen: Created output directory: {output_folder_path}")
            except Exception as e:
                self.showError("Directory Creation Error", f"Failed to create output directory: {output_folder_path}\n{e}")
                self.wrapped_organizer.log(4, f"SkyGen: ERROR: Failed to create output directory {output_folder_path}: {e}")
                return

        # Get plugin name for the target mod
        target_plugin_filename = self._get_plugin_name_from_mod_name(target_mod_display_name, self._get_internal_mod_name_from_display_name(target_mod_display_name))
        if not target_plugin_filename:
            self.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
            self.wrapped_organizer.log(3, f"SkyGen: Target mod '{target_mod_display_name}' has no primary plugin. Aborting YAML generation.")
            return

        # Export ALL data from the Target Mod first (only once)
        self.wrapped_organizer.log(1, f"SkyGen: Exporting all data from Target Mod '{target_mod_display_name}'...")
        
        target_export_script_options = {
            "TargetPlugin": target_plugin_filename,
            "TargetCategory": "", # Empty string to export all categories
            "Keywords": "",
            "BroadCategorySwap": "false"
        }

        xedit_output_path_target_all = safe_launch_xedit(
            self.wrapped_organizer, # organizer (CORRECTED to pass OrganizerWrapper)
            self, # dialog
            self.determined_xedit_exe_path, # xedit_path
            self.determined_xedit_executable_name, # xedit_mo2_name
            xedit_script_filename, # script_name
            game_mode_flag, # game_mode_flag
            self.selected_game_version, # game_version (CORRECTED)
            target_export_script_options, # script_options
            self.wrapped_organizer.log # debug_logger
        )
        
        if not xedit_output_path_target_all:
            self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export target mod data. Aborting YAML generation.")
            self.showError("xEdit Export Failed", "Failed to export data from the Target Mod. Check xEdit logs for details.")
            return

        target_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_target_all, "Target Mod xEdit Export", self)
        
        # Clean up the output JSON from target export after loading
        try:
            xedit_output_path_target_all.unlink()
            self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up target export JSON: {xedit_output_path_target_all}")
        except Exception as e:
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete target export JSON '{xedit_output_path_target_all}': {e}")


        if not target_exported_json or "baseObjects" not in target_exported_json:
            self.wrapped_organizer.log(3, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
            self.showError("JSON Parse Error", "Target mod xEdit export JSON is empty or malformed. Cannot proceed with YAML generation.")
            return
        
        # This will be used in generate_and_write_skypatcher_yaml to find target FormIDs for broad category swap
        self.all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in target_exported_json.get("baseObjects", []) if "FormID" in obj}


        if self.generate_all:
            self.wrapped_organizer.log(1, "SkyGen: 'Generate All' selected. Processing all compatible source mods.")
            all_mods = self.wrapped_organizer.modList().allMods() # Corrected: used wrapped_organizer
            successful_generations = 0
            
            # Filter out target mod and game master files from source mods for 'all' generation
            source_mods_to_process = []
            for mod_name_internal in all_mods:
                if self.wrapped_organizer.modList().state(mod_name_internal) & mobase.ModState.ACTIVE: # Corrected: used wrapped_organizer
                    mod_display_name = self.wrapped_organizer.modList().displayName(mod_name_internal) # Corrected: used wrapped_organizer
                    if mod_display_name == target_mod_display_name: # Don't process target mod as source
                        continue
                    
                    # Exclude master files (.esm, .esl) as sources unless specifically requested
                    source_plugin_candidate = self._get_plugin_name_from_mod_name(mod_display_name, mod_name_internal)
                    if source_plugin_candidate and not (source_plugin_candidate.lower().endswith(".esm") or source_plugin_candidate.lower().endswith(".esl")):
                        source_mods_to_process.append((mod_display_name, mod_name_internal, source_plugin_candidate))
                    else:
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping mod '{mod_display_name}' (internal: {mod_name_internal}) as it's a master file or has no main plugin.")

            if not source_mods_to_process:
                self.showWarning("No Source Mods", "No suitable source mods found for 'Generate All'. Skipping.")
                self.wrapped_organizer.log(2, "SkyGen: No suitable source mods found for 'Generate All'.")
                return

            self.showInformation("Starting Batch Generation", f"Generating YAMLs for compatible source mods against target mod '{target_mod_display_name}' for category '{category}'. This may take some time...")

            for current_source_mod_display_name, current_source_mod_internal_name, source_mod_plugin_filename in source_mods_to_process:
                self.wrapped_organizer.log(1, f"SkyGen: Processing source mod: '{current_source_mod_display_name}' ({source_mod_plugin_filename})...")
                
                source_export_script_options = {
                    "TargetPlugin": source_mod_plugin_filename, # This is the plugin we're extracting data FROM
                    "TargetCategory": category,
                    "Keywords": ','.join(keywords),
                    "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                }
                
                # Run xEdit export for the current source mod and specific category
                xedit_output_path_source = safe_launch_xedit(
                    self.wrapped_organizer, # organizer (CORRECTED to pass OrganizerWrapper)
                    self, # dialog
                    self.determined_xedit_exe_path,
                    self.determined_xedit_executable_name,
                    xedit_script_filename,
                    game_mode_flag,
                    self.selected_game_version, # game_version (CORRECTED)
                    source_export_script_options, # script_options
                    self.wrapped_organizer.log # debug_logger
                )
                
                if xedit_output_path_source:
                    source_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {current_source_mod_display_name}", dialog_instance=self)
                    
                    # Clean up the output JSON from source export after loading
                    try:
                        xedit_output_path_source.unlink()
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                    except Exception as e:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
                    
                    if source_exported_json and "baseObjects" in source_exported_json:
                        generated = generate_and_write_skypatcher_yaml(
                            wrapped_organizer=self.wrapped_organizer,
                            json_data=source_exported_json, # Pass the entire json_data with 'baseObjects'
                            target_mod_name=target_mod_display_name, # This is display name, will be converted internally in generate_and_write_skypatcher_yaml
                            output_folder_path=output_folder_path,
                            record_type=category,
                            broad_category_swap_enabled=broad_category_swap_enabled,
                            search_keywords=keywords # Pass as list
                        )
                        if generated:
                            successful_generations += 1
                    else:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: xEdit export JSON for '{current_source_mod_display_name}' is empty or malformed. Skipping YAML generation.")
                else:
                    self.wrapped_organizer.log(3, f"SkyGen: ERROR: xEdit export failed for source mod '{current_source_mod_display_name}'. Skipping YAML generation.")

            self.showInformation("Batch Generation Complete", f"Successfully generated {successful_generations} YAML file(s).")
            self.wrapped_organizer.log(1, f"SkyGen: Batch YAML generation complete. {successful_generations} files generated.")

        else: # Single YAML Generation
            if not source_mod_display_name:
                self.showError("Input Error", "Please select a Source Mod for single YAML generation.")
                self.wrapped_organizer.log(3, "SkyGen: Source Mod not selected for single YAML generation.")
                return

            self.wrapped_organizer.log(1, f"SkyGen: Generating single YAML for '{source_mod_display_name}' targeting '{target_mod_display_name}' for category '{category}'...")

            # Get plugin name for the source mod
            source_plugin_filename = self._get_plugin_name_from_mod_name(source_mod_display_name, self._get_internal_mod_name_from_display_name(source_mod_display_name))
            if not source_plugin_filename:
                self.showError("Source Mod Error", f"Could not determine plugin file for source mod '{source_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
                self.wrapped_organizer.log(3, f"SkyGen: Source mod '{source_mod_display_name}' has no primary plugin. Aborting YAML generation.")
                return

            # 2. Export data from the Source Mod for the specific category
            self.wrapped_organizer.log(1, f"SkyGen: Exporting data from Source Mod: {source_mod_display_name} for category {category}...")
            
            source_export_script_options = {
                "TargetPlugin": source_plugin_filename, # This is the plugin we're extracting data FROM
                "TargetCategory": category,
                "Keywords": ','.join(keywords),
                "BroadCategorySwap": str(broad_category_swap_enabled).lower()
            }

            xedit_output_path_source = safe_launch_xedit(
                self.wrapped_organizer, # organizer (CORRECTED to pass OrganizerWrapper)
                self, # dialog
                self.determined_xedit_exe_path,
                self.determined_xedit_executable_name,
                xedit_script_filename,
                game_mode_flag,
                self.selected_game_version, # game_version (CORRECTED)
                source_export_script_options, # script_options
                self.wrapped_organizer.log # debug_logger
            )
            
            if not xedit_output_path_source:
                self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export source mod data. Aborting YAML generation.")
                self.showError("xEdit Export Failed", "Failed to export data from the Source Mod. Check xEdit logs for details.")
                return

            source_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {source_mod_display_name}", dialog_instance=self)
            
            # Clean up the output JSON from source export after loading
            try:
                xedit_output_path_source.unlink()
                self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
            except Exception as e:
                self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
            
            if not source_exported_json or "baseObjects" not in source_exported_json:
                self.wrapped_organizer.log(3, "SkyGen: ERROR: Source mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                self.showError("JSON Parse Error", "Source mod xEdit export JSON is empty or malformed. Cannot generate YAML.")
                return

            # 3. Generate and write the YAML
            generate_and_write_skypatcher_yaml(
                wrapped_organizer=self.wrapped_organizer,
                json_data=source_exported_json, # Pass the entire json_data with 'baseObjects'
                target_mod_name=target_mod_display_name,
                output_folder_path=output_folder_path,
                record_type=category,
                broad_category_swap_enabled=broad_category_swap_enabled,
                search_keywords=keywords # Pass as list
            )

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


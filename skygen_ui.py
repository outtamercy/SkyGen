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
from typing import Any, Optional, Union, TextIO
from datetime import datetime

MO2_LOG_CRITICAL = 5
MO2_LOG_ERROR = 4
MO2_LOG_WARNING = 3
MO2_LOG_INFO = 2
MO2_LOG_DEBUG = 1
MO2_LOG_TRACE = 0

class OrganizerWrapper:
    """
    A wrapper class for the mobase.IOrganizer interface to handle logging.
    """
    def __init__(self, organizer: 'mobase.IOrganizer'):
        self._organizer = organizer
        self._log_file_path: Optional[Path] = None
        self._log_file_handle: Optional[TextIO] = None # Type hint for file handle
        # self._log_initialized = False # This flag is no longer strictly needed with the new set_log_file_path logic

    def set_log_file_path(self, path: Path):
        """
        Sets the path for the debug log file and attempts to open it.
        Closes any existing file handle before opening a new one.
        """
        if self._log_file_handle:
            try:
                self._log_file_handle.close()
                self.log(MO2_LOG_DEBUG, "SkyGen: DEBUG: Closed previous log file handle.") # CHANGED: self._organizer.log -> self.log
            except Exception as e:
                self.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to close old log file handle: {e}") # CHANGED: self._organizer.log -> self.log
        
        self._log_file_path = path
        try:
            # Ensure parent directory exists before opening the file
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file_handle = open(path, 'a', encoding='utf-8')
            self.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Opened debug log file: {path}") # CHANGED: self._organizer.log -> self.log
        except Exception as e:
            self.log(MO2_LOG_CRITICAL, f"SkyGen: CRITICAL: Could not open debug log file: {path}: {e}") # CHANGED: self._organizer.log -> self.log
            self._log_file_handle = None

    def log(self, level: int, message: str):
        """
        Logs a message to MO2's main log pane and to the custom debug log file.
        """
        self._organizer.log(level, message) # Log to MO2's main log pane

        if self._log_file_handle:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                level_name = {
                    MO2_LOG_TRACE: "TRACE",
                    MO2_LOG_DEBUG: "DEBUG",
                    MO2_LOG_INFO: "INFO",
                    MO2_LOG_WARNING: "WARNING",
                    MO2_LOG_ERROR: "ERROR",
                    MO2_LOG_CRITICAL: "CRITICAL"
                }.get(level, "UNKNOWN")
                self._log_file_handle.write(f"[{timestamp} {level_name}] {message}\n")
                self._log_file_handle.flush() # NEW: Force write to disk immediately
            except Exception as e:
                self._organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write to SkyGen_Debug.log: {e}")

    def close_log_file(self):
        """
        Closes the custom debug log file if it's open.
        """
        if self._log_file_handle:
            try:
                self._log_file_handle.close()
                self._log_file_handle = None
                self.log(MO2_LOG_DEBUG, "SkyGen: DEBUG: SkyGen_Debug.log file closed successfully.") # CHANGED: self._organizer.log -> self.log
            except Exception as e:
                self.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to close SkyGen_Debug.log: {e}") # CHANGED: self._organizer.log -> self.log

    # The _open_log_file method in OrganizerWrapper is now handled by set_log_file_path
    # This method is effectively removed as it's no longer necessary.

    def get_level_name(self, level: int) -> str:
        """Returns the string name for a given log level."""
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

    def gameInfo(self):
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
        pass

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
        self.executables_dict = {} # ADDED: Initialize dictionary to store executables from INI parsing
        self.pre_exported_xedit_json_path = "" # Added this as it's referenced in plugin.py


        self._setup_ui()
        self._populate_game_versions()
        self._populate_categories()
        self._populate_mods()
        self._load_config() # Load saved settings


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

        # Game Version
        game_version_layout = QHBoxLayout()
        game_version_label = QLabel("Game Version:")
        self.game_version_combo = QComboBox()
        self.game_version_combo.currentIndexChanged.connect(self._on_game_version_selected)
        game_version_layout.addWidget(game_version_label)
        game_version_layout.addWidget(self.game_version_combo)
        general_settings_layout.addLayout(game_version_layout)

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
        """Populates the game version combobox with only supported game types (SkyrimSE, SkyrimVR).
        This version is robust against mobase.GameType not being available during early plugin load.
        """
        supported_games_map = {}
        
        # Check if mobase.GameType is available. If not, use hardcoded strings directly.
        if hasattr(mobase, 'GameType'):
            self.wrapped_organizer.log(0, "SkyGen: DEBUG: mobase.GameType found. Using mobase enum values.")
            supported_games_map[mobase.GameType.SSE] = "SkyrimSE"
            supported_games_map[mobase.GameType.SkyrimVR] = "SkyrimVR"
        else:
            self.wrapped_organizer.log(3, "SkyGen: WARNING: mobase.GameType not found. Using hardcoded game versions as fallback.")
            # If GameType enum is not available, default to common names with arbitrary keys
            supported_games_map[0] = "SkyrimSE" # Using 0 and 1 as arbitrary keys for the map
            supported_games_map[1] = "SkyrimVR"
            
        current_game_type = None
        # Safely attempt to get the current game type from the organizer using currentGame()
        try:
            # MODIFIED: Changed from gameInfo().type() to currentGame().type()
            if hasattr(self.wrapped_organizer, 'currentGame') and self.wrapped_organizer.currentGame() is not None and hasattr(self.wrapped_organizer.currentGame(), 'type'):
                current_game_type = self.wrapped_organizer.currentGame().type()
        except Exception as e:
            self.wrapped_organizer.log(3, f"SkyGen: WARNING: Could not determine current game type from organizer: {e}. Defaulting to no specific current game.")

        self.game_version_combo.clear()
        
        # Logic to add current game first, if it's supported and detectable
        current_game_name = supported_games_map.get(current_game_type)
        
        if current_game_name:
            self.game_version_combo.addItem(current_game_name)
            self.selected_game_version = current_game_name
            
            # Add other supported games, excluding the one already added
            other_game_names = [name for key, name in supported_games_map.items() if name != current_game_name]
            self.game_version_combo.addItems(sorted(other_game_names))
        else:
            # If current game is not supported or could not be determined, just add all sorted supported games
            sorted_names = sorted(supported_games_map.values())
            self.game_version_combo.addItems(sorted_names)
            if sorted_names:
                self.selected_game_version = self.game_version_combo.currentText() # Set initial selection to first item
        
        self.wrapped_organizer.log(0, f"SkyGen: Populated game versions: {self.game_version_combo.currentText()}")


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
        # MODIFIED: Changed to use wrapped_organizer._organizer.modList().getMod()
        mod_obj = self.wrapped_organizer._organizer.modList().getMod(mod_internal_name) 
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


    def _on_game_version_selected(self):
        self.selected_game_version = self.game_version_combo.currentText()
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
        # MODIFIED: Changed from pluginDataPath() to basePath() / "plugins"
        return Path(self.wrapped_organizer.basePath()) / "plugins" / "SkyGen" / "config.json"


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
                self.game_version_combo.setCurrentIndex(
                    self.game_version_combo.findText(config.get("game_version", self.game_version_combo.currentText()))
                )
                
                self.output_folder_lineEdit.setText(config.get("output_folder_path", str(Path(self.wrapped_organizer.basePath()) / "overwrite")))
                self.output_folder_path = self.output_folder_lineEdit.text()

                # Apply YAML settings
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
            "game_version": self.game_version_combo.currentText(),
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

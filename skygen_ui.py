from pathlib import Path
import mobase
import os
import json
import yaml
import configparser # Although not directly used in the moved classes, it's a common dependency for related functions
import re           # Although not directly used in the moved classes, it's a common dependency for related functions
import time
from collections import defaultdict
from typing import Optional, Any
import traceback # Import traceback for error logging

# Import utility functions used by UI classes
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    write_pas_script_to_xedit,
    clean_temp_script_and_ini,
    get_game_root_from_general_ini # Added to ensure it's imported if needed by UI
)

# Ensure necessary PyQt6 modules are imported correctly or dummy classes are defined
try:
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QComboBox,
        QMessageBox,
        QButtonGroup,
        QWidget,
        QSizePolicy,
        QFileDialog,
        QCheckBox,
        QRadioButton,
        QListWidget, # <--- ADDED
        QListWidgetItem # <--- ADDED
    )
    from PyQt6.QtCore import Qt, QCoreApplication
    from PyQt6.QtGui import QIcon
except ImportError:
    print("One or more required PyQt modules are not installed. Please ensure PyQt6 is installed.")
    # Define dummy classes/functions to prevent hard crashes if PyQt6 is missing
    class QDialog:
        def __init__(self, *args, **kwargs): pass
        def exec(self): return 0
        def reject(self): pass
        def accept(self): pass
        def close(self): pass
        def show(self): pass
        def hide(self): pass
        def showInformation(self, title, message): print(f"INFO: {title}: {message}")
        def showWarning(self, title, message): print(f"WARN: {title}: {message}")
        def showError(self, title, message): print(f"ERROR: {title}: {message}")
        def setText(self, text): pass
        def text(self): return ""

    class QApplication:
        def __init__(self, *args, **kwargs): pass
        def instance(self): return None
        def exec(self): return 0
    class QVBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addWidget(self, widget): pass
        def addLayout(self, layout): pass
        def addStretch(self, stretch): pass
    class QHBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addWidget(self, widget): pass
        def addLayout(self, layout): pass
        def addStretch(self, stretch): pass
    class QLabel:
        def __init__(self, *args, **kwargs): pass
        def setText(self, text): pass
        def text(self): return ""
    class QLineEdit:
        def __init__(self, *args, **kwargs): pass
        def setText(self, text): pass
        def text(self): return ""
        def setReadOnly(self, read_only): pass
    class QPushButton:
        def __init__(self, *args, **kwargs): pass
        class clicked:
            def connect(self, func): pass
    class QComboBox:
        def __init__(self, *args, **kwargs): pass
        def clear(self): pass
        def addItems(self, items): pass
        def currentText(self): return ""
        def currentIndex(self): return -1
        def setCurrentIndex(self, index): pass
        class currentIndexChanged:
            def connect(self, func): pass
    class QMessageBox:
        @staticmethod
        def critical(parent, title, message): print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message): print(f"WARNING: {title}: {message}")
        @staticmethod
        def information(parent, title, message): print(f"INFORMATION: {title}: {message}")
    class QButtonGroup:
        def __init__(self, *args, **kwargs): pass
        def addButton(self, button): pass
        def checkedButton(self): return None
    class QWidget:
        def __init__(self, *args, **kwargs): pass
        def setLayout(self, layout): pass
        def setSizePolicy(self, h_policy, v_policy): pass
    class QSizePolicy:
        Fixed = 0
        Expanding = 1
        Preferred = 2
        Minimum = 3
        Maximum = 4
        Ignored = 5
        Stretch = 1
        def __init__(self, h_policy, v_policy): pass
    class QFileDialog:
        @staticmethod
        def getOpenFileName(parent, caption, directory, filter): return "",""
        @staticmethod
        def getExistingDirectory(parent, caption, directory): return ""
    class QCheckBox:
        def __init__(self, *args, **kwargs): pass
        def isChecked(self): return False
        class stateChanged:
            def connect(self, func): pass
        def setChecked(self, checked): pass
    class QRadioButton:
        def __init__(self, *args, **kwargs): pass
        def isChecked(self): return False
        class clicked:
            def connect(self, func): pass
    class QListWidget:
        def __init__(self, *args, **kwargs): pass
        def clear(self): pass
        def addItems(self, items): pass
        def selectedItems(self): return []
        class itemSelectionChanged:
            def connect(self, func): pass
    class QListWidgetItem:
        def __init__(self, *args, **kwargs): pass
    class QCoreApplication:
        @staticmethod
        def applicationDirPath(): return ""

    class Qt:
        SolidLine = 0
        NoButton = 0
        Checked = 2 # Dummy for QCheckBox.stateChanged
        Unchecked = 0 # Dummy for QCheckBox.stateChanged


class OrganizerWrapper:
    """
    A wrapper class for mobase.IOrganizer to provide logging and
    centralized access to MO2 functionalities for UI components,
    and to allow setting a custom log file path.
    """
    def __init__(self, organizer: mobase.IOrganizer):
        self._organizer = organizer
        self._log_file_path: Optional[Path] = None
        self._log_file = None

    def set_log_file_path(self, log_file_path: Path):
        """Sets the path for the custom log file."""
        self._log_file_path = log_file_path
        self._open_log_file() # Open/reopen the log file with the new path

    def _open_log_file(self):
        """Opens or reopens the custom log file."""
        if self._log_file:
            self._log_file.close()
        if self._log_file_path:
            # Changed "a" (append) to "w" (write, which truncates)
            self._log_file = open(self._log_file_path, "w", encoding="utf-8")
        else:
            self._log_file = None # Ensure it's None if no path set

    def log(self, level: int, message: str):
        """
        Logs a message to MO2's log and optionally to a custom file.
        Levels: 0 (debug), 1 (info), 2 (warning), 3 (error), 4 (critical)
        """
        log_map = {
            0: 0,    # Maps to mobase Debug level
            1: 1,    # Maps to mobase Info level
            2: 2,    # Maps to mobase Warning level
            3: 3,    # Maps to mobase Error level
            4: 4     # Maps to mobase Critical level
        }
        mo2_log_level = log_map.get(level, 1) # Default to 1 (Info) if level is unknown
        
        full_message = f"SkyGen (Level {mo2_log_level}): {message}" 
        
        # The line self._organizer.log(mo2_log_level, message) is now completely absent.
        # This means no messages will be logged directly to MO2's main console via this wrapper's log method.
        # All messages will still be written to the custom log file.
        
        if self._log_file:
            self._log_file.write(full_message + "\n")
            self._log_file.flush() # Ensure message is written immediately

    def close_log_file(self):
        """Closes the custom log file."""
        if self._log_file:
            self.log(0, "SkyGen: Closing custom log file.")
            self._log_file.close()
            self._log_file = None

    # Passthrough methods for mobase.IOrganizer functionality
    def basePath(self) -> str:
        return self._organizer.basePath()

    def pluginDataPath(self) -> str:
        return self._organizer.pluginDataPath()

    def modList(self) -> mobase.IModList:
        return self._organizer.modList()

    def pluginList(self) -> mobase.IPluginList:
        return self._organizer.pluginList()
    
    def getExecutables(self) -> list[mobase.ExecutableInfo]:
        """
        Attempts to retrieve the list of executables from IOrganizer.
        Handles AttributeError if getExecutables is not available on this MO2 version.
        """
        try:
            # Attempt to call the method on the actual organizer object
            executables = self._organizer.getExecutables()
            self.log(0, f"SkyGen: DEBUG: Successfully retrieved {len(executables)} executables from MO2.")
            return executables
        except AttributeError:
            self.log(3, "SkyGen: ERROR: mobase.IOrganizer object has no attribute 'getExecutables' in this MO2 version. Cannot auto-detect executables from MO2's list.")
            self.log(2, "SkyGen: WARNING: Falling back to config.json for xEdit path or requiring manual entry.")
            return [] # Return an empty list if the method doesn't exist
        except Exception as e:
            self.log(3, f"SkyGen: ERROR: Unexpected error getting executables from MO2: {e}\n{traceback.format_exc()}")
            return []


    def startApplication(self, binary: str, args: list[str], workingDirectory: str) -> Any:
        return self._organizer.startApplication(binary, args, workingDirectory)

    def resolvePath(self, path: str) -> str:
        return self._organizer.resolvePath(path)


class SkyGenToolDialog(QDialog):
    """
    The main UI dialog for the SkyGen tool.
    Handles user interaction, path selection, and triggers generation processes.
    """
    def __init__(self, organizer_wrapper: OrganizerWrapper):
        super().__init__()
        self._organizer_wrapper = organizer_wrapper
        self.setWindowTitle("SkyGen Tool")
        self.setMinimumSize(700, 500) # Increased minimum size for better layout

        self.categories_data = {} # To store data from categories.json
        self.output_folder_path = "" # Path where outputs will be saved (e.g., MO2 overwrite)
        self.selected_category = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.selected_game_version = "SkyrimSE" # Default
        self.selected_output_type = "SkyPatcher YAML" # Default
        self.generate_all = False # Flag for single or all generation

        # Properties to store determined paths/names from the plugin's display method
        self.determined_xedit_executable_name = ""
        self.determined_xedit_exe_path = Path("")
        self.game_root_path = Path("") # Initialize game root path

        # Paths initialized from config in _load_config
        self.igpc_json_path = ""
        self.pre_exported_xedit_json_path = ""
        # self.full_export_script_path = Path("H:/Truth Special Edition/tools/SSEEdit/Edit Scripts/ExportPluginData.pas") # Default, overridden by config - REMOVED

        # Call _init_ui first to create widgets before _load_config tries to set their text
        self._init_ui() 
        self._load_config() # This will load values from config.json and now populate UI fields

        # Connect signals and slots
        self.category_combo.currentIndexChanged.connect(self._update_category)
        self.target_mod_combo.currentIndexChanged.connect(self._on_target_mod_selected)
        self.source_mod_combo.currentIndexChanged.connect(self._on_source_mod_selected)
        self.generate_single_btn.clicked.connect(self._on_generate_single_clicked)
        self.generate_all_btn.clicked.connect(self._on_generate_all_clicked)
        self.cancel_btn.clicked.connect(self.reject)
        
        # Connect output type radio buttons
        self.skypatcher_radio.clicked.connect(self._on_output_type_toggled)
        self.bos_ini_radio.clicked.connect(self._on_output_type_toggled)

        # Connect game version radio buttons
        self.skyrimse_radio.clicked.connect(self._on_game_version_toggled)
        self.skyrimvr_radio.clicked.connect(self._on_game_version_toggled) # Connect this if adding VR

        # Connect broad category swap checkbox if it exists
        if hasattr(self, 'broad_category_swap_checkbox'):
            self.broad_category_swap_checkbox.stateChanged.connect(self._on_broad_category_swap_changed)

        # Initial UI state setup (now called AFTER _load_config populates selected_output_type)
        self._on_output_type_toggled() 

        # Initial population of mod lists and categories (no need to set text fields here anymore)
        self._populate_mod_combos()
        self._populate_categories()

    def _load_config(self):
        """
        Loads configuration from config.json and populates UI fields.
        """
        config_file_path = Path(__file__).parent / "config.json"
        if not config_file_path.is_file():
            self._organizer_wrapper.log(2, f"SkyGen: WARNING: config.json not found at {config_file_path}. Using default settings.")
            # Set default values for paths if config.json doesn't exist
            self.output_folder_path = str(Path(self._organizer_wrapper._organizer.overwritePath())) # Corrected access
            # self.full_export_script_path = Path("H:/Truth Special Edition/tools/SSEEdit/Edit Scripts/ExportPluginData.pas") # REMOVED
            self.igpc_json_path = ""
            self.pre_exported_xedit_json_path = ""
            # Set default UI values here too if config is not loaded
            if hasattr(self, 'igpc_path_lineEdit'): # Ensure widgets exist before setting text
                self.igpc_path_lineEdit.setText(self.igpc_json_path)
                self.xedit_json_lineEdit.setText(self.pre_exported_xedit_json_path)
                self.output_folder_lineEdit.setText(self.output_folder_path)
                # self.xedit_script_path_lineEdit.setText(str(self.full_export_script_path)) # REMOVED
            return

        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            # Load paths, ensuring they are Path objects (or strings for JSON line edits)
            self.igpc_json_path = config_data.get("igpc_json_path", "")
            self.pre_exported_xedit_json_path = config_data.get("pre_exported_xedit_json_path", "")
            # self.full_export_script_path = Path(config_data.get("full_export_script_path", "H:/Truth Special Edition/tools/SSEEdit/Edit Scripts/ExportPluginData.pas")) # Default - REMOVED
            self.output_folder_path = config_data.get("output_folder_path", str(Path(self._organizer_wrapper._organizer.overwritePath()))) # Corrected access # Default to overwrite

            # Load other settings
            self.selected_game_version = config_data.get("selected_game_version", "SkyrimSE")
            
            # Set radio button based on loaded config
            if self.selected_game_version == "SkyrimSE":
                self.skyrimse_radio.setChecked(True)
            elif self.selected_game_version == "SkyrimVR": # For Skyrim VR
                self.skyrimvr_radio.setChecked(True)

            self.selected_output_type = config_data.get("selected_output_type", "SkyPatcher YAML")
            self.plugin_disambiguation_map = config_data.get("plugin_disambiguation_map", {})

            # Populate initial values into UI fields after loading config
            # These lines were moved from __init__
            self.igpc_path_lineEdit.setText(self.igpc_json_path)
            self.xedit_json_lineEdit.setText(self.pre_exported_xedit_json_path)
            self.output_folder_lineEdit.setText(self.output_folder_path)
            # self.xedit_script_path_lineEdit.setText(str(self.full_export_script_path)) # REMOVED

            # Log successful loading
            self._organizer_wrapper.log(1, f"SkyGen: Configuration loaded from {config_file_path}")

        except json.JSONDecodeError as e:
            self._organizer_wrapper.log(3, f"SkyGen: ERROR: Error decoding config.json: {e}. Please check file syntax.")
            self.showError("Config Error", f"Error reading config.json: {e}. Please ensure it's valid JSON.")
        except IOError as e:
            self._organizer_wrapper.log(3, f"SkyGen: ERROR: I/O error reading config.json: {e}.")
            self.showError("Config Error", f"I/O error reading config.json: {e}.")
        except Exception as e:
            self._organizer_wrapper.log(3, f"SkyGen: ERROR: Unexpected error loading config.json: {e}\n{traceback.format_exc()}")
            self.showError("Config Error", f"An unexpected error occurred while loading config.json: {e}")

    def _save_config(self):
        """
        Saves current settings to config.json.
        """
        config_file_path = Path(__file__).parent / "config.json"
        config_data = {
            "igpc_json_path": self.igpc_path_lineEdit.text().strip(),
            "pre_exported_xedit_json_path": self.xedit_json_lineEdit.text().strip(),
            # "full_export_script_path": str(self.full_export_script_path), # Ensure it's a string for JSON - REMOVED
            "output_folder_path": self.output_folder_lineEdit.text().strip(),
            "selected_game_version": self.selected_game_version,
            "selected_output_type": self.selected_output_type,
            "plugin_disambiguation_map": self.plugin_disambiguation_map,
            # Add these two lines to save xEdit paths:
            "xedit_exe_path": str(self.determined_xedit_exe_path), # Ensure it's a string
            "xedit_mo2_name": self.determined_xedit_executable_name
        }
        try:
            with open(config_file_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4)
            self._organizer_wrapper.log(1, f"SkyGen: Configuration saved to {config_file_path}")
        except Exception as e:
            self._organizer_wrapper.log(3, f"SkyGen: ERROR: Failed to save config.json: {e}\n{traceback.format_exc()}")
            self.showWarning("Save Error", f"Failed to save configuration: {e}. Settings may not persist.")


    def _init_ui(self):
        """Initializes the dialog's user interface elements."""
        main_layout = QVBoxLayout()

        # Output Type Selection
        output_type_group_box_layout = QVBoxLayout()
        output_type_group_box = QWidget()
        output_type_group_box.setLayout(output_type_group_box_layout)
        output_type_group_box.setStyleSheet("QGroupBox { border: 1px solid gray; border-radius: 5px; margin-top: 1ex; } QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; }")

        output_type_label = QLabel("Select Output Type:")
        output_type_group_box_layout.addWidget(output_type_label)

        self.output_type_button_group = QButtonGroup(self)
        self.skypatcher_radio = QRadioButton("SkyPatcher YAML")
        self.bos_ini_radio = QRadioButton("BOS INI")

        output_type_group_box_layout.addWidget(self.skypatcher_radio)
        output_type_group_box_layout.addWidget(self.bos_ini_radio)

        self.output_type_button_group.addButton(self.skypatcher_radio)
        self.output_type_button_group.addButton(self.bos_ini_radio)

        # Set default selection (will be overridden by _load_config if config exists)
        self.skypatcher_radio.setChecked(True)

        main_layout.addWidget(output_type_group_box)

        # Game Version Selection
        game_version_group_box_layout = QVBoxLayout()
        game_version_group_box = QWidget()
        game_version_group_box.setLayout(game_version_group_box_layout)

        game_version_label = QLabel("Select Game Version:")
        game_version_group_box_layout.addWidget(game_version_label)

        self.game_version_button_group = QButtonGroup(self)
        self.skyrimse_radio = QRadioButton("Skyrim Special Edition")
        self.skyrimvr_radio = QRadioButton("Skyrim VR") # Add this if you want VR selection

        game_version_group_box_layout.addWidget(self.skyrimse_radio)
        game_version_group_box_layout.addWidget(self.skyrimvr_radio) # Add this if you want VR selection
        self.game_version_button_group.addButton(self.skyrimse_radio)
        self.game_version_button_group.addButton(self.skyrimvr_radio) # Add this if you want VR selection

        # Set default selection (will be overridden by _load_config if config exists)
        self.skyrimse_radio.setChecked(True) # Default to SkyrimSE

        main_layout.addWidget(game_version_group_box)

        # Common Paths (Output Folder) - Export Script Path removed
        paths_group_box_layout = QVBoxLayout()
        paths_group_box = QWidget()
        paths_group_box.setLayout(paths_group_box_layout)
        
        # Output Folder Path
        output_folder_layout = QHBoxLayout()
        output_folder_layout.addWidget(QLabel("Output Folder:"))
        self.output_folder_lineEdit = QLineEdit()
        self.output_folder_lineEdit.setReadOnly(True) # Make it read-only, user clicks button
        output_folder_layout.addWidget(self.output_folder_lineEdit)
        output_folder_button = QPushButton("Browse")
        output_folder_button.clicked.connect(self._select_output_folder)
        output_folder_layout.addWidget(output_folder_button)
        paths_group_box_layout.addLayout(output_folder_layout)

        # DELETED: Export Script Path block

        main_layout.addWidget(paths_group_box)

        # SkyPatcher YAML Specific Inputs
        self.skypatcher_inputs_widget = QWidget()
        skypatcher_layout = QVBoxLayout()
        self.skypatcher_inputs_widget.setLayout(skypatcher_layout)

        # xEdit JSON Path
        xedit_json_layout = QHBoxLayout()
        xedit_json_layout.addWidget(QLabel("Pre-exported xEdit JSON:"))
        self.xedit_json_lineEdit = QLineEdit()
        self.xedit_json_lineEdit.setReadOnly(True) # User browses for this
        xedit_json_layout.addWidget(self.xedit_json_lineEdit)
        xedit_json_button = QPushButton("Browse")
        xedit_json_button.clicked.connect(self._select_xedit_json)
        xedit_json_layout.addWidget(xedit_json_button)
        skypatcher_layout.addLayout(xedit_json_layout)
        
        # Broad Category Swap Checkbox
        self.broad_category_swap_checkbox = QCheckBox("Enable Broad Category Swap (experimental)")
        self.broad_category_swap_checkbox.setChecked(False) # Default to unchecked
        skypatcher_layout.addWidget(self.broad_category_swap_checkbox)

        # Keywords LineEdit
        keywords_layout = QHBoxLayout()
        keywords_layout.addWidget(QLabel("Keywords (comma separated):"))
        self.keywords_lineEdit = QLineEdit()
        keywords_layout.addWidget(self.keywords_lineEdit)
        skypatcher_layout.addLayout(keywords_layout)


        # Categories
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        category_layout.addWidget(self.category_combo)
        skypatcher_layout.addLayout(category_layout)

        # Target Mod
        target_mod_layout = QHBoxLayout()
        target_mod_layout.addWidget(QLabel("Target Mod:"))
        self.target_mod_combo = QComboBox()
        target_mod_layout.addWidget(self.target_mod_combo)
        skypatcher_layout.addLayout(target_mod_layout)

        # Source Mod (Single)
        source_mod_layout = QHBoxLayout()
        source_mod_layout.addWidget(QLabel("Source Mod:"))
        self.source_mod_combo = QComboBox()
        source_mod_layout.addWidget(self.source_mod_combo)
        skypatcher_layout.addLayout(source_mod_layout)

        main_layout.addWidget(self.skypatcher_inputs_widget)


        # BOS INI Specific Inputs
        self.bos_ini_inputs_widget = QWidget()
        bos_ini_layout = QVBoxLayout()
        self.bos_ini_inputs_widget.setLayout(bos_ini_layout)

        # IGPC JSON Path
        igpc_path_layout = QHBoxLayout()
        igpc_path_layout.addWidget(QLabel("IGPC JSON Path:"))
        self.igpc_path_lineEdit = QLineEdit()
        self.igpc_path_lineEdit.setReadOnly(True) # User browses for this
        igpc_path_layout.addWidget(self.igpc_path_lineEdit)
        igpc_path_button = QPushButton("Browse")
        igpc_path_button.clicked.connect(self._select_igpc_json)
        igpc_path_layout.addWidget(igpc_path_button)
        bos_ini_layout.addLayout(igpc_path_layout)

        main_layout.addWidget(self.bos_ini_inputs_widget)


        # Action Buttons
        button_layout = QHBoxLayout()
        self.generate_single_btn = QPushButton("Generate Single YAML/INI")
        self.generate_all_btn = QPushButton("Generate All Applicable YAMLs")
        self.cancel_btn = QPushButton("Cancel")
        
        button_layout.addStretch(1) # Pushes buttons to the right
        button_layout.addWidget(self.generate_single_btn)
        button_layout.addWidget(self.generate_all_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch(1)

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def _on_output_type_toggled(self):
        """
        Toggles visibility of UI elements based on selected output type (SkyPatcher YAML or BOS INI).
        Also sets the self.selected_output_type and updates button states.
        """
        if self.skypatcher_radio.isChecked():
            self.selected_output_type = "SkyPatcher YAML"
            self.skypatcher_inputs_widget.setVisible(True)
            self.bos_ini_inputs_widget.setVisible(False)
            self.generate_single_btn.setText("Generate Single YAML")
            self.generate_all_btn.setText("Generate All Applicable YAMLs")
            self.generate_all_btn.setEnabled(True) # Always enabled for YAML
        elif self.bos_ini_radio.isChecked():
            self.selected_output_type = "BOS INI"
            self.skypatcher_inputs_widget.setVisible(False)
            self.bos_ini_inputs_widget.setVisible(True)
            self.generate_single_btn.setText("Generate BOS INIs (All)") # Single button generates all for BOS INI
            self.generate_all_btn.setText("Generate BOS INIs (All)") # Same for consistency
            self.generate_all_btn.setEnabled(False) # Disable 'Generate All' if both buttons do same
        
        self._organizer_wrapper.log(0, f"SkyGen: Output type toggled to: {self.selected_output_type}")
        self._save_config() # Save the selected output type immediately

    def _populate_categories(self):
        """
        Populates the category QComboBox with a predefined list of common categories.
        Removed dependency on categories.json.
        """
        self.category_combo.clear()
        self.category_combo.addItem("") # Add an empty/default item
        
        # Hardcoded list of common categories (Signatures)
        common_categories = [
            "ARMA", "ARMO", "BOOK", "FLST", "FURN", "IMAD", "INGR", 
            "KEYM", "LVLI", "MISC", "WEAP", "WOOP", "SPEL", "STAT", "QUST"
        ]
        
        for category_name in sorted(common_categories):
            self.category_combo.addItem(category_name)
        self._organizer_wrapper.log(1, f"SkyGen: Populated categories with {len(common_categories)} common types.")
        # self._save_config() # No need to save here, as selections are saved by _update_category

    def _update_category(self):
        """Updates the selected category based on QComboBox selection."""
        self.selected_category = self.category_combo.currentText()
        self._organizer_wrapper.log(0, f"SkyGen: Category selected: {self.selected_category}")
        self._save_config() # Save the selected category

    def _populate_mod_combos(self):
        """
        Populates the target and source mod QComboBoxes with active mods from MO2.
        Adds game masters (ESMs) as well.
        """
        self.target_mod_combo.clear()
        self.source_mod_combo.clear()
        
        self.target_mod_combo.addItem("") # Allow no selection
        self.source_mod_combo.addItem("") # Allow no selection

        mod_names = []
        # Add active mods
        for mod_name in self._organizer_wrapper.modList().allMods():
            if self._organizer_wrapper.modList().state(mod_name) & mobase.ModState.ACTIVE:
                display_name = self._organizer_wrapper.modList().displayName(mod_name)
                mod_names.append(display_name)
        
        # Add active plugins that are ESMs (like Skyrim.esm, Update.esm, Dawnguard.esm)
        for plugin_name in self._organizer_wrapper.pluginList().pluginNames():
            if plugin_name.lower().endswith((".esm", ".esp", ".esl")):
                if self._organizer_wrapper.pluginList().state(plugin_name) & mobase.PluginState.ACTIVE:
                    if plugin_name not in mod_names: # Avoid duplicates if an ESM is also a mod
                        mod_names.append(plugin_name)

        mod_names.sort(key=str.lower) # Sort alphabetically
        
        self.target_mod_combo.addItems(mod_names)
        self.source_mod_combo.addItems(mod_names)
        self._organizer_wrapper.log(1, f"SkyGen: Populated mod combos with {len(mod_names)} active mods/ESMs.")
        self._save_config() # Save the selected mod combos

    def _get_plugin_name_from_mod_name(self, mo2_display_name: str, mo2_internal_mod_name: str) -> Optional[str]:
        """
        Attempts to find the plugin filename (.esp, .esm, .esl) associated with an MO2 mod display name.
        Accounts for disambiguation map and user selection for multiple plugins in one mod.
        """
        self._organizer_wrapper.log(0, f"SkyGen: Resolving plugin name for MO2 display '{mo2_display_name}' (Internal: '{mo2_internal_mod_name}')")

        if mo2_display_name.lower().endswith((".esm", ".esp", ".esl")):
            # If the display name itself is a plugin, assume it's the plugin name
            if self._organizer_wrapper.pluginList().state(mo2_display_name) & mobase.PluginState.ACTIVE:
                self._organizer_wrapper.log(0, f"SkyGen: Detected display name is a plugin: {mo2_display_name}")
                return mo2_display_name

        # Check disambiguation map first
        if mo2_display_name in self.plugin_disambiguation_map:
            suggested_plugin = self.plugin_disambiguation_map[mo2_display_name]
            if self._organizer_wrapper.pluginList().state(suggested_plugin) & mobase.PluginState.ACTIVE:
                self._organizer_wrapper.log(0, f"SkyGen: Found plugin in disambiguation map for '{mo2_display_name}': {suggested_plugin}")
                return suggested_plugin
            else:
                self._organizer_wrapper.log(2, f"SkyGen: WARNING: Disambiguation map entry '{mo2_display_name}': '{suggested_plugin}' is not an active plugin. Will prompt user.")


        # Get files from the mod's directory within MO2's VFS
        mod_path = Path(self._organizer_wrapper.modsPath()) / mo2_internal_mod_name
        
        potential_plugins = []
        for root, _, files in os.walk(mod_path):
            for file in files:
                if file.lower().endswith((".esm", ".esp", ".esl")):
                    full_plugin_name = file
                    # Check if the plugin is active in MO2's plugin list
                    if self._organizer_wrapper.pluginList().state(full_plugin_name) & mobase.PluginState.ACTIVE:
                        potential_plugins.append(full_plugin_name)
                        self._organizer_wrapper.log(0, f"SkyGen: Found active plugin in mod '{mo2_display_name}': {full_plugin_name}")

        if not potential_plugins:
            self.showWarning("Plugin Not Found", f"No active plugin (.esm, .esp, .esl) found for mod '{mo2_display_name}'. "
                                                "Please ensure the mod contains an active plugin file.")
            self._organizer_wrapper.log(2, f"SkyGen: No active plugins found for mod '{mo2_display_name}' (internal: {mo2_internal_mod_name}).")
            return None
        elif len(potential_plugins) == 1:
            self._organizer_wrapper.log(0, f"SkyGen: Uniquely determined plugin for '{mo2_display_name}': {potential_plugins[0]}")
            return potential_plugins[0]
        else:
            # Multiple plugins found, prompt user to choose
            self._organizer_wrapper.log(1, f"SkyGen: Multiple active plugins found for '{mo2_display_name}': {', '.join(potential_plugins)}. Prompting user. ")
            selected_plugin = self._prompt_for_plugin_selection(mo2_display_name, potential_plugins)
            if selected_plugin:
                # Add to disambiguation map for future runs
                self.plugin_disambiguation_map[mo2_display_name] = selected_plugin
                self._save_config()
            return selected_plugin

    def _prompt_for_plugin_selection(self, mod_display_name: str, plugins: list[str]) -> Optional[str]:
        """
        Displays a dialog to let the user select one plugin from a list.
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(f"Select Plugin for {mod_display_name}")
        msg_box.setText(f"Multiple active plugins found for '{mod_display_name}'. Please select one:")
        
        list_widget = QListWidget()
        list_widget.addItems(plugins)
        list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        if plugins:
            list_widget.setCurrentRow(0) # Select the first item by default

        msg_box.layout().addWidget(list_widget)

        select_button = msg_box.addButton("Select", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()

        if msg_box.clickedButton() == select_button and list_widget.selectedItems():
            selected_item = list_widget.selectedItems()[0].text()
            self._organizer_wrapper.log(0, f"SkyGen: User selected plugin: {selected_item}")
            return selected_item
        else:
            self._organizer_wrapper.log(0, "SkyGen: User cancelled plugin selection.")
            return None


    def _on_target_mod_selected(self):
        """Updates the selected target mod."""
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self._organizer_wrapper.log(0, f"SkyGen: Target mod selected: {self.selected_target_mod_name}")
        self._save_config()

    def _on_source_mod_selected(self):
        """Updates the selected source mod."""
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self._organizer_wrapper.log(0, f"SkyGen: Source mod selected: {self.selected_source_mod_name}")
        self._save_config()

    def _on_broad_category_swap_changed(self, state):
        """Updates the broad_category_swap_enabled flag."""
        self.broad_category_swap_enabled = (state == Qt.Checked)
        self._organizer_wrapper.log(0, f"SkyGen: Broad Category Swap: {self.broad_category_swap_enabled}")
        self._save_config()

    def _select_output_folder(self):
        """Opens a dialog to select the output folder."""
        # Start browsing from MO2's overwrite path
        initial_dir = str(Path(self._organizer_wrapper._organizer.overwritePath())) # Corrected access
        folder_path = QFileDialog.getExistingDirectory(self, "Select Output Folder", initial_dir)
        if folder_path:
            self.output_folder_path = folder_path
            self.output_folder_lineEdit.setText(folder_path)
            self._organizer_wrapper.log(0, f"SkyGen: Output folder selected: {self.output_folder_path}")
            self._save_config()

    def _select_xedit_json(self):
        """Opens a dialog to select a pre-exported xEdit JSON file."""
        json_path, _ = QFileDialog.getOpenFileName(self, "Select Pre-exported xEdit JSON",
                                                   "", "JSON Files (*.json);;All Files (*)")
        if json_path:
            self.pre_exported_xedit_json_path = json_path
            self.xedit_json_lineEdit.setText(json_path)
            self._organizer_wrapper.log(0, f"SkyGen: Pre-exported xEdit JSON selected: {self.pre_exported_xedit_json_path}")
            self._save_config()

    def _select_igpc_json(self):
        """Opens a dialog to select the IGPC JSON file."""
        json_path, _ = QFileDialog.getOpenFileName(self, "Select IGPC JSON",
                                                   "", "JSON Files (*.json);;All Files (*)")
        if json_path:
            self.igpc_json_path = json_path
            self.igpc_path_lineEdit.setText(json_path)
            self._organizer_wrapper.log(0, f"SkyGen: IGPC JSON selected: {self.igpc_json_path}")
            self._save_config()


    def _on_game_version_toggled(self):
        """
        Updates the self.selected_game_version based on the selected radio button.
        """
        if self.skyrimse_radio.isChecked():
            self.selected_game_version = "SkyrimSE"
        elif self.skyrimvr_radio.isChecked(): # For Skyrim VR
            self.selected_game_version = "SkyrimVR"
        self._organizer_wrapper.log(0, f"SkyGen: Game version selected: {self.selected_game_version}")
        self._save_config() # Save the selected game version immediately


    def _validate_inputs(self) -> bool:
        """
        Validates all necessary inputs before triggering generation.
        Returns True if inputs are valid, False otherwise.
        """
        # Validate output folder
        if not self.output_folder_path or not Path(self.output_folder_path).is_dir():
            self.showError("Input Error", "Please select a valid Output Folder.")
            return False

        if self.skypatcher_radio.isChecked():
            self.selected_output_type = "SkyPatcher YAML"
            # Validate export script path if not using pre-exported JSON
            # This check is now only for pre-exported JSON. The Pascal script path is hardcoded.
            if not self.xedit_json_lineEdit.text().strip(): # If pre-exported JSON is NOT provided
                # No longer checking self.full_export_script_path, as it's hardcoded and assumed to exist in xEdit's scripts
                pass # Removed previous script path validation
            
            # Validate categories
            if not self.selected_category:
                self.showError("Input Error", "Please select a Category.")
                return False

            # Validate target mod
            if not self.selected_target_mod_name:
                self.showError("Input Error", "Please select a Target Mod.")
                return False
            
            # Game version is fixed for now, but could be selectable later
            # self.game_version = "SkyrimSE" # This line should now be removed from here, as _on_game_version_toggled sets it
            # The value comes from the radio buttons now, already set by _on_game_version_toggled
            if not self.selected_game_version:
                self.showError("Input Error", "Please select a Game Version.")
                return False


        elif self.bos_ini_radio.isChecked():
            self.selected_output_type = "BOS INI"
            # Validate IGPC JSON Path
            igpc_path_str = self.igpc_path_lineEdit.text().strip()
            if not igpc_path_str:
                self.showError("Input Error", "IGPC JSON Path cannot be empty for BOS INI generation.")
                return False
            if not Path(igpc_path_str).is_file():
                self.showError("File Not Found", f"IGPC JSON file not found at: {igpc_path_str}")
                return False
            
            # If valid, save to instance variable for retrieval by plugin.py
            self.igpc_json_path = igpc_path_str

        return True


    def _on_generate_single_clicked(self):
        """
        Handles the "Generate Single YAML/INI" button click.
        """
        self._organizer_wrapper.log(1, "SkyGen: 'Generate Single' button clicked.")
        self.generate_all = False # Ensure this is set for single generation
        if self._validate_inputs():
            if self.selected_output_type == "SkyPatcher YAML":
                if not self.selected_source_mod_name:
                    self.showError("Input Error", "Please select a Source Mod for single YAML generation.")
                    return
            self.accept() # Close dialog with QDialog.Accepted

    def _on_generate_all_clicked(self):
        """
        Handles the "Generate All Applicable YAMLs" button click.
        This button should only be enabled for SkyPatcher YAML mode.
        """
        self._organizer_wrapper.log(1, "SkyGen: 'Generate All' button clicked.")
        self.generate_all = True # Ensure this is set for all generation
        if self.selected_output_type == "BOS INI":
            self.showWarning("Invalid Operation", "Generate All is not applicable for BOS INI. Use the single generate button.")
            return
        if self._validate_inputs():
            self.accept() # Close dialog with QDialog.Accepted

    def showError(self, title: str, message: str):
        """Helper to show a critical error message box and log."""
        self._organizer_wrapper.log(3, f"SkyGen: UI Error - {title}: {message}")
        QMessageBox.critical(self, title, message)

    def showWarning(self, title: str, message: str):
        """Helper to show a warning message box and log."""
        self._organizer_wrapper.log(2, f"SkyGen: UI Warning - {title}: {message}")
        QMessageBox.warning(self, title, message)

    def showInformation(self, title: str, message: str):
        """Helper to show an information message box and log."""
        self._organizer_wrapper.log(1, f"SkyGen: UI Info - {title}: {message}")
        QMessageBox.information(self, title, message)

    def reject(self):
        """Overrides reject to log cancellation."""
        self._organizer_wrapper.log(1, "SkyGen: Dialog cancelled by user.")
        super().reject()

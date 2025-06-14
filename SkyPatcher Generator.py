# Section 1: Imports
import mobase
import os
import json
import yaml
import subprocess
import traceback
from pathlib import Path
from collections import defaultdict
import time # Added for time.sleep

# Ensure necessary modules are imported correctly and used appropriately
try:
    from PyQt6.QtWidgets import (
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
        QFileDialog
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
except ImportError:
    print("One or more required PyQt modules are not installed. Please ensure PyQt6 is installed.")
    # Define dummy classes/functions to prevent hard crashes if PyQt6 is missing
    # In a real MO2 plugin, this would likely lead to the plugin not loading.
    class QDialog:
        def __init__(self, *args, **kwargs): pass
        def exec(self): return 0 # Simulate rejection
        def setLayout(self, *args, **kwargs): pass # Added for consistency
        def reject(self): pass # Dummy reject method
    class QVBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addLayout(self, *args, **kwargs): pass
        def addWidget(self, *args, **kwargs): pass
    class QHBoxLayout:
        def __init__(self, *args, **kwargs): pass
        def addWidget(self, *args, **kwargs): pass
    class QLabel:
        def __init__(self, *args, **kwargs): pass
    class QLineEdit:
        def __init__(self, *args, **kwargs): pass
        def setText(self, *args, **kwargs): pass
        def text(self): return ""
    class QPushButton:
        def __init__(self, *args, **kwargs): pass
        def clicked(self): return type('obj', (object,), {'connect': lambda *args: None})() # Dummy signal
    class QComboBox:
        def __init__(self, *args, **kwargs): pass
        def addItems(self, *args, **kwargs): pass
        def currentIndexChanged(self): return type('obj', (object,), {'connect': lambda *args: None})() # Dummy signal
        def currentText(self): return ""
        def itemText(self, index): return ""
    class QMessageBox:
        @staticmethod
        def critical(*args, **kwargs): print(f"CRITICAL: {args[2]}")
        @staticmethod
        def warning(*args, **kwargs): print(f"WARNING: {args[2]}")
        @staticmethod
        def information(*args, **kwargs): print(f"INFO: {args[2]}")
    class QButtonGroup:
        def __init__(self, *args, **kwargs): pass
    class QWidget:
        def __init__(self, *args, **kwargs): pass
        def setLayout(self, *args, **kwargs): pass
    class QSizePolicy:
        def __init__(self, *args, **kwargs): pass
    class QFileDialog:
        @staticmethod
        def getOpenFileName(*args, **kwargs): return "", ""
    class Qt:
        class DialogCode:
            Accepted = 1
            Rejected = 0
    class QIcon:
        def __init__(self, *args, **kwargs): pass

# Section 2: Utility Functions
def read_nexus_categories(filepath: Path):
    """
    Reads categories from a Nexus-style category map file.
    Each line is expected to be in the format: ID|Name|...
    """
    categories = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):  # Ignore empty lines and comments
                    continue
                parts = line.split("|")
                if len(parts) >= 2:  # Ensure there's at least an ID and a Name
                    categories.append(parts[1])
    except Exception as e:
        # It's generally better to log to MO2's log if an organizer instance is available,
        # but for a global helper, print is a fallback.
        print(f"ERROR: Failed to read categories from {filepath}: {e}")
    return categories

# Section 3: UI Dialog Class and Core Logic
class SkyPatcherToolDialog(QDialog):
    def __init__(self, organizer: mobase.IOrganizer, parent=None):
        super().__init__(parent)
        self.organizer = organizer
        self.setWindowTitle("SkyPatcher YAML Generator Configuration")
        self.setMinimumWidth(500)

        # Initialize variables
        self.igpc_json_path = ""
        self.pre_exported_xedit_json_path = "" # Added for pre-exported data
        self.selected_game_version = ""
        self.selected_category = ""
        self.selected_target_mod_name = ""
        self.selected_source_mod_name = ""
        self.generate_all = False
        self.search_keywords = ""

        # Initialize UI components
        self._init_ui()

        # Connect signal slots to methods
        self.game_version_combo.currentIndexChanged.connect(self._update_game_version)
        self.target_mod_combo.currentIndexChanged.connect(self._on_target_mod_selected)
        self.source_mod_combo.currentIndexChanged.connect(self._on_source_mod_selected)
        self.generate_single_btn.clicked.connect(self._on_generate_single_clicked)
        self.generate_all_btn.clicked.connect(self._on_generate_all_clicked)
        self.cancel_btn.clicked.connect(self.reject)

    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout()

        # Input for IGPC JSON Path
        igpc_path_layout = QHBoxLayout()
        self.igpc_path_label = QLabel("IGPC JSON Path:")
        self.igpc_path_lineEdit = QLineEdit(self.igpc_json_path)
        self.igpc_path_button = QPushButton("Browse...")
        self.igpc_path_button.clicked.connect(self._browse_igpc_json)
        igpc_path_layout.addWidget(self.igpc_path_label)
        igpc_path_layout.addWidget(self.igpc_path_lineEdit)
        igpc_path_layout.addWidget(self.igpc_path_button)
        layout.addLayout(igpc_path_layout)

        # Input for Pre-exported xEdit JSON Path (Optional)
        xedit_json_layout = QHBoxLayout()
        self.xedit_json_label = QLabel("Pre-exported xEdit JSON (Optional):")
        self.xedit_json_lineEdit = QLineEdit(self.pre_exported_xedit_json_path)
        self.xedit_json_button = QPushButton("Browse...")
        self.xedit_json_button.clicked.connect(self._browse_xedit_json)
        xedit_json_layout.addWidget(self.xedit_json_label)
        xedit_json_layout.addWidget(self.xedit_json_lineEdit)
        xedit_json_layout.addWidget(self.xedit_json_button)
        layout.addLayout(xedit_json_layout)

        # Game Version Selection
        game_version_layout = QHBoxLayout()
        game_version_layout.addWidget(QLabel("Game Version:"))
        self.game_version_combo = QComboBox()
        self.game_version_combo.addItems(["Select Game Version", "SkyrimSE", "SkyrimVR", "SkyrimLE"])
        game_version_layout.addWidget(self.game_version_combo)
        layout.addLayout(game_version_layout)

        # Category Selection
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        # Populate categories from a default file or allow user to browse
        default_category_file = Path(__file__).parent.parent / "Nexus JSON Generator" / "category_map.txt"
        categories = ["Select Category"] + read_nexus_categories(default_category_file)
        self.category_combo.addItems(categories)
        category_layout.addWidget(self.category_combo)
        layout.addLayout(category_layout)

        # Target Mod Selection
        target_mod_layout = QHBoxLayout()
        target_mod_layout.addWidget(QLabel("Target Mod (MO2 Name):"))
        self.target_mod_combo = QComboBox()
        self.target_mod_combo.addItem("Select Target Mod")
        self._populate_mod_combobox(self.target_mod_combo)
        target_mod_layout.addWidget(self.target_mod_combo)
        layout.addLayout(target_mod_layout)

        # Source Mod Selection (for single generation)
        source_mod_layout = QHBoxLayout()
        source_mod_layout.addWidget(QLabel("Source Mod (for Single Gen):"))
        self.source_mod_combo = QComboBox()
        self.source_mod_combo.addItem("Select Source Mod")
        self._populate_mod_combobox(self.source_mod_combo)
        source_mod_layout.addWidget(self.source_mod_combo)
        layout.addLayout(source_mod_layout)

        # Search Keywords
        keywords_layout = QHBoxLayout()
        keywords_layout.addWidget(QLabel("Filter by EDID Keywords (comma-separated):"))
        self.keywords_lineEdit = QLineEdit("")
        keywords_layout.addWidget(self.keywords_lineEdit)
        layout.addLayout(keywords_layout)

        # Buttons
        button_layout = QHBoxLayout()
        self.generate_single_btn = QPushButton("Generate Single YAML")
        self.generate_all_btn = QPushButton("Generate All Applicable YAMLs")
        self.cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(self.generate_single_btn)
        button_layout.addWidget(self.generate_all_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Set initial values from saved settings or defaults
        self.igpc_path_lineEdit.setText(self.igpc_json_path)
        self.xedit_json_lineEdit.setText(self.pre_exported_xedit_json_path)


    def _populate_mod_combobox(self, combo_box: QComboBox):
        """Populates a QComboBox with active MO2 mod names."""
        mod_list = self.organizer.modList()
        if mod_list:
            active_mods = sorted([mod_list.displayName(mod_name) for mod_name in mod_list.allMods() if mod_list.state(mod_name) & mobase.ModState.ACTIVE], key=lambda s: s.lower())
            combo_box.addItems(active_mods)


    def _browse_igpc_json(self):
        """Opens a file dialog to select the IGPC JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select IGPC JSON File", "", "JSON Files (*.json)")
        if file_path:
            self.igpc_json_path = file_path
            self.igpc_path_lineEdit.setText(file_path)

    def _browse_xedit_json(self):
        """Opens a file dialog to select the pre-exported xEdit JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Pre-exported xEdit JSON File", "", "JSON Files (*.json)")
        if file_path:
            self.pre_exported_xedit_json_path = file_path
            self.xedit_json_lineEdit.setText(file_path)


    def _update_game_version(self, index):
        """Update the selected game version."""
        self.selected_game_version = self.game_version_combo.currentText()
        self.organizer.log(mobase.LogLevel.DEBUG, f"Game version selected: {self.selected_game_version}")

    def _on_target_mod_selected(self, index):
        """Handle selection of target mod in combo box."""
        self.selected_target_mod_name = self.target_mod_combo.currentText()
        self.organizer.log(mobase.LogLevel.DEBUG, f"Target mod selected: {self.selected_target_mod_name}")

    def _on_source_mod_selected(self, index):
        """Handle selection of source mod in combo box."""
        self.selected_source_mod_name = self.source_mod_combo.currentText()
        self.organizer.log(mobase.LogLevel.DEBUG, f"Source mod selected: {self.selected_source_mod_name}")

    def _validate_inputs(self) -> bool:
        """Validates user inputs before proceeding with generation."""
        if not self.igpc_json_path or not Path(self.igpc_json_path).exists():
            self.showError("Input Missing", "Please select a valid IGPC JSON file.")
            return False

        if self.pre_exported_xedit_json_path and not Path(self.pre_exported_xedit_json_path).exists():
            self.showError("Input Missing", "Pre-exported xEdit JSON file path is invalid.")
            return False

        # Validate selected game version
        if not self.selected_game_version or self.selected_game_version == "Select Game Version":
            self.showError("Invalid Selection", "Please select a valid Game Version.")
            return False

        # Validate category
        if not self.selected_category or self.selected_category == "Select Category":
            self.showError("Invalid Selection", "Please select a valid Category.")
            return False

        # Validate target mod
        if not self.selected_target_mod_name or self.selected_target_mod_name == "Select Target Mod":
            self.showError("Invalid Selection", "Please select a valid Target Mod.")
            return False

        # Additional validation for single generation if needed
        if not self.generate_all and (not self.selected_source_mod_name or self.selected_source_mod_name == "Select Source Mod"):
             self.showError("Invalid Selection", "Please select a valid Source Mod for single generation.")
             return False

        return True

    def _on_generate_single_clicked(self):
        """Prepares for single YAML generation and accepts the dialog."""
        self.organizer.log(mobase.LogLevel.DEBUG, "Generate Single clicked.")
        self.generate_all = False
        self.search_keywords = self.keywords_lineEdit.text()
        self.selected_category = self.category_combo.currentText()

        if self._validate_inputs():
            self.accept()
        else:
            self.organizer.log(mobase.LogLevel.WARNING, "Validation failed for single generation.")

    def _on_generate_all_clicked(self):
        """Prepares for all applicable YAMLs generation and accepts the dialog."""
        self.organizer.log(mobase.LogLevel.DEBUG, "Generate All clicked.")
        self.generate_all = True
        self.search_keywords = self.keywords_lineEdit.text()
        self.selected_category = self.category_combo.currentText()

        # For "Generate All", source mod selection is not strictly required for validation
        # as it iterates through all active mods.
        # We temporarily set selected_source_mod_name to an empty string to bypass its specific validation.
        original_source_mod_selection = self.selected_source_mod_name
        self.selected_source_mod_name = "" # Temporarily clear for validation logic

        if self._validate_inputs():
            self.accept()
        else:
            self.selected_source_mod_name = original_source_mod_selection # Revert if validation failed
            self.organizer.log(mobase.LogLevel.WARNING, "Validation failed for 'generate all'.")
    def _on_generate_all_clicked(self):
        """Prepares for all applicable YAMLs generation and accepts the dialog."""
        self.organizer.log(mobase.LogLevel.DEBUG, "Generate All clicked.")
        self.generate_all = True
        self.search_keywords = self.keywords_lineEdit.text()
        self.selected_category = self.category_combo.currentText()

        # For "Generate All", source mod selection is not strictly required for validation
        # as it iterates through all active mods.
        # We temporarily set selected_source_mod_name to an empty string to bypass its specific validation.
        original_source_mod_selection = self.selected_source_mod_name
        self.selected_source_mod_name = "" # Temporarily clear for validation logic

        if self._validate_inputs():
            self.accept()
        else:
            self.selected_source_mod_name = original_source_mod_selection # Revert if validation failed
            self.organizer.log(mobase.LogLevel.WARNING, "Validation failed for 'generate all'.")

    # Section 4: Error Handling and Logging (Moved into Dialog Class)
    def showError(self, title: str, message: str):
        """Show an error dialog with a given title and message."""
        QMessageBox.critical(self, title, message)
        self.organizer.log(mobase.LogLevel.ERROR, f"{title}: {message}")

    # Section 5: xEdit Handling Methods (Moved into Dialog Class)
    def _find_xedit_path(self, game_version: str) -> Path | None: # Return Path or None
        """
        Finds the xEdit executable path based on the selected game version.
        Prioritizes MO2 registered executables, then common install paths.
        """
        xedit_exec_name_map = {
            "SkyrimSE": "SSEEdit.exe", # Case sensitive for some systems
            "SkyrimVR": "TES5VREdit.exe", # Common name, sometimes TES5VREdit64.exe
            "SkyrimLE": "TES5Edit.exe"
        }
        xedit_exec_name = xedit_exec_name_map.get(game_version)
        alternate_xedit_exec_name = None
        if game_version == "SkyrimVR":
            alternate_xedit_exec_name = "TES5VREdit64.exe"

        if not xedit_exec_name:
            self.organizer.log(mobase.LogLevel.ERROR, f"Unknown game version '{game_version}' for xEdit lookup.")
            return None

        # 1. Check MO2 registered executables
        if self.organizer.pluginList():
            for exec_key in self.organizer.pluginList().pluginNames():
                plugin = self.organizer.pluginList().plugin(exec_key)
            if plugin and hasattr(plugin, 'is') and "MO2Executable" in plugin.is():
                    binary_path = Path(plugin.binary())
                    # Reformat the long condition for robustness
                    if (binary_path.name.lower() == xedit_exec_name.lower() or
                        (alternate_xedit_exec_name and binary_path.name.lower() == alternate_xedit_exec_name.lower())):
                        if binary_path.is_file():
                            self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit via MO2 executable '{exec_key}': {binary_path}")
                            return binary_path

        # 2. Search common xEdit install locations relative to MO2's instance path and game path
        search_paths = set() # Use a set to avoid duplicate searches
        if self.organizer.basePath():
            search_paths.add(Path(self.organizer.basePath()))
            search_paths.add(Path(self.organizer.basePath()).parent)

        try:
            game_path_str = self.organizer.gameInfo().path()
            if game_path_str:
                game_path_resolved = Path(game_path_str)
                search_paths.add(game_path_resolved) # Game directory itself
                search_paths.add(game_path_resolved.parent) # Directory containing game directory
                search_paths.add(game_path_resolved / "xEdit") # Game_Dir/xEdit
                search_paths.add(game_path_resolved / xedit_exec_name_map.get(game_version, "").replace(".exe","")) # Game_Dir/SSEEdit
        except Exception as e:
            self.organizer.log(mobase.LogLevel.DEBUG, f"Could not determine game path from MO2 or error processing it: {e}")

        possible_xedit_folders = ["xEdit", xedit_exec_name.replace(".exe", ""), "Tools/xEdit"]
        if alternate_xedit_exec_name:
            possible_xedit_folders.append(alternate_xedit_exec_name.replace(".exe", ""))


        for base_path in search_paths:
            for folder in possible_xedit_folders:
                candidate_path = base_path / folder / xedit_exec_name
                if candidate_path.is_file():
                    self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit in common folder: {candidate_path}")
                    return candidate_path
                if alternate_xedit_exec_name:
                    candidate_path_alt = base_path / folder / alternate_xedit_exec_name
                    if candidate_path_alt.is_file():
                        self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit (alt name) in common folder: {candidate_path_alt}")
                        return candidate_path_alt
            # Check directly in base_path as well
            direct_candidate = base_path / xedit_exec_name
            if direct_candidate.is_file():
                self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit directly in path: {direct_candidate}")
                return direct_candidate
            if alternate_xedit_exec_name:
                direct_candidate_alt = base_path / alternate_xedit_exec_name
                if direct_candidate_alt.is_file():
                    self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit (alt name) directly in path: {direct_candidate_alt}")
                    return direct_candidate_alt

        # Re-constructing this line very carefully to avoid any subtle issues.
        # This is the line that has been causing persistent SyntaxErrors.
        # The issue is almost certainly an invisible character or encoding problem.
        # Re-typing it character by character with a simple string concatenation.
        error_msg = "xEdit executable ('" + xedit_exec_name
        if alternate_xedit_exec_name:
            error_msg += " or '" + alternate_xedit_exec_name + "'"
        error_msg += "') not found after checking MO2 executables and common paths."
        self.organizer.log(mobase.LogLevel.ERROR, error_msg) # This is the problematic line
        return None

    def _run_xedit_export(self, output_path: Path, target_plugin_name: str, game_version: str) -> bool:
        """
        Runs xEdit to export data for a specific target plugin.
        """
        self.organizer.log(mobase.LogLevel.INFO, f"Attempting to find xEdit for game version: {game_version}")
        xedit_path = self._find_xedit_path(game_version)

        if not xedit_path:
            self.showError("xEdit Not Found", f"Could not automatically find xEdit for {game_version}. "
                                 "Please ensure it's installed and, if necessary, configured as an MO2 executable.")
            return False
        self.organizer.log(mobase.LogLevel.INFO, f"Using xEdit path: {xedit_path}")

        script_file_path = Path(__file__).parent / "ExportPluginData.pas" # Assuming script is in the same directory
        if not script_file_path.exists():
            self.showError("xEdit Script Missing",
                                 f"xEdit script 'ExportPluginData.pas' not found at {script_file_path}.")
            return False
        self.organizer.log(mobase.LogLevel.INFO, f"Using xEdit script: {script_file_path}")


        # Ensure output directory for the script exists (it expects the dir, not the file)
        output_json_dir = output_path.parent
        output_json_dir.mkdir(parents=True, exist_ok=True)

        xedit_args = [
            # Define a variable for the script: output JSON file path
            f"-D:ExportPath=\"{output_path.as_posix()}\"", # Pass the full desired output file path
            # Define a variable for the script: target plugin name
            f"-D:TargetPlugin=\"{target_plugin_name}\"",
            # Path to the Pascal script to execute
            f"-script:\"{script_file_path.as_posix()}\"",
            "-IKnowWhatImDoing",
            "-NoAutoUpdate",
            "-NoAutoBackup",
            "-quickautoclean" # Optional: can speed up loading for some versions.
        ]

        game_mode_arg = {
            "SkyrimLE": "-tes5",
            "SkyrimSE": "-sse",
            "SkyrimVR": "-tes5vr"
        }.get(game_version)

        if game_mode_arg:
            xedit_args.insert(0, game_mode_arg) # e.g. -sse
        else:
            self.organizer.log(mobase.LogLevel.WARNING, f"No specific game mode argument for xEdit for game version '{game_version}'. Launching without it.")


        mo2_exec_name_to_use = None
        if self.organizer.pluginList():
            for exec_key in self.organizer.pluginList().pluginNames():
                plugin = self.organizer.pluginList().plugin(exec_key)
                if plugin and hasattr(plugin, 'is') and "MO2Executable" in plugin.is():
                    try:
                        if Path(plugin.binary()).resolve() == xedit_path.resolve():
                            mo2_exec_name_to_use = exec_key
                            self.organizer.log(mobase.LogLevel.INFO, f"Found MO2 executable '{mo2_exec_name_to_use}' for xEdit binary '{xedit_path}'.")
                            break
                    except Exception as e: # Handle potential errors during resolve (e.g. file not found if path is bad)
                        self.organizer.log(mobase.LogLevel.DEBUG, f"Error resolving path for MO2 executable '{plugin.binary()}' or xEdit path '{xedit_path}': {e}. Comparing directly.")
                        if Path(plugin.binary()) == xedit_path: # Fallback to direct comparison
                            mo2_exec_name_to_use = exec_key
                            self.organizer.log(mobase.LogLevel.INFO, f"Found MO2 executable '{mo2_exec_name_to_use}' for xEdit binary '{xedit_path}' (using direct comparison).")
                            break

        if not mo2_exec_name_to_use:
            self.showError("xEdit Launch Error",
                                 f"Could not find a registered MO2 executable for '{xedit_path}'. "
                                 "Please add xEdit to MO2's executables and ensure its path is correctly configured.")
            return False

        self.organizer.log(mobase.LogLevel.INFO, f"Calling MO2's startApplication for '{mo2_exec_name_to_use}' with arguments: {xedit_args}")

        try:
            # MO2 startApplication requires a working directory. Game data path is usually best.
            cwd = self.organizer.gameDataPath()
            if not cwd or not Path(cwd).exists():
                cwd = self.organizer.managedGame().gameDirectory().absolutePath() # Game directory
                self.organizer.log(mobase.LogLevel.WARNING, f"gameDataPath not valid, using gameDirectory as CWD: {cwd}")
            if not cwd or not Path(cwd).exists(): # If still no valid CWD
                 cwd = str(xedit_path.parent) # Fallback to xEdit's own directory
                 self.organizer.log(mobase.LogLevel.WARNING, f"Game directory also not valid, using xEdit directory as CWD: {cwd}")


            # Ensure output file does not exist before running, or xEdit might append/error
            if output_path.exists():
                self.organizer.log(mobase.LogLevel.INFO, f"Pre-existing xEdit output file found at {output_path}. Deleting.")
                try:
                    output_path.unlink()
                except OSError as e:
                    self.showError("File Error", f"Could not delete pre-existing xEdit output file: {output_path}.\nPlease check permissions or delete it manually.")
                    return False


            app_handle = self.organizer.startApplication(mo2_exec_name_to_use, xedit_args, str(cwd))

            if app_handle == 0: # 0 typically means failure to start by MO2
                self.showError("xEdit Launch Failed",
                                     f"Failed to launch '{mo2_exec_name_to_use}' via MO2. "
                                     "Check your MO2 setup for this executable and MO2 logs.")
                return False

            self.organizer.log(mobase.LogLevel.INFO, f"xEdit launched with handle: {app_handle}. Waiting for output file: {output_path}")

            max_wait_time = 120  # seconds
            wait_interval = 1   # seconds
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                if output_path.is_file() and output_path.stat().st_size > 0:
                    self.organizer.log(mobase.LogLevel.INFO, f"xEdit output file found and is not empty: {output_path}")
                    # Brief pause to ensure file write is complete
                    time.sleep(2)
                    return True

                self.organizer.log(mobase.LogLevel.DEBUG, f"Waiting for xEdit export ({elapsed_time}/{max_wait_time}s)... Output: {output_path.exists()}, Size: {output_path.stat().st_size if output_path.exists() else 'N/A'}")
                time.sleep(wait_interval)
                elapsed_time += wait_interval

            # Timeout occurred
            self.showError("xEdit Timeout",
                                 f"xEdit output file '{output_path.name}' was not created or was empty after {max_wait_time} seconds. "
                                 "Check xEdit logs (e.g., in Overwrite/xEdit Logs, or xEdit's own log files) for errors.")
            return False

        except Exception as e:
            self.organizer.log(mobase.LogLevel.CRITICAL, f"Error launching or running xEdit: {e}\n{traceback.format_exc()}")
            self.showError("xEdit Error",
                                 f"An unexpected error occurred while trying to run xEdit: {e}\nCheck MO2 logs for more details.")
            return False

    # Section 6: Data Loading and YAML Generation Methods (Moved into Dialog Class)
    def _load_json_data(self, file_path: Path, description: str):
        """
        Loads JSON data from a specified file path.
        """
        if not file_path or not file_path.exists(): # Added check for None path
            self.organizer.log(mobase.LogLevel.WARNING, f"{description} file path is invalid or file not found at: {file_path}.")
            self.showError("File Not Found", f"{description} file not found at the specified path: {file_path}.")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.organizer.log(mobase.LogLevel.INFO, f"Successfully loaded {description} from: {file_path}")
            return data
        except (IOError, json.JSONDecodeError) as e:
            self.organizer.log(mobase.LogLevel.ERROR, f"Error loading {description} from {file_path}: {e}")
            self.showError("File Load Error", f"Error loading {description} from {file_path}: {e}")
            return None
        except Exception as e: # Catch any other unexpected error
            self.organizer.log(mobase.LogLevel.ERROR, f"Unexpected error loading {description} from {file_path}: {e}\n{traceback.format_exc()}")
            self.showError("File Load Error", f"An unexpected error occurred while loading {description} from {file_path}: {e}")
            return None


    def _generate_and_write_skypatcher_yaml(
        self,
        igpc_json_data: dict,
        category: str,
        target_mod_plugin_name: str,
        source_mod_plugin_name: str,
        source_mod_mo2_name: str, # MO2 display name
        source_mod_base_objects_from_xedit: list,
        all_exported_target_bases_by_formid: dict,
        search_keywords: str = ""
    ) -> int: # Return 1 if YAML generated, 0 otherwise
        """
        Generates the SkyPatcher YAML content and writes it to a file
        within the specified source mod's MO2 folder. Returns 1 on success, 0 on failure/no replacements.
        """
        self.organizer.log(mobase.LogLevel.INFO, f"Generating YAML for source mod: {source_mod_mo2_name} (Plugin: {source_mod_plugin_name})")

        filtered_source_bases = []
        keywords_list = [k.strip().lower() for k in search_keywords.split(',') if k.strip()]

        for obj in source_mod_base_objects_from_xedit:
            edid = obj.get("EDID")
            if edid: # Ensure EDID exists
                edid_lower = edid.lower()
                if not keywords_list or any(keyword in edid_lower for keyword in keywords_list):
                    filtered_source_bases.append(obj)
            # else:
            #     self.organizer.log(mobase.LogLevel.DEBUG, f"Source object skipped (no EDID): {obj.get('formId')}")


        source_bases_by_edid = {obj["EDID"]: obj.get("formId") for obj in filtered_source_bases if obj.get("EDID") and obj.get("formId")}
        self.organizer.log(mobase.LogLevel.DEBUG, f"Source bases by EDID for {source_mod_mo2_name} (filtered by keywords '{search_keywords}'): {len(source_bases_by_edid)} entries.")

        if not source_bases_by_edid and filtered_source_bases:
             self.organizer.log(mobase.LogLevel.WARNING, f"Some filtered source bases for {source_mod_mo2_name} are missing FormID or EDID after keyword filtering.")


        grouped_replacements = defaultdict(lambda: {"newBase": None, "references": set()})

        igpc_records = igpc_json_data.get("records", [])
        if not isinstance(igpc_records, list):
            self.organizer.log(mobase.LogLevel.ERROR, "IGPC JSON 'records' field is not a list. Aborting YAML generation for this mod.")
            self.showError("Error", "IGPC JSON format error: 'records' field is not a list.")
            return 0

        for ref_entry in igpc_records:
            ref_form_id = ref_entry.get("formId")
            base_object_form_id_from_igpc = ref_entry.get("base")
            ref_origin_mod_from_igpc = ref_entry.get("sourceName")

            if not ref_form_id or not base_object_form_id_from_igpc or not ref_origin_mod_from_igpc:
                self.organizer.log(mobase.LogLevel.WARNING, f"Skipping IGPC reference due to missing formId, base, or sourceName: {ref_entry}")
                continue

            base_info_from_xedit = all_exported_target_bases_by_formid.get(base_object_form_id_from_igpc)

            if not base_info_from_xedit:
                self.organizer.log(mobase.LogLevel.DEBUG, f"Base object {base_object_form_id_from_igpc} (from IGPC reference {ref_form_id}) not found in xEdit's exported base objects. Skipping.")
                continue

            base_origin_mod_from_xedit = base_info_from_xedit.get("originMod")
            base_category_from_xedit = base_info_from_xedit.get("category")
            base_edid_from_xedit = base_info_from_xedit.get("EDID")

            if base_origin_mod_from_xedit == target_mod_plugin_name and \
               base_category_from_xedit == category and \
               base_edid_from_xedit:

                new_base_form_id_from_source = source_bases_by_edid.get(base_edid_from_xedit)

                if new_base_form_id_from_source:
                    new_base_identifier = f"{source_mod_plugin_name}|{new_base_form_id_from_source}"
                    reference_identifier = f"{ref_origin_mod_from_igpc}|{ref_form_id}"

                    grouped_replacements[new_base_identifier]["newBase"] = new_base_identifier
                    grouped_replacements[new_base_identifier]["references"].add(reference_identifier)
                    self.organizer.log(mobase.LogLevel.DEBUG, f"  - Matched target base EDID '{base_edid_from_xedit}' (FormID: {base_object_form_id_from_igpc}) "
                                       f"with source base FormID '{new_base_form_id_from_source}'. Adding reference: {reference_identifier}")
                # else:
                #     self.organizer.log(mobase.LogLevel.DEBUG, f"  - No source match found for target EDID: '{base_edid_from_xedit}' in {source_mod_plugin_name} (category '{category}', keywords '{search_keywords}').")
            # else:
            #     self.organizer.log(mobase.LogLevel.DEBUG, f"Base object {base_object_form_id_from_igpc} (EDID: {base_edid_from_xedit}, Origin: {base_origin_mod_from_xedit}, Cat: {base_category_from_xedit}) "
            #                                                f"does not match target criteria (TargetMod: {target_mod_plugin_name}, TargetCat: {category}). Skipping.")


        output_replacements = []
        for _, data in grouped_replacements.items(): # Key `new_base_key` is not used from items()
            if data["newBase"] and data["references"]:
                output_replacements.append({
                    "newBase": data["newBase"],
                    "references": sorted(list(data["references"]))
                })

        if not output_replacements:
            self.organizer.log(mobase.LogLevel.INFO, f"No replacements found for {source_mod_mo2_name} in category '{category}' with current settings (keywords '{search_keywords}'). No YAML generated.")
            # Only show message box if it's a single mod generation, to avoid spam for "Generate All"
            # This check would ideally be outside this function, based on generate_all_mods flag.
            # For now, this function might be called in a loop, so avoid direct QMessageBox here for "no replacements".
            # The calling function in `display` handles the "no replacements" summary.
            return 0

        yaml_content = {
            "replacements": output_replacements
        }

        try:
            # Need to get the internal name for getPath if source_mod_mo2_name is display name
            source_mod_internal_name = self.organizer.modList().getMod(source_mod_mo2_name).name()
            source_mod_path = Path(self.organizer.modList().getPath(source_mod_internal_name))
        except Exception as e:
            self.organizer.log(mobase.LogLevel.ERROR, f"Could not get path for source mod '{source_mod_mo2_name}': {e}. Cannot write YAML.")
            self.showError("Error", f"Source mod folder '{source_mod_mo2_name}' path not found: {e}. Cannot write YAML.")
            return 0


        if not source_mod_path.exists(): # Should be caught by getPath raising an error if mod doesn't exist
            self.organizer.log(mobase.LogLevel.ERROR, f"Source mod path does not exist: {source_mod_path}. Cannot write YAML.")
            self.showError("Error", f"Source mod folder '{source_mod_mo2_name}' resolved to a non-existent path: {source_mod_path}. Cannot write YAML.")
            return 0

        skypatcher_config_dir = source_mod_path / "SkyPatcher" / "Configs"
        skypatcher_config_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize category name for filename
        sane_category_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in category).strip().replace(' ', '_')
        yaml_filename = f"{source_mod_mo2_name}-{sane_category_name}-Replacements.yaml"
        output_yaml_path = skypatcher_config_dir / yaml_filename

        try:
            with open(output_yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(yaml_content, f, default_flow_style=False, indent=2, sort_keys=False)
            self.organizer.log(mobase.LogLevel.INFO, f"Successfully wrote SkyPatcher YAML to: {output_yaml_path}")
            return 1 # Success
        except Exception as e:
            self.organizer.log(mobase.LogLevel.ERROR, f"Error writing YAML to {output_yaml_path}: {e}\n{traceback.format_exc()}")
            self.showError("Write Error", f"Failed to write YAML to {output_yaml_path}: {e}")
            return 0

# Section 7: Main Plugin Class (MO2 Interface)
class SkyPatcherGeneratorTool(mobase.IPluginTool):
# Reformat the long condition for robustness
if (binary_path.name.lower() == xedit_exec_name.lower() or
    (alternate_xedit_exec_name and binary_path.name.lower() == alternate_xedit_exec_name.lower())):
    
    if binary_path.is_file():
        self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit via MO2 executable '{exec_key}': {binary_path}")
        return binary_path# Reformat the long condition for robustness
if (binary_path.name.lower() == xedit_exec_name.lower() or
    (alternate_xedit_exec_name and binary_path.name.lower() == alternate_xedit_exec_name.lower())):
    
    if binary_path.is_file():
        self.organizer.log(mobase.LogLevel.INFO, f"Found xEdit via MO2 executable '{exec_key}': {binary_path}")
        return binary_path    def __init__(self):
        super().__init__()
        self.organizer = None
        self.plugin_name = "SkyPatcher Generator"
        self.patch_mod_name = "SkyPatcher Patch - Generated" # Default name for the new mod
        self.xedit_script_name = "ExportPluginData.pas" # Name of the xEdit script

    def init(self, organizer: mobase.IOrganizer):
        self.organizer = organizer
        self.organizer.log(mobase.LogLevel.INFO, f"{self.plugin_name} initialized.")
        return True

    def name(self):
        return "SkyPatcher Generator"

    def displayName(self):
        return self.name()

    def description(self):
        return "Generates SkyPatcher YAML files for asset replacements based on xEdit data (live export or pre-exported JSON)."

    def version(self):
        return mobase.VersionInfo(1, 0, 6, mobase.VersionInfo.ReleaseType.FINAL)

    def isActive(self):
        return self.organizer is not None

    def settings(self):
        # If you want to save/load settings like default paths through MO2,
        # you would define them here. For now, returning empty list means no MO2-managed settings.
        return []

    def display(self):
        self.organizer.log(mobase.LogLevel.INFO, f"Starting {self.plugin_name} display method...")

        dialog = SkyPatcherToolDialog(self.organizer)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.organizer.log(mobase.LogLevel.INFO, "User cancelled the operation.")
            return

        # Get values from the dialog after it's accepted
        igpc_json_path = dialog.igpc_json_path
        pre_exported_xedit_json_path = dialog.pre_exported_xedit_json_path
        selected_game_version = dialog.selected_game_version
        selected_category = dialog.selected_category
        target_mod_mo2_name = dialog.selected_target_mod_name
        source_mod_mo2_name = dialog.selected_source_mod_name
        generate_all_mods = dialog.generate_all
        search_keywords = dialog.search_keywords

        self.organizer.log(mobase.LogLevel.INFO, f"IGPC JSON: {igpc_json_path}")
        self.organizer.log(mobase.LogLevel.INFO, f"Pre-exported xEdit JSON: {pre_exported_xedit_json_path if pre_exported_xedit_json_path else 'Not provided'}")
        self.organizer.log(mobase.LogLevel.INFO, f"Game Version: {selected_game_version}")
        self.organizer.log(mobase.LogLevel.INFO, f"Category: {selected_category}")
        self.organizer.log(mobase.LogLevel.INFO, f"Target Mod (MO2 Name): {target_mod_mo2_name}")
        self.organizer.log(mobase.LogLevel.INFO, f"Source Mod (MO2 Name): {source_mod_mo2_name if source_mod_mo2_name else 'N/A (Generate All)'}")
        self.organizer.log(mobase.LogLevel.INFO, f"Generate for All Mods: {generate_all_mods}")
        self.organizer.log(mobase.LogLevel.INFO, f"Search Keywords: '{search_keywords}'")

        # Check for SkyPatcher enabled status
        mod_list = self.organizer.modList()
        skypatcher_enabled = False
        if mod_list is not None:
            try:
                for mod_name_iter in mod_list.allMods():
                    if "skypatcher" in mod_name_iter.lower() and (mod_list.state(mod_name_iter) & mobase.ModState.ACTIVE):
                        skypatcher_enabled = True
                        self.organizer.log(mobase.LogLevel.INFO, f"Found active SkyPatcher mod: {mod_name_iter}")
                        break
                if not skypatcher_enabled:
                    dialog.showError(
                        "SkyPatcher Not Enabled",
                        "No enabled mod containing 'SkyPatcher' was found in MO2.\n"
                        "Please ensure a SkyPatcher-related mod is active before generating YAMLs."
                    )
                    return
            except Exception as e:
                self.organizer.log(mobase.LogLevel.WARNING, f"Could not check SkyPatcher mod state: {e}")
                dialog.showError("Warning", f"Could not check SkyPatcher mod state: {e}")
        else:
            self.organizer.log(mobase.LogLevel.WARNING, "Mod list is None, cannot check SkyPatcher status.")
            dialog.showError("Warning", "Could not retrieve mod list to check SkyPatcher status.")
            return


        target_mod_obj = self.organizer.getMod(target_mod_mo2_name)
        if not target_mod_obj or not target_mod_obj.isActive():
            dialog.showError("Error", f"The selected target mod '{target_mod_mo2_name}' is not active or does not exist.")
            return

        target_mod_plugin_name = ""
        try:
            if hasattr(target_mod_obj, 'fileName') and callable(getattr(target_mod_obj, 'fileName')) :
                 target_mod_plugin_name = target_mod_obj.fileName()
            else:
                mod_path = Path(self.organizer.modList().getPath(target_mod_mo2_name))
                plugins = [f.name for f in mod_path.glob("*.es[mp]")] + [f.name for f in mod_path.glob("*.esl")]
                if plugins:
                    target_mod_plugin_name = plugins[0]
                    self.organizer.log(mobase.LogLevel.INFO, f"Found plugin '{target_mod_plugin_name}' in target mod '{target_mod_mo2_name}'.")
                else:
                    dialog.showError("Error", f"Could not determine the plugin name for target mod '{target_mod_mo2_name}'.")
                    return
        except Exception as e:
            dialog.showError("Error", f"Error getting plugin name for target mod '{target_mod_mo2_name}': {e}")
            return

        self.organizer.log(mobase.LogLevel.INFO, f"Target Mod Plugin Name: {target_mod_plugin_name}")

        xedit_export_data = None

        if pre_exported_xedit_json_path and Path(pre_exported_xedit_json_path).exists():
            self.organizer.log(mobase.LogLevel.INFO, f"Loading pre-exported xEdit data from: {pre_exported_xedit_json_path}")
            xedit_export_data = dialog._load_json_data(Path(pre_exported_xedit_json_path), "Pre-exported xEdit Data JSON")
        else:
            self.organizer.log(mobase.LogLevel.INFO, f"Running xEdit to export data for target mod: {target_mod_plugin_name}")
            xedit_export_output_dir = Path(self.organizer.overwritePath()) / "SKSE" / "Plugins" / "StorageUtilData"
            xedit_export_output_dir.mkdir(parents=True, exist_ok=True)
            default_xedit_export_path = xedit_export_output_dir / "xedit_exported_data.json"
            self.organizer.log(mobase.LogLevel.INFO, f"Default xEdit export path: {default_xedit_export_path}")

            if not dialog._run_xedit_export(default_xedit_export_path, target_mod_plugin_name, selected_game_version):
                self.organizer.log(mobase.LogLevel.ERROR, "xEdit data export failed. Aborting.")
                return
            xedit_export_data = dialog._load_json_data(default_xedit_export_path, "xEdit Export JSON")

        igpc_json_data = dialog._load_json_data(Path(igpc_json_path), "IGPC JSON")

        if igpc_json_data is None or xedit_export_data is None:
            self.organizer.log(mobase.LogLevel.ERROR, "Failed to load necessary data. Aborting.")
            return

        all_exported_target_bases_by_formid = {
            obj.get("formId"): obj for obj in xedit_export_data.get("baseObjects", []) if obj.get("formId")
        }
        self.organizer.log(mobase.LogLevel.INFO, f"Loaded {len(all_exported_target_bases_by_formid)} base objects from xEdit export.")

        source_mod_base_objects_from_xedit = xedit_export_data.get("sourceModBaseObjects", [])
        self.organizer.log(mobase.LogLevel.INFO, f"Loaded {len(source_mod_base_objects_from_xedit)} source mod base objects from xEdit export.")

        total_yamls_generated = 0

        if generate_all_mods:
            self.organizer.log(mobase.LogLevel.INFO, "Generating YAMLs for all applicable mods.")
            all_mods_list = self.organizer.modList().allMods()
            active_mods_details = [(self.organizer.modList().displayName(mod_name), mod_name) for mod_name in all_mods_list if mod_list.state(mod_name) & mobase.ModState.ACTIVE]

            other_active_mods_details = [ (disp_name, mod_name_internal) for disp_name, mod_name_internal in active_mods_details if disp_name != target_mod_mo2_name]


            if not other_active_mods_details:
                dialog.showError("No Source Mods", "No other active mods found to generate patches against the target mod.")
                return

            for current_source_mod_display_name, current_source_mod_internal_name in other_active_mods_details:
                current_source_mod_path = Path(self.organizer.modList().getPath(current_source_mod_internal_name))
                current_source_plugins = [f.name for f in current_source_mod_path.glob("*.es[mp]")] + [f.name for f in current_source_mod_path.glob("*.esl")]
                if not current_source_plugins:
                    self.organizer.log(mobase.LogLevel.WARNING, f"Skipping source mod '{current_source_mod_display_name}': No plugin (.esp/esm/esl) found.")
                    continue
                current_source_mod_plugin_name = current_source_plugins[0]

                self.organizer.log(mobase.LogLevel.INFO, f"Processing source mod: {current_source_mod_display_name} ({current_source_mod_plugin_name})")

                source_bases_for_this_mod = [
                    obj for obj in source_mod_base_objects_from_xedit
                    if obj.get("originMod") == current_source_mod_plugin_name and obj.get("category") == selected_category
                ]

                if not source_bases_for_this_mod:
                    self.organizer.log(mobase.LogLevel.INFO, f"Skipping {current_source_mod_display_name}: No relevant base objects found for category '{selected_category}'.")
                    continue

                generated_count = dialog._generate_and_write_skypatcher_yaml(
                    igpc_json_data=igpc_json_data,
                    category=selected_category,
                    target_mod_plugin_name=target_mod_plugin_name,
                    source_mod_plugin_name=current_source_mod_plugin_name,
                    source_mod_mo2_name=current_source_mod_display_name, # Use display name for paths/logging
                    source_mod_base_objects_from_xedit=source_bases_for_this_mod,
                    all_exported_target_bases_by_formid=all_exported_target_bases_by_formid,
                    search_keywords=search_keywords
                )
                if generated_count > 0:
                    total_yamls_generated += 1

            if not total_yamls_generated:
                dialog.showError("Finished", "No YAMLs were generated for any mods with the current settings.")
            else:
                dialog.showError("Finished", f"Successfully generated YAMLs for {total_yamls_generated} mod(s).")

        else: # Single mod generation
            self.organizer.log(mobase.LogLevel.INFO, f"Generating YAML for single mod: {source_mod_mo2_name}")
            selected_source_mod_obj = self.organizer.getMod(source_mod_mo2_name)
            if not selected_source_mod_obj or not selected_source_mod_obj.isActive():
                dialog.showError("Error", f"The selected source mod '{source_mod_mo2_name}' is not active or does not exist.")
                return

            source_mod_plugin_name = ""
            try:
                if hasattr(selected_source_mod_obj, 'fileName') and callable(getattr(selected_source_mod_obj, 'fileName')) :
                    source_mod_plugin_name = selected_source_mod_obj.fileName()
                else:
                    source_mod_internal_name = self.organizer.modList().getMod(source_mod_mo2_name).name()
                    mod_path = Path(self.organizer.modList().getPath(source_mod_internal_name))
                    plugins = [f.name for f in mod_path.glob("*.es[mp]")] + [f.name for f in mod_path.glob("*.esl")]
                    if plugins:
                        source_mod_plugin_name = plugins[0]
                        self.organizer.log(mobase.LogLevel.INFO, f"Found plugin '{source_mod_plugin_name}' in source mod '{source_mod_mo2_name}'.")
                    else:
                        dialog.showError("Error", f"Could not determine plugin name for source mod '{source_mod_mo2_name}'.")
                        return
            except Exception as e:
                dialog.showError("Error", f"Error getting plugin name for source mod '{source_mod_mo2_name}': {e}")
                return

            self.organizer.log(mobase.LogLevel.INFO, f"Selected Source Mod Plugin Name: {source_mod_plugin_name}")

            source_bases_for_selected_mod = [
                obj for obj in source_mod_base_objects_from_xedit
                if obj.get("originMod") == source_mod_plugin_name and obj.get("category") == selected_category
            ]

            if not source_bases_for_selected_mod:
                dialog.showError("No Replacements", f"No relevant base objects found in '{source_mod_mo2_name}' for category '{selected_category}'. No YAML will be generated.")
                return

            generated_count = dialog._generate_and_write_skypatcher_yaml(
                igpc_json_data=igpc_json_data,
                category=selected_category,
                target_mod_plugin_name=target_mod_plugin_name,
                source_mod_plugin_name=source_mod_plugin_name,
                source_mod_mo2_name=source_mod_mo2_name, # Display name
                source_mod_base_objects_from_xedit=source_bases_for_selected_mod,
                all_exported_target_bases_by_formid=all_exported_target_bases_by_formid,
                search_keywords=search_keywords
            )
            if generated_count > 0:
                dialog.showError("Success", f"SkyPatcher YAML generated successfully for mod '{source_mod_mo2_name}'.\nRemember to enable this mod and the main SkyPatcher mod in MO2.")
            # If generated_count is 0, the _generate_and_write_skypatcher_yaml method would have shown a message.

# Section 8: Plugin Entry Point
    def createPlugin(self):
        return SkyPatcherGeneratorTool()

    super().__init__(parent)


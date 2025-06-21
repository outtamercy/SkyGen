# __init__.py (This is your main plugin file)

import mobase
import json
from pathlib import Path
from typing import Optional, Any

# Import UI and utility functions
from .skygen_ui import SkyGenToolDialog, OrganizerWrapper

# Note: These imports are relative to the package, which is why they work now that
# SkyGenGeneratorTool is in __init__.py and not in a separate 'plugin.py'.
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    safe_launch_xedit, # Using safe_launch_xedit directly
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
    # clean_temp_files, # Removed as it's handled internally by safe_launch_xedit
    # get_game_root_from_general_ini, # Not directly used by plugin, but by utilities
    # Removed write_pas_script_to_xedit import as it's now called internally by safe_launch_xedit
)

# Ensure necessary PyQt6 modules are imported for the main plugin if still used here,
# or for dummy QMessageBox if needed for initial checks.
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog # Import QDialog here
    from PyQt6.QtGui import QIcon # QIcon is used by the plugin tool directly
    from PyQt6.QtCore import Qt # Import Qt for window flags
except ImportError:
    # Define dummy classes if PyQt6 is not installed, to allow basic script parsing
    # without crashing, though UI functionality will be absent.
    print("One or more required PyQt modules are not installed. Please ensure PyQt6 is installed.")
    class QApplication:
        def __init__(self, *args, **kwargs): pass
        def instance(self): return None
        def exec(self): return 0
    class QMessageBox:
        # Dummy methods for QMessageBox if PyQt6 is not fully available
        @staticmethod
        def critical(parent, title, message): print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message): print(f"WARNING: {title}: {message}")
        @staticmethod
        def information(parent, title, message): print(f"INFORMATION: {title}: {message}")
    class QIcon:
        def __init__(self, *args, **kwargs): pass
    class QWidget:
        def __init__(self, *args, **kwargs):
            pass
        def show(self):
            pass
        def close(self):
            pass
        def setWindowTitle(self, title):
            pass
        def setLayout(self, layout):
            pass
        def setFixedSize(self, width, height):
            pass
        def setSizePolicy(self, policy):
            pass
    class QDialog: # Dummy QDialog if not available
        Accepted = 1 # Define Accepted constant
        Rejected = 0 # Define Rejected constant
        def __init__(self, *args, **kwargs): pass
        def exec(self): return QDialog.Rejected # Default to Rejected
    class Qt: # Dummy Qt object to prevent AttributeError for window flags
        WindowStaysOnTopHint = 0 # Dummy value


# This function creates and returns an instance of your plugin tool.
def createPlugin() -> mobase.IPluginTool:
    return SkyGenGeneratorTool()


class SkyGenGeneratorTool(mobase.IPluginTool):
    """
    Mod Organizer 2 plugin tool for SkyGen, automating Skyrim patching tasks.
    """
    def __init__(self):
        super().__init__()
        self.organizer: Optional[mobase.IOrganizer] = None
        self.wrapped_organizer: Optional[OrganizerWrapper] = None
        self.dialog: Optional[SkyGenToolDialog] = None
        self.xedit_exe_path: Optional[Path] = None
        self.xedit_mo2_name: str = "" # To store MO2's registered name for xEdit
        self.xedit_script_filename: str = "ExportPluginData.pas" # Pascal script name
        self.xedit_ini_filename: str = "ExportPluginData.ini" # INI file name for Pascal script


    def init(self, organizer: mobase.IOrganizer):
        """
        Initializes the plugin tool, sets up logging, and detects xEdit.
        """
        self.organizer = organizer
        self.wrapped_organizer = OrganizerWrapper(organizer)
        
        # Initialize logging for the wrapped organizer
        log_file_path = Path(self.organizer.pluginDataPath()) / "SkyGen" / "SkyGen_Debug.log"
        self.wrapped_organizer.set_log_file_path(log_file_path)

        self.wrapped_organizer.log(1, "SkyGen: Plugin initializing...")

        # Initialize the dialog (which will load its own config)
        self.dialog = SkyGenToolDialog(self.wrapped_organizer)
        
        # Pass the dialog instance to the wrapped_organizer for logging errors from dialog during init
        # Note: This requires a `dialog_instance` property on OrganizerWrapper
        self.wrapped_organizer.dialog_instance = self.dialog 

        # Get xEdit path and MO2 name during initialization
        # The dialog instance is needed here for error reporting if xEdit is not found during init
        xedit_info = get_xedit_exe_path(self.wrapped_organizer, self.dialog)
        if xedit_info:
            self.xedit_exe_path, self.xedit_mo2_name = xedit_info
            self.wrapped_organizer.log(1, f"SkyGen: Detected xEdit at: {self.xedit_exe_path} (MO2 Name: {self.xedit_mo2_name})")
        else:
            self.wrapped_organizer.log(3, "SkyGen: WARNING: xEdit executable not found during plugin initialization. Some functions may be unavailable.")
        
        # Example: keep on top if Qt.WindowStaysOnTopHint is available
        if hasattr(Qt, 'WindowStaysOnTopHint'):
            self.dialog.setWindowFlags(self.dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        self.dialog.setWindowTitle("SkyGen - Skyrim Patch Generator")
        
        self.wrapped_organizer.log(1, "SkyGen: Plugin initialized successfully.")
        return True

    def deinit(self):
        """
        Deinitializes the plugin tool, closing the log file.
        """
        self.wrapped_organizer.log(1, "SkyGen: Plugin de-initializing...")
        if self.wrapped_organizer:
            self.wrapped_organizer.close_log_file()
        return True

    def name(self) -> str:
        """Returns the name of the tool."""
        return "SkyGen"

    def displayName(self) -> str:
        """Returns the display name for the plugin in MO2's UI."""
        return "SkyGen" # It can simply return the same as name()

    def icon(self) -> QIcon:
        """Returns the icon for the plugin."""
        # You can replace 'QIcon()' with a path to an icon file if you have one,
        # but a default QIcon should prevent the crash.
        return QIcon()

    def tooltip(self) -> str:
        """Returns the tooltip text displayed when hovering over the plugin."""
        return "Automates generation of SkyPatcher YAML and BOS INI files using xEdit."

    def author(self) -> str:
        """Returns the author of the tool."""
        return "ZanderLex"

    def description(self) -> str:
        """Returns a brief description of the tool."""
        return "Automates generation of SkyPatcher YAML and BOS INI files using xEdit."

    def version(self) -> mobase.VersionInfo:
        """Returns the version of the tool."""
        return mobase.VersionInfo(1, 1, 0, mobase.ReleaseType.BETA) # Current version

    def isActive(self) -> bool:
        """Determines if the plugin is active."""
        return True

    def settings(self) -> list[mobase.PluginSetting]:
        """Returns a list of settings for the plugin."""
        return [] # No specific plugin settings managed directly by the tool outside the dialog

    def display(self) -> None:
        """
        Displays the main dialog of the plugin tool and handles its execution.
        """
        self.wrapped_organizer.log(1, "SkyGen: Displaying UI dialog...")

        # Ensure dialog has latest xEdit info if it was detected after init (unlikely but safe)
        self.dialog.determined_xedit_exe_path = self.xedit_exe_path
        self.dialog.determined_xedit_executable_name = self.xedit_mo2_name

        # Before showing, ensure output folder is sensible default if not set
        if not self.dialog.output_folder_lineEdit.text():
            # Default to MO2's overwrite folder or a new SkyGen_Output folder
            default_output_path = Path(self.organizer.modsPath()) / "SkyGen_Output"
            self.dialog.output_folder_lineEdit.setText(str(default_output_path))
            self.dialog.output_folder_path = str(default_output_path)

        if self.dialog.exec() == QDialog.DialogCode.Accepted: # Corrected to QDialog.DialogCode.Accepted
            self.wrapped_organizer.log(1, "SkyGen: Dialog accepted. Starting generation process.")
            
            output_type = self.dialog.selected_output_type
            output_folder_path = Path(self.dialog.output_folder_path) # Get path from dialog

            # Ensure output folder exists before proceeding
            if not output_folder_path.is_dir():
                try:
                    output_folder_path.mkdir(parents=True, exist_ok=True)
                    self.wrapped_organizer.log(1, f"SkyGen: Created output directory: {output_folder_path}")
                except Exception as e:
                    self.dialog.showError("Directory Creation Error", f"Failed to create output directory: {output_folder_path}\n{e}")
                    self.wrapped_organizer.log(4, f"SkyGen: ERROR: Failed to create output directory {output_folder_path}: {e}")
                    return

            # Check if xEdit path and name are available
            if not self.xedit_exe_path or not self.xedit_mo2_name:
                self.dialog.showError("xEdit Not Configured", "xEdit executable not found or configured. Please add it to MO2's executables and restart SkyGen.")
                self.wrapped_organizer.log(4, "SkyGen: CRITICAL: xEdit not found. Aborting generation.")
                return

            if output_type == "SkyPatcher YAML":
                # Delegate the actual YAML generation logic to the dialog's internal method
                self.dialog._generate_skypatcher_yaml_internal()

            elif output_type == "BOS INI":
                self.wrapped_organizer.log(1, "SkyGen: Generating BOS INI files...")
                igpc_json_path = Path(self.dialog.igpc_json_path)
                if not igpc_json_path.is_file():
                    self.dialog.showError("Input Error", "IGPC JSON file not found at the specified path.")
                    self.wrapped_organizer.log(3, f"SkyGen: IGPC JSON file not found: {igpc_json_path}")
                    return

                igpc_data = load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=igpc_json_path, description="IGPC JSON", dialog_instance=self.dialog)
                if igpc_data:
                    generate_bos_ini_files(wrapped_organizer=self.wrapped_organizer, igpc_data=igpc_data, output_folder_path=output_folder_path, dialog_instance=self.dialog)
                else:
                    self.wrapped_organizer.log(3, "SkyGen: Failed to load IGPC data. Aborting BOS INI generation.")
        else:
            self.wrapped_organizer.log(1, "SkyGen: Dialog cancelled by user. No action taken.")

    def __tr(self, str_: str) -> str:
        """Translates a string using MO2's translation mechanism."""
        # This assumes mobase.IOrganizer has a qtTr method.
        # If not, it falls back to returning the string itself.
        if self.organizer and hasattr(self.organizer, 'qtTr'):
            return self.organizer.qtTr(str_, self.name())
        return str_


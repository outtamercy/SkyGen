# __init__.py (This is your main plugin file)

import mobase
import json
from pathlib import Path
from typing import Optional, Any

# Import UI and utility functions
from .skygen_ui import SkyGenToolDialog, OrganizerWrapper
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
    class QMessageBox:
        @staticmethod
        def warning(parent, title, message): print(f"WARNING: {title}: {message}")
        @staticmethod
        def critical(parent, title, message): print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def information(parent, title, message): print(f"INFO: {title}: {message}")
    class QDialog:
        def __init__(self, *args, **kwargs): pass
        def exec(self): return 0 # Simulate dialog closing
    class QIcon:
        def __init__(self, *args, **kwargs): pass
    class Qt:
        WindowContextHelpButtonHint = 0
        WindowStaysOnTopHint = 0

# Import MO2_LOG_* constants from the new constants file
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
)


class SkyGenGeneratorTool(mobase.IPluginTool):
    """
    MO2 Plugin Tool for SkyGen.
    Provides the main entry point for the SkyGen functionality.
    """
    def __init__(self):
        super().__init__()
        self.organizer = None
        self.wrapped_organizer: Optional[OrganizerWrapper] = None # Our custom wrapper
        self.dialog: Optional[SkyGenToolDialog] = None
        self._debug_log_path: Optional[Path] = None

    def init(self, organizer: mobase.IOrganizer):
        self.organizer = organizer
        self.wrapped_organizer = OrganizerWrapper(organizer)
        
        # Set up the custom debug log file path immediately
        self._debug_log_path = Path(self.organizer.pluginDataPath()) / "SkyGen" / "SkyGen_Debug.log"
        self.wrapped_organizer.set_log_file_path(self._debug_log_path)
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Plugin initializing.")
        
        self.dialog = SkyGenToolDialog(self.wrapped_organizer)
        self.wrapped_organizer.dialog_instance = self.dialog # Pass dialog instance for direct error showing
        
        # Attempt to detect xEdit path and name early
        xedit_paths = get_xedit_exe_path(self.wrapped_organizer, self.dialog)
        if xedit_paths:
            self.dialog.determined_xedit_exe_path, self.dialog.determined_xedit_executable_name = xedit_paths
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Detected xEdit at: {self.dialog.determined_xedit_exe_path} (MO2 Name: {self.dialog.determined_xedit_executable_name})")
        else:
            self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: xEdit not automatically detected during plugin init.")
            # The dialog will show a warning if xEdit is still not found when generate is clicked.
        
        return True

    def name(self):
        return "SkyGen"

    def author(self):
        return "Shalom_Neumann"

    def description(self):
        return "Automates SkyPatcher YAML and BOS INI generation based on mod data and xEdit exports."

    def version(self):
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)

    def settings(self):
        return []

    def display(self):
        """
        Displays the main dialog for the SkyGen tool.
        This is the method called when the user clicks the tool button in MO2.
        """
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Display method called. Showing dialog.")
        if not self.dialog:
            self.wrapped_organizer.log(MO2_LOG_CRITICAL, "SkyGen: Dialog not initialized. Cannot display.")
            QMessageBox.critical(None, "SkyGen Error", "SkyGen dialog failed to initialize. Please check MO2 logs.")
            return

        # Ensure xEdit path is up-to-date before showing dialog
        xedit_paths = get_xedit_exe_path(self.wrapped_organizer, self.dialog)
        if xedit_paths:
            self.dialog.determined_xedit_exe_path, self.dialog.determined_xedit_executable_name = xedit_paths
        
        # Show the dialog
        result = self.dialog.exec() # Use exec() for modal dialog

        if result == QDialog.Accepted:
            self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Dialog accepted by user. Proceeding with generation.")
            output_type = self.dialog.selected_output_type
            output_folder_path = Path(self.dialog.output_folder_path)

            if output_type == "SkyPatcher YAML":
                self.wrapped_organizer.log(1, "SkyGen: Generating SkyPatcher YAML files...")
                self.dialog._generate_skypatcher_yaml_internal() # Call the internal generation logic
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
        # If not, it might need to be self.organizer.qtTr(str_, self.name())
        return self.organizer.qtTr(str_, self.name())

    def deinit(self):
        """
        Called by MO2 when the plugin is being unloaded.
        Ensures the custom debug log file is properly closed.
        """
        if self.wrapped_organizer:
            self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Plugin de-initializing. Closing debug log file.")
            self.wrapped_organizer.close_log_file()
        return True


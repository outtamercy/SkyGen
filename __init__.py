# __init__.py (This is your main plugin file)

import mobase
import json
from pathlib import Path
from typing import Optional, Any
import logging
import os

# Define the path for the plugin's debug log file
plugin_log_path = os.path.join(os.path.dirname(__file__), 'skygen_plugin_debug.log')

# Get the logger instance for SkyGen
skygen_logger = logging.getLogger('skygen')
skygen_logger.setLevel(logging.DEBUG) # Set overall logging level for SkyGen

# Avoid adding duplicate handlers if the plugin reloads (e.g., during MO2 restart)
if not skygen_logger.handlers:
    # Create a FileHandler for writing logs to a file
    file_handler = logging.FileHandler(plugin_log_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG) # Set level for this specific handler
    
    # Define a formatter for log messages
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    # Add the file handler to the logger
    skygen_logger.addHandler(file_handler)

skygen_logger.info("SkyGen plugin logger initialized successfully.")


# Import UI and utility functions
from .skygen_ui import SkyGenToolDialog, OrganizerWrapper
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    safe_launch_xedit, # Using safe_launch_xedit directly
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
)

# Import MO2_LOG_* constants from the new constants file
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
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
        def critical(parent, title, message): print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message): print(f"WARNING: {title}: {message}")
    class QDialog:
        def __init__(self, *args, **kwargs): pass
        def setWindowModality(self, modality): pass
        def exec(self): return 0 # Simulate rejection
        def show(self): pass
        def close(self): pass
        def accept(self): pass
        def reject(self): pass
    class QIcon:
        def __init__(self, *args, **kwargs): pass
    class Qt:
        WindowStaysOnTopHint = 0
        ApplicationModal = 0


class SkyGenPlugin(mobase.IPluginTool):
    """
    The main plugin class for SkyGen, integrating with Mod Organizer 2.
    """

    def __init__(self, organizer: mobase.IOrganizer): # Modified: accept organizer here
        super().__init__()
        self.organizer = organizer
        self.wrapped_organizer = OrganizerWrapper(self.organizer) 
        self.dialog: Optional[SkyGenToolDialog] = None
        self._xedit_exe_path: Optional[Path] = None
        self._xedit_mo2_name: str = ""

        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Organizer object assigned and wrapped.")

        # Set up the log file path using the wrapped organizer's method
        log_file_path = Path(self.wrapped_organizer.pluginDataPath()) / "SkyGen" / "skygen_plugin_debug.log"
        self.wrapped_organizer.set_log_file_path(log_file_path) # This call is now a placeholder due to new logging setup.
        
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen plugin __init__ called for initialization.")
        
        # Determine and store xEdit paths early
        self._determine_xedit_paths()

        # Initialize the dialog here but don't show it yet
        # Pass the wrapped_organizer to the dialog
        self.dialog = SkyGenToolDialog(self.wrapped_organizer)
        self.wrapped_organizer.dialog_instance = self.dialog # Set dialog_instance for direct UI error display from wrapper

        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen plugin initialized successfully within MO2.")
        # Removed the redundant 'init' method. All essential setup is now in __init__


    def name(self):
        return "SkyGen"

    def author(self):
        # Updated author credit
        return "BoltBot & ms.mayhem"

    def description(self):
        # Updated description
        return "Automate SkyPatcher YAML and BOS INI generation."

    def version(self):
        # Updated version
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)

    # Added URL property as per request
    def url(self):
        return "https://boltbot.app/"

    def settings(self):
        return [] # No specific settings to configure via MO2's settings dialog

    def display(self):
        """
        This method is called when the user clicks on the tool in MO2.
        It shows the dialog and handles the generation logic based on user input.
        """
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Display method called, showing dialog.")

        # Ensure a QApplication exists before creating QDialog
        if QApplication.instance() is None:
            QApplication([])
            self.wrapped_organizer.log(MO2_LOG_DEBUG, "SkyGen: QApplication instance created.")
        
        try:
            # Ensure the dialog's mod lists are populated every time it's displayed
            # This is important because MO2's mod list can change while the plugin is open
            self.dialog._populate_mods()
            self.dialog._populate_game_versions() # Ensure game versions are correctly set on display

            # Pass determined xEdit paths to the dialog before displaying it
            self.dialog.determined_xedit_exe_path = self._xedit_exe_path
            self.dialog.determined_xedit_executable_name = self._xedit_mo2_name

            # Show the dialog as modal
            result = self.dialog.exec() # Use exec() for modal dialogs

            if result == QDialog.Accepted: # Check against QDialog.Accepted or mobase.QDialog.Accepted (if QDialog imported as mobase.QDialog)
                self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Dialog accepted. Processing request.")
                selected_output_type = self.dialog.selected_output_type
                
                # Update config with latest determined xEdit paths from dialog before saving
                # These were already assigned above, but ensuring they are consistent with what's used.
                self.dialog._save_config()

                if selected_output_type == "SkyPatcher YAML":
                    self.dialog._generate_skypatcher_yaml_internal() # Call the internal generation method
                elif selected_output_type == "BOS INI":
                    igpc_json_file = Path(self.dialog.igpc_json_path)
                    output_folder_path = Path(self.dialog.output_folder_path)

                    if not igpc_json_file.is_file():
                        self.dialog.showError("File Not Found", f"IGPC JSON file not found at the specified path: {igpc_json_file}.")
                        self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: IGPC JSON file not found: {igpc_json_file}")
                        return

                    igpc_data = load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=igpc_json_file, description="IGPC JSON", dialog_instance=self.dialog)
                    if igpc_data:
                        generate_bos_ini_files(wrapped_organizer=self.wrapped_organizer, igpc_data=igpc_data, output_folder_path=output_folder_path, dialog_instance=self.dialog)
                    else:
                        self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: Failed to load IGPC data. Aborting BOS INI generation.")
            else:
                self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Dialog cancelled by user. No action taken.")

        except Exception as e:
            self.wrapped_organizer.log(MO2_LOG_CRITICAL, f"SkyGen: CRITICAL ERROR in display function: {e}", exc_info=True)
            if self.dialog:
                self.dialog.showError("Plugin Error", f"An unexpected error occurred: {e}\nCheck the SkyGen debug log for details.")
            else:
                QMessageBox.critical(None, "Plugin Error", f"An unexpected error occurred during dialog creation: {e}\nCheck the SkyGen debug log for details.")

    def _determine_xedit_paths(self):
        """
        Determines and stores the xEdit executable path and MO2 registered name.
        Called once during init.
        """
        xedit_info = get_xedit_exe_path(self.wrapped_organizer, None) # Pass None for dialog initially
        if xedit_info:
            self._xedit_exe_path, self._xedit_mo2_name = xedit_info
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: xEdit path determined: {self._xedit_exe_path} (MO2 name: {self._xedit_mo2_name})")
        else:
            self._xedit_exe_path = None
            self._xedit_mo2_name = ""
            self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: Could not determine xEdit path during plugin initialization.")


    def __tr(self, str_: str) -> str:
        """Translates a string using MO2's translation mechanism."""
        # This assumes mobase.IOrganizer has a qtTr method.
        # If not, it might need to be self.organizer.qtTr(str_, self.name())
        # Since organizer is now initialized in __init__, this might need self.organizer check
        if self.organizer:
            return self.organizer.qtTr(str_, self.name())
        return str_ # Fallback if organizer is not available for some reason

    def deinit(self):
        """
        Called by MO2 when the plugin is being unloaded.
        Ensures the custom debug log file is properly closed.
        """
        self.wrapped_organizer.close_log_file()
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen plugin deinitialized.")

# This function is automatically called by MO2 to create an instance of your plugin.
def createPlugin(organizer: mobase.IOrganizer):
    """
    This function is automatically called by MO2 to create an instance of your plugin.
    """
    return SkyGenPlugin(organizer) # Modified: pass organizer to the constructor


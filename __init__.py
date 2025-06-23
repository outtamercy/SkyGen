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

# NO MORE PYQT6 IMPORTS OR DUMMY CLASSES HERE
# They are handled in skygen_ui.py and skygen_file_utilities.py


class SkyGenPlugin(mobase.IPluginTool):
    """
    The main plugin class for SkyGen, integrating with Mod Organizer 2.
    """

    def __init__(self, organizer): # Modified: accept organizer here
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
        return "BoltBot & Mayhem" # Changed from ms.mayhem to Mayhem

    def description(self):
        # Updated description
        return "Automate SkyPatcher YAML and BOS INI generation."

    def version(self):
        # Updated version
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)

    # Added URL property as per request
    def url(self):
        return "https://github.com/outtamercy/SkyGen" # Updated URL

    def displayName(self): 
        return self.name() # It's common to return the same as name() for display

    def settings(self):
        return [] # No specific settings to configure via MO2's settings dialog

    def display(self):
        """
        This method is called when the user clicks on the tool in MO2.
        It shows the dialog and handles the generation logic based on user input.
        """
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Display method called, showing dialog.")

        # Ensure a QApplication exists before creating QDialog
        # This check should now be handled within the UI/utilities if needed by their dummy classes
        # or rely on MO2's main PyQt app being available.

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

            # Use QDialog.Accepted directly if it's guaranteed to be imported or part of MO2's API
            # For robustness, using the numerical value directly is also an option if import is tricky:
            # if result == 1: # QDialog.Accepted typically maps to 1
            # Note: QDialog is imported in skygen_ui.py and dummy-defined if not available.
            # Here, we need to ensure QDialog.Accepted is accessible.
            # Since mobase.QDialog.Accepted is used below in the original code, we'll revert to that.
            if result == mobase.QDialog.Accepted:
                self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Dialog accepted. Processing request.")
                selected_output_type = self.dialog.selected_output_type
                
                # Update config with latest determined xEdit paths from dialog before saving
                # These were already assigned above, but ensuring they are consistent with what's used.
                self.dialog._save_config()

                if selected_output_type == "SkyPatcher YAML":
                    # Call the refactored method in the dialog to get all parameters
                    params = self.dialog._generate_skypatcher_yaml_internal()
                    
                    if not params: # If parameter gathering failed (e.g., due to missing input)
                        self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: Parameter gathering for YAML generation failed. Aborting.")
                        return # Exit the display method

                    # Extract parameters for clarity
                    target_mod_display_name = params["target_mod_display_name"]
                    source_mod_display_name = params["source_mod_display_name"]
                    category = params["category"]
                    keywords = params["keywords"] # This is now a list
                    broad_category_swap_enabled = params["broad_category_swap_enabled"]
                    output_folder_path = params["output_folder_path"]
                    game_mode_flag = params["game_mode_flag"]
                    xedit_exe_path = params["xedit_exe_path"]
                    xedit_executable_name = params["xedit_executable_name"]
                    xedit_script_filename = params["xedit_script_filename"]
                    target_plugin_filename = params["target_plugin_filename"]
                    generate_all = params["generate_all"]
                    all_exported_target_bases_by_formid = params["all_exported_target_bases_by_formid"]

                    # Export ALL data from the Target Mod first (only once), regardless of generate_all
                    self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Exporting all data from Target Mod '{target_mod_display_name}'...")
                    
                    target_export_script_options = {
                        "TargetPlugin": target_plugin_filename,
                        "TargetCategory": "", # Empty string to export all categories
                        "Keywords": "",
                        "BroadCategorySwap": "false"
                    }

                    xedit_output_path_target_all = safe_launch_xedit(
                        wrapped_organizer=self.wrapped_organizer, # Pass wrapped_organizer
                        dialog=self.dialog,
                        xedit_path=xedit_exe_path,
                        xedit_mo2_name=xedit_executable_name,
                        script_name=xedit_script_filename,
                        game_version=game_mode_flag,
                        script_options=target_export_script_options,
                        debug_logger=self.wrapped_organizer.log
                    )
                    
                    if not xedit_output_path_target_all:
                        self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: Failed to export target mod data. Aborting YAML generation.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Target Mod. Check xEdit logs for details.")
                        return

                    target_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_target_all, "Target Mod xEdit Export", self.dialog)
                    
                    # Clean up the output JSON from target export after loading
                    try:
                        xedit_output_path_target_all.unlink()
                        self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Cleaned up target export JSON: {xedit_output_path_target_all}")
                    except Exception as e:
                        self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete target export JSON '{xedit_output_path_target_all}': {e}")


                    if not target_exported_json or "baseObjects" not in target_exported_json:
                        self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                        self.dialog.showError("JSON Parse Error", "Target mod xEdit export JSON is empty or malformed. Cannot proceed with YAML generation.")
                        return
                    
                    # Store for use in generate_and_write_skypatcher_yaml
                    self.dialog.all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in target_exported_json.get("baseObjects", []) if "FormID" in obj}


                    if generate_all:
                        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: 'Generate All' selected. Processing all compatible source mods.")
                        all_mods = self.organizer.modList().allMods() # Access original organizer
                        successful_generations = 0
                        
                        # Filter out target mod and game master files from source mods for 'all' generation
                        source_mods_to_process = []
                        for mod_name_internal in all_mods:
                            if self.organizer.modList().state(mod_name_internal) & mobase.ModState.ACTIVE:
                                mod_display_name = self.organizer.modList().displayName(mod_name_internal)
                                if mod_display_name == target_mod_display_name: # Don't process target mod as source
                                    continue
                                
                                # Exclude master files (.esm, .esl) as sources unless specifically requested
                                source_plugin_candidate = self.dialog._get_plugin_name_from_mod_name(mod_display_name, mod_name_internal)
                                if source_plugin_candidate and not (source_plugin_candidate.lower().endswith(".esm") or source_plugin_candidate.lower().endswith(".esl")):
                                    source_mods_to_process.append((mod_display_name, mod_name_internal, source_plugin_candidate))
                                else:
                                    self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Skipping mod '{mod_display_name}' (internal: {mod_name_internal}) as it's a master file or has no main plugin.")

                        if not source_mods_to_process:
                            self.dialog.showWarning("No Source Mods", "No suitable source mods found for 'Generate All'. Skipping.")
                            self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: No suitable source mods found for 'Generate All'.")
                            return

                        self.dialog.showInformation("Starting Batch Generation", f"Generating YAMLs for compatible source mods against target mod '{target_mod_display_name}' for category '{category}'. This may take some time...")

                        for current_source_mod_display_name, current_source_mod_internal_name, source_mod_plugin_filename in source_mods_to_process:
                            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Processing source mod: '{current_source_mod_display_name}' ({source_mod_plugin_filename})...")
                            
                            source_export_script_options = {
                                "TargetPlugin": source_mod_plugin_filename, # This is the plugin we're extracting data FROM
                                "TargetCategory": category,
                                "Keywords": ','.join(keywords),
                                "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                            }
                            
                            # Run xEdit export for the current source mod and specific category
                            xedit_output_path_source = safe_launch_xedit(
                                wrapped_organizer=self.wrapped_organizer, # Pass wrapped_organizer
                                dialog=self.dialog,
                                xedit_path=xedit_exe_path,
                                xedit_mo2_name=xedit_executable_name,
                                script_name=xedit_script_filename,
                                game_version=game_mode_flag,
                                script_options=source_export_script_options,
                                debug_logger=self.wrapped_organizer.log
                            )
                            
                            if xedit_output_path_source:
                                source_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {current_source_mod_display_name}", dialog_instance=self.dialog)
                                
                                # Clean up the output JSON from source export after loading
                                try:
                                    xedit_output_path_source.unlink()
                                    self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                                except Exception as e:
                                    self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
                                
                                if source_exported_json and "baseObjects" in source_exported_json:
                                    generated = generate_and_write_skypatcher_yaml(
                                        wrapped_organizer=self.wrapped_organizer,
                                        json_data=source_exported_json, # Pass the entire json_data with 'baseObjects'
                                        target_mod_name=target_mod_display_name, # This is display name, will be converted internally in generate_and_write_skypatcher_yaml
                                        output_folder_path=output_folder_path,
                                        record_type=category,
                                        broad_category_swap_enabled=broad_category_swap_enabled,
                                        search_keywords=keywords, # Pass keywords for filtering in YAML generation
                                        dialog_instance=self.dialog
                                    )
                                    if generated:
                                        successful_generations += 1
                                else:
                                    self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: xEdit export JSON for '{current_source_mod_display_name}' is empty or malformed. Skipping YAML generation.")
                            else:
                                self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit export failed for source mod '{current_source_mod_display_name}'. Skipping YAML generation.")

                        self.dialog.showInformation("Batch Generation Complete", f"Successfully generated {successful_generations} YAML file(s).")
                        self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Batch YAML generation complete. {successful_generations} files generated.")

                    else: # Single YAML Generation
                        if not source_mod_display_name:
                            self.dialog.showError("Input Error", "Please select a Source Mod for single YAML generation.")
                            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: Source Mod not selected for single YAML generation.")
                            return

                        self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Generating single YAML for '{source_mod_display_name}' targeting '{target_mod_display_name}' for category '{category}'...")

                        source_plugin_filename = self.dialog._get_plugin_name_from_mod_name(source_mod_display_name, self.dialog._get_internal_mod_name_from_display_name(source_mod_display_name))
                        if not source_plugin_filename:
                            self.dialog.showError("Source Mod Error", f"Could not determine plugin file for source mod '{source_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
                            self.wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: Source mod '{source_mod_display_name}' has no primary plugin. Aborting YAML generation.")
                            return

                        # 2. Export data from the Source Mod for the specific category
                        self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Exporting data from Source Mod: {source_mod_display_name} for category {category}...")
                        
                        source_export_script_options = {
                            "TargetPlugin": source_plugin_filename, # This is the plugin we're extracting data FROM
                            "TargetCategory": category,
                            "Keywords": ','.join(keywords),
                            "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                        }

                        xedit_output_path_source = safe_launch_xedit(
                            wrapped_organizer=self.wrapped_organizer, # Pass wrapped_organizer
                            dialog=self.dialog,
                            xedit_path=xedit_exe_path,
                            xedit_mo2_name=xedit_executable_name,
                            script_name=xedit_script_filename,
                            game_version=game_mode_flag,
                            script_options=source_export_script_options,
                            debug_logger=self.wrapped_organizer.log
                        )
                        
                        if not xedit_output_path_source:
                            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: Failed to export source mod data. Aborting YAML generation.")
                            self.dialog.showError("xEdit Export Failed", "Failed to export data from the Source Mod. Check xEdit logs for details.")
                            return

                        source_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {source_mod_display_name}", dialog_instance=self.dialog)
                        
                        # Clean up the output JSON from source export after loading
                        try:
                            xedit_output_path_source.unlink()
                            self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                        except Exception as e:
                            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
                        
                        if not source_exported_json or "baseObjects" not in source_exported_json:
                            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: Source mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                            self.dialog.showError("JSON Parse Error", "Source mod xEdit export JSON is empty or malformed. Cannot generate YAML.")
                            return

                        # 3. Generate and write the YAML
                        generate_and_write_skypatcher_yaml(
                            wrapped_organizer=self.wrapped_organizer,
                            json_data=source_exported_json, # Pass the entire json_data with 'baseObjects'
                            target_mod_name=target_mod_display_name,
                            output_folder_path=output_folder_path,
                            record_type=category,
                            broad_category_swap_enabled=broad_category_swap_enabled,
                            search_keywords=keywords, # Pass keywords for filtering in YAML generation
                            dialog_instance=self.dialog
                        )
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
                # If dialog itself failed to create, use QMessageBox directly
                # QApplication is still needed if QMessageBox is used without a parent.
                # Re-adding a basic QApplication check if not already handled by MO2's env.
                # If MO2 guarantees a QApplication, this can be removed.
                # Given MO2 is a Qt app, QApplication.instance() should usually exist.
                # We'll just rely on the try/except for the QMessageBox as a fallback.
                QMessageBox.critical(None, "Plugin Error", f"An unexpected error occurred during dialog creation: {e}\nCheck the SkyGen debug log for details.")

    def _determine_xedit_paths(self):
        """
        Determines and stores the xEdit executable path and MO2 registered name.
        Called once during __init__.
        """
        # Pass self.dialog here for UI error reporting if xEdit path determination fails
        xedit_info = get_xedit_exe_path(self.wrapped_organizer, self.dialog)
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
def createPlugin(organizer):
    """
    This function is automatically called by MO2 to create an instance of your plugin.
    It MUST accept the 'organizer' argument.
    """
    # Use the logger defined at the top of the file
    skygen_logger.info("SkyGen Plugin: createPlugin function called with organizer.")
    return SkyGenPlugin(organizer)

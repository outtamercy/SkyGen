# __init__.py (This is your main plugin file)

import mobase
import json
from pathlib import Path
from typing import Optional, Any
import logging
import os

# Define the path for the plugin's debug log file (used by OrganizerWrapper)
plugin_log_path = os.path.join(os.path.dirname(__file__), 'skygen_plugin_debug.log')

# Get the logger instance for SkyGen. This logger will be configured by OrganizerWrapper.
skygen_logger = logging.getLogger('skygen')
skygen_logger.setLevel(logging.DEBUG) # Set overall logging level for SkyGen

# IMPORTANT: REMOVED THE REDUNDANT INITIAL FILEHANDLER SETUP HERE.
# The OrganizerWrapper.set_log_file_path method (which calls make_file_logger)
# will now be the SOLE responsible party for setting up and managing
# the file handler on 'skygen_logger'. This ensures a single,
# well-managed file handler across the plugin's lifecycle and prevents conflicts.

skygen_logger.info("SkyGen plugin logger initialized (initial global setup). This message may go to console initially if file handler is not yet set by OrganizerWrapper, but subsequent logs will go to file.")


# Import UI and utility functions
from .skygen_ui import SkyGenToolDialog, OrganizerWrapper
from .skygen_file_utilities import (
    load_json_data,
    get_xedit_exe_path,
    safe_launch_xedit, # Using safe_launch_xedit directly
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
    get_game_root_path_from_general_ini,
    make_file_logger, # Import make_file_logger as it's needed by OrganizerWrapper
)

# Import MO2_LOG_* constants from the new constants file
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
)


class SkyGenPlugin(mobase.IPluginTool):
    """
    The main plugin class for SkyGen, integrating with Mod Organizer 2.
    """

    def __init__(self):
        # Call the base class constructor. For IPluginTool, init(organizer) is called by MO2.
        super().__init__() 
        self.organizer: Optional[mobase.IOrganizer] = None
        self.wrapped_organizer: Optional[OrganizerWrapper] = None
        self.dialog: Optional[SkyGenToolDialog] = None
        self._xedit_exe_path: Optional[Path] = None
        self._xedit_mo2_name: str = ""
        skygen_logger.info("SkyGenPlugin instance created (Python __init__ method).")


    def init(self, organizer: mobase.IOrganizer):
        """
        Initializes the plugin with the Mod Organizer 2 organizer instance.
        This method is called by MO2 for IPluginTool implementations.
        """
        self.organizer = organizer
        self.wrapped_organizer = OrganizerWrapper(self.organizer) 
        
        self.wrapped_organizer.log(MO2_LOG_DEBUG, "SkyGen: Organizer object assigned and wrapped in init method.")

        # Set up the log file path using the wrapped organizer's method.
        # This call will now use the make_file_logger from skygen_file_utilities.py
        # to properly configure the shared 'skygen_logger'.
        log_file_path_for_wrapper = Path(self.wrapped_organizer.pluginDataPath()) / "SkyGen" / "skygen_plugin_debug.log"
        self.wrapped_organizer.set_log_file_path(log_file_path_for_wrapper)
        
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen plugin init method called and log path set.")
        
        # Determine and store xEdit paths early
        self._determine_xedit_paths()

        # Initialize the dialog here but don't show it yet
        self.dialog = SkyGenToolDialog(self.wrapped_organizer)
        self.wrapped_organizer.dialog_instance = self.dialog # Set dialog_instance for direct UI error display from wrapper

        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen plugin initialized successfully within MO2 (from init method).")
        return True # Indicate successful initialization


    def name(self):
        return "SkyGen"

    def author(self):
        return "BoltBot & Mayhem"

    def description(self):
        return "Automate SkyPatcher YAML and BOS INI generation."

    def version(self):
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)

    def url(self):
        return "https://github.com/outtamercy/SkyGen"

    def displayName(self): 
        return self.name()

    def settings(self):
        return []

    def display(self):
        # Ensure organizer is available. This should always be true if init() was called.
        if not self.wrapped_organizer:
            skygen_logger.critical("SkyGen: ERROR: display() called before init() or wrapped_organizer is None.")
            # Fallback for critical error if wrapped_organizer isn't ready
            try:
                from PyQt6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance()
                if not app:
                    app = QApplication([])
                QMessageBox.critical(None, "Plugin Error", "SkyGen internal error: Plugin not fully initialized. Please report this issue and check MO2 logs.")
            except ImportError:
                print("SkyGen: CRITICAL ERROR (no UI): Plugin not initialized.")
            return

        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Display method called, showing dialog.")

        try:
            self.dialog._populate_game_versions() 

            self.dialog.determined_xedit_exe_path = self._xedit_exe_path
            self.dialog.determined_xedit_executable_name = self._xedit_mo2_name

            result = self.dialog.exec()

            if result == mobase.QDialog.Accepted:
                self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Dialog accepted. Processing request.")
                selected_output_type = self.dialog.selected_output_type
                
                self.dialog._save_config()

                if selected_output_type == "SkyPatcher YAML":
                    self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Processing SkyPatcher YAML generation.")
                    params = self.dialog._generate_skypatcher_yaml_internal()
                    
                    if not params:
                        self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: Parameter gathering for YAML generation failed. Aborting.")
                        return

                    target_mod_display_name = params["target_mod_display_name"]
                    source_mod_display_name = params["source_mod_display_name"]
                    category = params["category"]
                    keywords = params["keywords"]
                    broad_category_swap_enabled = params["broad_category_swap_enabled"]
                    output_folder_path = params["output_folder_path"]
                    game_mode_flag = params["game_mode_flag"]
                    xedit_exe_path = params["xedit_exe_path"]
                    xedit_executable_name = params["xedit_executable_name"]
                    xedit_script_filename = params["xedit_script_filename"]
                    target_plugin_filename = params["target_plugin_filename"]
                    generate_all = params["generate_all"]
                    all_exported_target_bases_by_formid = params["all_exported_target_bases_by_formid"]

                    if generate_all:
                        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: 'Generate All' selected. Processing all compatible source mods.")
                        all_mods = self.organizer.modList().allMods()
                        successful_generations = 0
                        
                        source_mods_to_process = []
                        for mod_name_internal in all_mods:
                            if self.organizer.modList().state(mod_name_internal) & mobase.ModState.ACTIVE:
                                mod_display_name = self.organizer.modList().displayName(mod_name_internal)
                                if mod_display_name == target_mod_display_name:
                                    continue
                                
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
                                "TargetPlugin": source_mod_plugin_filename,
                                "TargetCategory": category,
                                "Keywords": ','.join(keywords),
                                "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                            }
                            
                            xedit_output_path_source = safe_launch_xedit(
                                wrapped_organizer=self.wrapped_organizer,
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
                                
                                try:
                                    xedit_output_path_source.unlink()
                                    self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                                except Exception as e:
                                    self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}", exc_info=True)
                                
                                if source_exported_json and "baseObjects" in source_exported_json:
                                    generated = generate_and_write_skypatcher_yaml(
                                        wrapped_organizer=self.wrapped_organizer,
                                        json_data=source_exported_json,
                                        target_mod_name=target_mod_display_name,
                                        output_folder_path=output_folder_path,
                                        record_type=category,
                                        broad_category_swap_enabled=broad_category_swap_enabled,
                                        search_keywords=keywords,
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
                            "TargetPlugin": source_plugin_filename,
                            "TargetCategory": category,
                            "Keywords": ','.join(keywords),
                            "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                        }

                        xedit_output_path_source = safe_launch_xedit(
                            wrapped_organizer=self.wrapped_organizer,
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
                        
                        try:
                            xedit_output_path_source.unlink()
                            self.wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                        except Exception as e:
                            self.wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}", exc_info=True)
                        
                        if not source_exported_json or "baseObjects" not in source_exported_json:
                            self.wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: Source mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                            self.dialog.showError("JSON Parse Error", "Source mod xEdit export JSON is empty or malformed. Cannot generate YAML.")
                            return

                        # 3. Generate and write the YAML
                        generate_and_write_skypatcher_yaml(
                            wrapped_organizer=self.wrapped_organizer,
                            json_data=source_exported_json,
                            target_mod_name=target_mod_display_name,
                            output_folder_path=output_folder_path,
                            record_type=category,
                            broad_category_swap_enabled=broad_category_swap_enabled,
                            search_keywords=keywords,
                            dialog_instance=self.dialog
                        )
                elif selected_output_type == "BOS INI":
                    self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Processing BOS INI generation.")
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
                try:
                    from PyQt6.QtWidgets import QApplication, QMessageBox
                    app = QApplication.instance()
                    if not app:
                        app = QApplication([])
                    QMessageBox.critical(None, "Plugin Error", f"An unexpected error occurred during dialog creation: {e}\nCheck the SkyGen debug log for details.")
                except ImportError:
                    print(f"SkyGen: CRITICAL ERROR (no UI): An unexpected error occurred during dialog creation: {e}")


    def _determine_xedit_paths(self):
        """
        Determines and stores the xEdit executable path and MO2 registered name.
        Called once during init.
        """
        if not self.wrapped_organizer or not self.dialog:
            skygen_logger.critical("SkyGen: Cannot determine xEdit paths: wrapped_organizer or dialog not initialized.")
            return

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
        if self.organizer: # Use self.organizer, which is set in init()
            return self.organizer.qtTr(str_, self.name())
        return str_

    def deinit(self):
        """
        Called by MO2 when the plugin is being unloaded.
        Ensures the custom debug log file is properly closed.
        """
        if self.wrapped_organizer: # Ensure wrapped_organizer exists before using it
            self.wrapped_organizer.close_log_file()
            self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen plugin deinitialized.")
        return True

# This function is automatically called by MO2 to create an instance of your plugin.
def createPlugin(): # Corrected: No arguments for IPluginTool
    """
    This function is automatically called by MO2 to create an instance of your plugin.
    It takes no arguments for IPluginTool.
    """
    skygen_logger.info("SkyGen Plugin: createPlugin function called.")
    return SkyGenPlugin() # Return an instance of the plugin

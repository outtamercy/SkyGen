# __init__.py (This is your main plugin file)

import mobase
import json
from pathlib import Path
from typing import Optional, Any

# Import UI and utility functions.
# IMPORTANT: Removed direct import of generate_bos_ini_files and generate_and_write_skypatcher_yaml
# to prevent circular dependency issues during module loading.
# They will now be accessed via skygen_file_utilities.function_name.
from .skygen_ui import SkyGenToolDialog, OrganizerWrapper
from . import skygen_file_utilities # Import the module directly

# Ensure necessary PyQt6 modules are imported for the main plugin if still used here,
# or for dummy QMessageBox if needed for initial checks.
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import Qt
except ImportError:
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
        # Define DialogCode for dummy class to match PyQt6 structure
        class DialogCode:
            Accepted = 1 # QDialog.Accepted enum value
            Rejected = 0 # QDialog.Rejected enum value
        
        def __init__(self, *args, **kwargs): pass
        def exec(self): return self.DialogCode.Accepted # Return Accepted by default for dummy
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
        self.wrapped_organizer: Optional[OrganizerWrapper] = None
        self.dialog: Optional[SkyGenToolDialog] = None
        self._debug_log_path: Optional[Path] = None

    def init(self, organizer: mobase.IOrganizer):
        self.organizer = organizer
        self.wrapped_organizer = OrganizerWrapper(organizer)
        
        self._debug_log_path = Path(self.organizer.pluginDataPath()) / "SkyGen" / "SkyGen_Debug.log"
        self.wrapped_organizer.set_log_file_path(self._debug_log_path)
        self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Plugin initializing.")
        
        self.dialog = SkyGenToolDialog(self.wrapped_organizer)
        self.wrapped_organizer.dialog_instance = self.dialog # Pass dialog instance for direct error showing
        
        # Use skygen_file_utilities.get_xedit_exe_path for detection
        xedit_paths = skygen_file_utilities.get_xedit_exe_path(self.wrapped_organizer, self.dialog)
        if xedit_paths:
            self.dialog.determined_xedit_exe_path, self.dialog.determined_xedit_executable_name = xedit_paths
            self.wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Detected xEdit at: {self.dialog.determined_xedit_exe_path} (MO2 Name: {self.dialog.determined_xedit_executable_name})")
        else:
            self.wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: xEdit not automatically detected during plugin init.")
        
        return True

    def name(self):
        return "SkyGen"

    def displayName(self):
        return self.name()

    def icon(self): # Added icon method
        return QIcon()

    def tooltip(self): # Added tooltip method
        return self.description() # A reasonable default for the tooltip

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
        # Use skygen_file_utilities.get_xedit_exe_path for detection
        xedit_paths = skygen_file_utilities.get_xedit_exe_path(self.wrapped_organizer, self.dialog)
        if xedit_paths:
            self.dialog.determined_xedit_exe_path, self.dialog.determined_xedit_executable_name = xedit_paths
        
        result = self.dialog.exec()

        if result == QDialog.DialogCode.Accepted: # Corrected for PyQt6
            self.wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Dialog accepted by user. Proceeding with generation.")
            
            output_type = self.dialog.selected_output_type
            output_folder_path = Path(self.dialog.output_folder_path)

            if output_type == "SkyPatcher YAML":
                self.wrapped_organizer.log(1, "SkyGen: Generating SkyPatcher YAML files...")
                self._generate_skypatcher_yaml_logic(
                    target_mod_display_name=self.dialog.selected_target_mod_name,
                    source_mod_display_name=self.dialog.selected_source_mod_name,
                    category=self.dialog.selected_category,
                    keywords_str=self.dialog.keywords_lineEdit.text(),
                    broad_category_swap_enabled=self.dialog.broad_category_swap_checkbox.isChecked(),
                    generate_all=self.dialog.generate_all_checkbox.isChecked(),
                    output_folder_path=output_folder_path,
                    game_version=self.dialog.selected_game_version
                )
            elif output_type == "BOS INI":
                self.wrapped_organizer.log(1, "SkyGen: Generating BOS INI files...")
                igpc_json_path = Path(self.dialog.igpc_json_path)

                if not igpc_json_path.is_file():
                    self.dialog.showError("Input Error", "IGPC JSON file not found at the specified path.")
                    self.wrapped_organizer.log(3, f"SkyGen: IGPC JSON file not found: {igpc_json_path}")
                    return

                # Use skygen_file_utilities.load_json_data
                igpc_data = skygen_file_utilities.load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=igpc_json_path, description="IGPC JSON", dialog_instance=self.dialog)
                if igpc_data:
                    # Use skygen_file_utilities.generate_bos_ini_files
                    skygen_file_utilities.generate_bos_ini_files(wrapped_organizer=self.wrapped_organizer, igpc_data=igpc_data, output_folder_path=output_folder_path, dialog_instance=self.dialog)
                else:
                    self.wrapped_organizer.log(3, "SkyGen: Failed to load IGPC data. Aborting BOS INI generation.")
        else:
            self.wrapped_organizer.log(1, "SkyGen: Dialog cancelled by user. No action taken.")

    def __tr(self, str_: str) -> str:
        """Translates a string using MO2's translation mechanism."""
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

    def _get_internal_mod_name_from_display_name(self, display_name: str) -> Optional[str]:
        """
        Retrieves the internal (folder) name of a mod from its display name.
        This helper is now part of the tool.
        """
        mod_list = self.wrapped_organizer.modList()
        for mod_internal_name in mod_list.allMods():
            if mod_list.displayName(mod_internal_name) == display_name:
                return mod_internal_name
        return None

    def _get_plugin_name_from_mod_name(self, mod_display_name: str, mod_internal_name: str) -> Optional[str]:
        """
        Attempts to find the primary plugin file (.esp, .esm, .esl) for a given mod.
        This helper is now part of the tool.
        """
        mod_obj = self.wrapped_organizer.modList().getMod(mod_internal_name) 
        if not mod_obj:
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Could not find IMod object for '{mod_display_name}' ({mod_internal_name}).")
            return None

        mod_path = Path(mod_obj.absolutePath())
        if not mod_path.is_dir():
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Mod directory for '{mod_display_name}' ({mod_internal_name}) not found at: {mod_path}.")
            return None

        plugin_files = list(mod_path.glob("*.esm")) + \
                       list(mod_path.glob("*.esp")) + \
                       list(mod_path.glob("*.esl"))
        
        for p_file in plugin_files:
            if p_file.stem.lower() == mod_internal_name.lower():
                self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found exact plugin match for '{mod_display_name}': {p_file.name}")
                return p_file.name

        if len(plugin_files) == 1:
            self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Found single plugin file for '{mod_display_name}': {plugin_files[0].name}")
            return plugin_files[0].name
        elif plugin_files:
            sorted_plugins = sorted(plugin_files, key=lambda p: p.name.lower())
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Multiple plugin files found for '{mod_display_name}' and no exact match. Picking '{sorted_plugins[0].name}'.")
            return sorted_plugins[0].name
        
        self.wrapped_organizer.log(2, f"SkyGen: WARNING: No plugin file (.esp, .esm, .esl) found for active mod '{mod_display_name}' ({mod_internal_name}).")
        return None

    def _generate_skypatcher_yaml_logic(
        self,
        target_mod_display_name: str,
        source_mod_display_name: str,
        category: str,
        keywords_str: str,
        broad_category_swap_enabled: bool,
        generate_all: bool,
        output_folder_path: Path,
        game_version: str
    ):
        """
        Encapsulates the SkyPatcher YAML generation logic.
        Moved from skygen_ui.py to centralize logic.
        """
        self.wrapped_organizer.log(1, "SkyGen: Starting SkyPatcher YAML generation (internal logic).")

        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]

        if not target_mod_display_name:
            self.dialog.showError("Input Error", "Please select a Target Mod.")
            self.wrapped_organizer.log(3, "SkyGen: Target Mod not selected. Aborting YAML generation.")
            return

        if not category:
            self.dialog.showError("Input Error", "Please select or enter a Category (Record Type).")
            self.wrapped_organizer.log(3, "SkyGen: Category not selected. Aborting YAML generation.")
            return

        game_mode_arg_for_xedit = "" # Renamed variable for clarity in this context
        if game_version == "SkyrimSE":
            game_mode_arg_for_xedit = "SE"
        elif game_version == "SkyrimVR":
            game_mode_arg_for_xedit = "VR"
        else:
            self.dialog.showError("Game Version Error", "Could not determine game version. Please select SkyrimSE/AE or SkyrimVR.")
            self.wrapped_organizer.log(4, "SkyGen: ERROR: Invalid or unselected game version.")
            return

        if not self.dialog.determined_xedit_exe_path or not self.dialog.determined_xedit_executable_name:
            self.dialog.showError("xEdit Not Configured", "xEdit executable not found or configured. Please add it to MO2's executables and restart SkyGen.")
            self.wrapped_organizer.log(4, "SkyGen: CRITICAL: xEdit not found. Aborting generation.")
            return

        xedit_script_filename = "ExportPluginData.pas"

        if not output_folder_path.is_dir():
            try:
                output_folder_path.mkdir(parents=True, exist_ok=True)
                self.wrapped_organizer.log(1, f"SkyGen: Created output directory: {output_folder_path}")
            except Exception as e:
                self.dialog.showError("Directory Creation Error", f"Failed to create output directory: {output_folder_path}\n{e}")
                self.wrapped_organizer.log(4, f"SkyGen: ERROR: Failed to create output directory {output_folder_path}: {e}")
                return

        target_plugin_filename = self._get_plugin_name_from_mod_name(target_mod_display_name, self._get_internal_mod_name_from_display_name(target_mod_display_name))
        if not target_plugin_filename:
            self.dialog.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
            self.wrapped_organizer.log(3, f"SkyGen: Target mod '{target_mod_display_name}' has no primary plugin. Aborting YAML generation.")
            return

        self.wrapped_organizer.log(1, f"SkyGen: Exporting all data from Target Mod '{target_mod_display_name}' for comparison...")
        
        # Script options for exporting ALL data from the target mod for comparison
        target_export_script_options = {
            "TargetPlugin": target_plugin_filename,
            "TargetCategory": "", # Empty category means export all records from this plugin
            "Keywords": "",       # No keyword filtering for the full export
            "BroadCategorySwap": "false" # Not relevant for full export
        }

        # Use skygen_file_utilities.safe_launch_xedit
        xedit_output_path_target_all = skygen_file_utilities.safe_launch_xedit(
            self.wrapped_organizer,
            self.dialog,
            self.dialog.determined_xedit_exe_path,
            self.dialog.determined_xedit_executable_name,
            xedit_script_filename,
            game_version, # Pass game_version, not game_mode_flag here
            target_export_script_options,
            self.wrapped_organizer.log
        )
        
        if not xedit_output_path_target_all:
            self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export target mod data. Aborting YAML generation.")
            self.dialog.showError("xEdit Export Failed", "Failed to export data from the Target Mod for comparison. Check xEdit logs for details.")
            return

        # Use skygen_file_utilities.load_json_data
        target_exported_json = skygen_file_utilities.load_json_data(self.wrapped_organizer, xedit_output_path_target_all, "Target Mod xEdit Export", self.dialog)
        
        try:
            xedit_output_path_target_all.unlink()
            self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up target export JSON: {xedit_output_path_target_all}")
        except Exception as e:
            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete target export JSON '{xedit_output_path_target_all}': {e}")

        if not target_exported_json or "baseObjects" not in target_exported_json:
            self.wrapped_organizer.log(3, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
            self.dialog.showError("JSON Parse Error", "Target mod xEdit export JSON is empty or malformed. Cannot proceed with YAML generation.")
            return
        
        # Crucial step: Populate the dialog's attribute that holds all target base objects for comparison
        self.dialog.all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in target_exported_json.get("baseObjects", []) if "FormID" in obj}


        if generate_all:
            self.wrapped_organizer.log(1, "SkyGen: 'Generate All' selected. Processing all compatible source mods.")
            all_mods = self.wrapped_organizer.modList().allMods()
            successful_generations = 0
            
            source_mods_to_process = []
            for mod_name_internal in all_mods:
                if self.wrapped_organizer.modList().state(mod_name_internal) & mobase.ModState.ACTIVE:
                    mod_display_name = self.wrapped_organizer.modList().displayName(mod_name_internal)
                    if mod_display_name == target_mod_display_name:
                        continue # Skip the target mod itself
                    
                    source_plugin_candidate = self._get_plugin_name_from_mod_name(mod_display_name, mod_name_internal)
                    # Only process if it has a plugin and is not an ESM (master file) or ESL (light master)
                    if source_plugin_candidate and not (source_plugin_candidate.lower().endswith(".esm") or source_plugin_candidate.lower().endswith(".esl")):
                        source_mods_to_process.append((mod_display_name, mod_name_internal, source_plugin_candidate))
                    else:
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping mod '{mod_display_name}' (internal: {mod_name_internal}) as it's a master file, ESL, or has no main plugin.")

            if not source_mods_to_process:
                self.dialog.showWarning("No Source Mods", "No suitable source mods found for 'Generate All' (must be active ESPs). Skipping.")
                self.wrapped_organizer.log(2, "SkyGen: No suitable source mods found for 'Generate All'.")
                return

            self.dialog.showInformation("Starting Batch Generation", f"Generating YAMLs for compatible source mods against target mod '{target_mod_display_name}' for category '{category}'. This may take some time...")

            for current_source_mod_display_name, current_source_mod_internal_name, source_mod_plugin_filename in source_mods_to_process:
                self.wrapped_organizer.log(1, f"SkyGen: Processing source mod: '{current_source_mod_display_name}' ({source_mod_plugin_filename})...")
                
                source_export_script_options = {
                    "TargetPlugin": source_mod_plugin_filename,
                    "TargetCategory": category,
                    "Keywords": ','.join(keywords),
                    "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                }
                
                # Use skygen_file_utilities.safe_launch_xedit
                xedit_output_path_source = skygen_file_utilities.safe_launch_xedit(
                    self.wrapped_organizer,
                    self.dialog,
                    self.dialog.determined_xedit_exe_path,
                    self.dialog.determined_xedit_executable_name,
                    xedit_script_filename,
                    game_version, # Pass game_version
                    source_export_script_options,
                    self.wrapped_organizer.log
                )
                
                if xedit_output_path_source:
                    # Use skygen_file_utilities.load_json_data
                    source_exported_json = skygen_file_utilities.load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {current_source_mod_display_name}", dialog_instance=self.dialog)
                    
                    try:
                        xedit_output_path_source.unlink()
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                    except Exception as e:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
                    
                    if source_exported_json and "baseObjects" in source_exported_json:
                        # Use skygen_file_utilities.generate_and_write_skypatcher_yaml
                        generated = skygen_file_utilities.generate_and_write_skypatcher_yaml(
                            wrapped_organizer=self.wrapped_organizer,
                            json_data=source_exported_json,
                            target_mod_name=target_mod_display_name,
                            output_folder_path=output_folder_path,
                            record_type=category,
                            broad_category_swap_enabled=broad_category_swap_enabled,
                            search_keywords=keywords,
                            dialog_instance=self.dialog # <--- ADDED THIS LINE
                        )
                        if generated:
                            successful_generations += 1
                    else:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: xEdit export JSON for '{current_source_mod_display_name}' is empty or malformed. Skipping YAML generation.")
                else:
                    self.wrapped_organizer.log(3, f"SkyGen: ERROR: xEdit export failed for source mod '{current_source_mod_display_name}'. Skipping YAML generation.")

            self.dialog.showInformation("Batch Generation Complete", f"Successfully generated {successful_generations} YAML file(s).")
            self.wrapped_organizer.log(1, f"SkyGen: Batch YAML generation complete. {successful_generations} files generated.")

        else: # Single YAML Generation
            if not source_mod_display_name:
                self.dialog.showError("Input Error", "Please select a Source Mod for single YAML generation.")
                self.wrapped_organizer.log(3, "SkyGen: Source Mod not selected for single YAML generation.")
                return

            self.wrapped_organizer.log(1, f"SkyGen: Generating single YAML for '{source_mod_display_name}' targeting '{target_mod_display_name}' for category '{category}'...")

            source_plugin_filename = self._get_plugin_name_from_mod_name(source_mod_display_name, self._get_internal_mod_name_from_display_name(source_mod_display_name))
            if not source_plugin_filename:
                self.dialog.showError("Source Mod Error", f"Could not determine plugin file for source mod '{source_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
                self.wrapped_organizer.log(3, f"SkyGen: Source mod '{source_mod_display_name}' has no primary plugin. Aborting YAML generation.")
                return

            self.wrapped_organizer.log(1, f"SkyGen: Exporting data from Source Mod: {source_mod_display_name} for category {category}...")
            
            source_export_script_options = {
                "TargetPlugin": source_plugin_filename,
                "TargetCategory": category,
                "Keywords": ','.join(keywords),
                "BroadCategorySwap": str(broad_category_swap_enabled).lower()
            }

            # Use skygen_file_utilities.safe_launch_xedit
            xedit_output_path_source = skygen_file_utilities.safe_launch_xedit(
                self.wrapped_organizer,
                self.dialog,
                self.dialog.determined_xedit_exe_path,
                self.dialog.determined_xedit_executable_name,
                xedit_script_filename,
                game_version, # Pass game_version
                source_export_script_options,
                self.wrapped_organizer.log
            )
            
            if not xedit_output_path_source:
                self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export source mod data. Aborting YAML generation.")
                self.dialog.showError("xEdit Export Failed", "Failed to export data from the Source Mod. Check xEdit logs for details.")
                return

            # Use skygen_file_utilities.load_json_data
            source_exported_json = skygen_file_utilities.load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {source_mod_display_name}", dialog_instance=self.dialog)
            
            try:
                xedit_output_path_source.unlink()
                self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
            except Exception as e:
                self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
            
            if not source_exported_json or "baseObjects" not in source_exported_json:
                self.wrapped_organizer.log(3, "SkyGen: ERROR: Source mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                self.dialog.showError("JSON Parse Error", "Source mod xEdit export JSON is empty or malformed. Cannot generate YAML.")
                return

            # Use skygen_file_utilities.generate_and_write_skypatcher_yaml
            skygen_file_utilities.generate_and_write_skypatcher_yaml(
                wrapped_organizer=self.wrapped_organizer,
                json_data=source_exported_json,
                target_mod_name=target_mod_display_name,
                output_folder_path=output_folder_path,
                record_type=category,
                broad_category_swap_enabled=broad_category_swap_enabled,
                search_keywords=keywords,
                dialog_instance=self.dialog # <--- ADDED THIS LINE
            )

# IMPORTANT: This function MUST be at the global scope for MO2 to find it.
def createPlugin():
    return SkyGenGeneratorTool()

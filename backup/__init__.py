# __init__.py (This is your main plugin file, formerly plugin.py)

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
    run_xedit_export,
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
    clean_temp_script_and_ini,
    get_game_root_from_general_ini,
    detect_root_mode,
)

# Ensure necessary PyQt6 modules are imported for the main plugin if still used here,
# or for dummy QMessageBox if needed for initial checks.
# Only import what's strictly necessary for *this* file's display method or plugin tool.
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog # Import QDialog here
    from PyQt6.QtGui import QIcon # QIcon is used by the plugin tool directly
except ImportError:
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


def createPlugin() -> mobase.IPluginTool:
    return SkyGenGeneratorTool()


class SkyGenGeneratorTool(mobase.IPluginTool):
    """
    MO2 Plugin Tool for SkyGen, allowing generation of SkyPatcher YAMLs or BOS INIs.
    """

    def __init__(self):
        super().__init__()
        self.mobase = mobase # Store mobase reference
        self.organizer = None # Will be set by init method
        self.wrapped_organizer = None # Custom wrapper for logging
        self.dialog = None # UI dialog instance
        self.xedit_exe_path = Path("")
        self.xedit_mo2_name = ""
        self.game_root_path = Path("")

    def init(self, organizer: mobase.IOrganizer):
        """Initializes the plugin with the MO2 organizer."""
        self.organizer = organizer
        self.wrapped_organizer = OrganizerWrapper(organizer) # Initialize the wrapper
        
        # Ensure the plugin's data directory exists
        # MODIFIED: Changed from pluginDataPath() to basePath() / "plugins"
        plugin_data_dir = Path(self.organizer.basePath()) / "plugins" / "SkyGen" 
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        
        self.wrapped_organizer.set_log_file_path(plugin_data_dir / "SkyGen_Debug.log")
        self.wrapped_organizer.log(1, "SkyGen: Plugin initialized.")
        return True

    def name(self):
        return "SkyGen"

    def displayName(self):
        """Returns the display name for the plugin in MO2."""
        return self.name() # Returns the same name as the 'name' method

    def author(self):
        return "Your Name" # Replace with your name

    def description(self):
        return "A tool to generate SkyPatcher YAML files or BOS INI files based on xEdit exports."

    def version(self):
        return mobase.Version(1, 0, 0, mobase.ReleaseType.FINAL)

    def isActive(self):
        return self.organizer.pluginList().isActive("SkyGen") # Assuming the plugin is named SkyGen

    def settings(self):
        # No specific settings for MO2's plugin list itself, managed via config.json
        return []

    def icon(self):
        """
        Returns the icon for the plugin in MO2.
        Required by mobase.IPluginTool.
        """
        return QIcon() # Return an empty QIcon if no specific icon is provided

    def tooltip(self):
        """
        Returns the tooltip text for the plugin in MO2.
        Required by mobase.IPluginTool.
        """
        return "Generate SkyPatcher YAMLs or BOS INIs"

    def display(self):
        """
        Displays the main UI dialog and handles the generation process based on user input.
        """
        # Create the dialog with the wrapped organizer
        self.dialog = SkyGenToolDialog(self.wrapped_organizer)

        # Get initial config data for path lookup before showing the dialog
        class DummyMessageBox:
            def showError(self, title, message):
                self.wrapped_organizer.log(3, f"SkyGen: Initial Config Error - {title}: {message}")
        
        temp_msg_box = DummyMessageBox()

        # CORRECTED: Use self.organizer.basePath() / "plugins" / "SkyGen" for config.json
        config_file_path = Path(self.organizer.basePath()) / "plugins" / "SkyGen" / "config.json"
        
        config_data_for_path_lookup = {}
        if config_file_path.is_file():
            try:
                with open(config_file_path, "r", encoding="utf-8") as f:
                    config_data_for_path_lookup = json.load(f)
            except Exception as e:
                self.wrapped_organizer.log(3, f"SkyGen: ERROR: Could not load config.json for path lookup from '{config_file_path}': {e}")
                # Don't show dialog error here, as dialog might not be fully initialized yet
        
        # Determine xEdit path and game root path
        # MODIFIED: Added self.dialog.selected_game_version to the call
        self.xedit_exe_path, self.xedit_mo2_name = get_xedit_exe_path(
            config_data_for_path_lookup, 
            self.wrapped_organizer,
            self.dialog,
            self.dialog.selected_game_version # Pass the selected game version
        )
        if not self.xedit_exe_path or not self.xedit_mo2_name:
            self.wrapped_organizer.log(3, "SkyGen: xEdit executable not found. Aborting display.")
            self.dialog.showError("xEdit Not Found", "Could not determine xEdit executable path or MO2 name. Please configure it in config.json or ensure it's in your MO2 executables.")
            return

        self.game_root_path = get_game_root_from_general_ini(
            self.wrapped_organizer,
            config_data_for_path_lookup
        )
        if not self.game_root_path:
            self.wrapped_organizer.log(3, "SkyGen: Game root path not found. Aborting display.")
            self.dialog.showError("Game Root Not Found", "Could Could not determine game root path. Please ensure 'gamePath' is configured in your ModOrganizer.ini or config.json.")
            return

        # Pass determined paths to the dialog after it's initialized but before it's shown
        self.dialog.determined_xedit_exe_path = self.xedit_exe_path
        self.dialog.determined_xedit_executable_name = self.xedit_mo2_name
        self.dialog.game_root_path = self.game_root_path

        # If the dialog is accepted (Generate button clicked)
        if self.dialog.exec() == 1: # QDialog.Accepted is typically 1, use direct integer for robustness
            self.wrapped_organizer.log(1, "SkyGen: Dialog accepted. Starting generation process.")
            
            # Retrieve values from dialog
            selected_output_type = self.dialog.selected_output_type
            output_folder_path = Path(self.dialog.output_folder_path)

            # Define the Pascal script filename (not full path, as it's written inside xEdit's script dir)
            xedit_script_filename = "ExportPluginData.pas" # Only store the filename
            
            if selected_output_type == "SkyPatcher YAML":
                self.wrapped_organizer.log(1, "SkyGen: Generating SkyPatcher YAML...")
                category = self.dialog.selected_category
                target_mod_display_name = self.dialog.selected_target_mod_name
                source_mod_display_name = self.dialog.selected_source_mod_name
                pre_exported_xedit_json_path = self.dialog.pre_exported_xedit_json_path
                broad_category_swap_enabled = self.dialog.broad_category_swap_checkbox.isChecked()
                keywords = self.dialog.keywords_lineEdit.text().strip()

                if self.dialog.generate_all:
                    # Get all active mods to iterate through
                    all_active_mods = []
                    for mod_name in self.organizer.modList().allMods():
                        if self.organizer.modList().state(mod_name) & mobase.ModState.ACTIVE:
                            all_active_mods.append(self.organizer.modList().displayName(mod_name))
                    all_active_mods.sort(key=str.lower)

                    # Filter out target mod and game master files from source mods for 'all' generation
                    source_mods_for_all = [
                        mod_name for mod_name in all_active_mods 
                        if mod_name != target_mod_display_name and 
                        not mod_name.lower().endswith((".esm", ".esl")) # Exclude master files
                    ]
                    
                    if not source_mods_for_all:
                        self.dialog.showWarning("No Source Mods", "No suitable source mods found for 'Generate All'. Skipping.")
                        self.wrapped_organizer.log(2, "SkyGen: No suitable source mods found for 'Generate All'.")
                        return

                    successful_generations = 0

                    # 1. Export ALL data from the Target Mod first (only once)
                    self.wrapped_organizer.log(1, f"SkyGen: Exporting all data from Target Mod '{target_mod_display_name}' for 'Generate All' operation...")
                    target_plugin_filename = self.dialog._get_plugin_name_from_mod_name(target_mod_display_name, self.dialog._get_internal_mod_name_from_display_name(target_mod_display_name))
                    if not target_plugin_filename:
                        self.wrapped_organizer.log(3, f"SkyGen: ERROR: Could not determine plugin filename for target mod: {target_mod_display_name}. Aborting 'Generate All'.")
                        self.dialog.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_display_name}'. Please ensure it's active and contains a plugin.")
                        # Updated cleanup call with correct output path and script filename
                        clean_temp_script_and_ini(self.xedit_exe_path, output_folder_path / "SkyGen_xEdit_Export.json", xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
                        return

                    # For "Generate All", the target mod export should capture ALL categories, not a specific one
                    xedit_output_path_target_all = run_xedit_export(
                        wrapped_organizer=self.wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=self.xedit_exe_path,
                        xedit_mo2_name=self.xedit_mo2_name,
                        game_root_path=self.game_root_path,
                        xedit_script_filename=xedit_script_filename, # CHANGED
                        output_base_dir=output_folder_path,
                        target_plugin_filename=target_plugin_filename,
                        game_version=self.dialog.selected_game_version,
                        target_mod_display_name=target_mod_display_name,
                        target_category="", # Empty string to export all categories from target
                        broad_category_swap_enabled=False, # Not relevant for target export
                        keywords="" # Not relevant for target export
                    )
                    
                    if not xedit_output_path_target_all:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export target mod data for 'Generate All'. Aborting.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Target Mod. Check xEdit logs for details.")
                        # Updated cleanup call with correct output path and script filename
                        clean_temp_script_and_ini(self.xedit_exe_path, output_folder_path / "SkyGen_xEdit_Export.json", xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
                        return

                    target_exported_json = load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=xedit_output_path_target_all, description="Target Mod xEdit Export", dialog_instance=self.dialog)
                    # Updated cleanup call with correct output path and script filename
                    clean_temp_script_and_ini(self.xedit_exe_path, xedit_output_path_target_all, xedit_script_filename, wrapped_organizer=self.wrapped_organizer)

                    if not target_exported_json or "baseObjects" not in target_exported_json:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting 'Generate All'.")
                        self.dialog.showError("JSON Parse Error", "Target mod xEdit export JSON is empty or malformed. Cannot proceed with 'Generate All'.")
                        return
                    
                    all_exported_target_bases = target_exported_json.get("baseObjects", [])
                    all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in all_exported_target_bases if "FormID" in obj}


                    # Iterate through each source mod and generate YAML
                    self.dialog.showInformation("Starting Batch Generation", f"Generating YAMLs for {len(source_mods_for_all)} source mods against target mod '{target_mod_display_name}' for category '{category}'. This may take some time...")

                    for current_source_mod_display_name in source_mods_for_all:
                        self.wrapped_organizer.log(1, f"SkyGen: Processing source mod: {current_source_mod_display_name}")
                        current_source_mod_internal_name = self.dialog._get_internal_mod_name_from_display_name(current_source_mod_display_name)
                        
                        source_mod_plugin_filename = self.dialog._get_plugin_name_from_mod_name(current_source_mod_display_name, current_source_mod_internal_name)
                        
                        if not source_mod_plugin_filename:
                            self.wrapped_organizer.log(2, f"SkyGen: WARNING: Skipping '{current_source_mod_display_name}' - no active plugin found.")
                            continue
                        
                        # Run xEdit export for the current source mod and specific category
                        xedit_output_path_source = run_xedit_export(
                            wrapped_organizer=self.wrapped_organizer,
                            dialog=self.dialog,
                            xedit_exe_path=self.xedit_exe_path,
                            xedit_mo2_name=self.xedit_mo2_name,
                            game_root_path=self.game_root_path,
                            xedit_script_filename=xedit_script_filename, # CHANGED
                            output_base_dir=output_folder_path,
                            target_plugin_filename=source_mod_plugin_filename, # This is the plugin we're extracting data FROM
                            game_version=self.dialog.selected_game_version,
                            target_mod_display_name=current_source_mod_display_name, # For logging context
                            target_category=category, # Pass the specific category for source export
                            broad_category_swap_enabled=broad_category_swap_enabled,
                            keywords=keywords
                        )
                        
                        if xedit_output_path_source:
                            source_exported_json = load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=xedit_output_path_source, description=f"xEdit Export for {current_source_mod_display_name}", dialog_instance=self.dialog)
                            # Updated cleanup call with correct output path and script filename
                            clean_temp_script_and_ini(self.xedit_exe_path, xedit_output_path_source, xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
                            
                            if source_exported_json and "baseObjects" in source_exported_json:
                                generated = generate_and_write_skypatcher_yaml(
                                    wrapped_organizer=self.wrapped_organizer,
                                    category=category,
                                    target_mod_plugin_name=target_plugin_filename, # Target is the single target mod
                                    source_mod_plugin_name=source_mod_plugin_filename,
                                    source_mod_display_name=current_source_mod_display_name,
                                    source_mod_base_objects=source_exported_json["baseObjects"],
                                    all_exported_target_bases_by_formid=all_exported_target_bases_by_formid,
                                    broad_category_swap_enabled=broad_category_swap_enabled,
                                    search_keywords=keywords,
                                    dialog_instance=self.dialog,
                                    output_folder_path=output_folder_path
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
                        self.wrapped_organizer.log(3, "SkyGen: Source mod not selected for single YAML generation.")
                        return

                    self.wrapped_organizer.log(1, f"SkyGen: Generating single YAML for '{source_mod_display_name}' targeting '{target_mod_display_name}' for category '{category}'...")

                    # Get plugin names from display names
                    target_plugin_filename = self.dialog._get_plugin_name_from_mod_name(target_mod_display_name, self.dialog._get_internal_mod_name_from_display_name(target_mod_display_name))
                    source_plugin_filename = self.dialog._get_plugin_name_from_mod_name(source_mod_display_name, self.dialog._get_internal_mod_name_from_display_name(source_mod_display_name))

                    if not target_plugin_filename or not source_plugin_filename:
                        self.dialog.showError("Plugin Resolution Error", "Could not determine plugin filenames for selected mods. Please ensure they are active and contain plugin files.")
                        self.wrapped_organizer.log(3, "SkyGen: Could not determine plugin filenames for selected mods.")
                        return

                    # 1. Export data from the Target Mod
                    self.wrapped_organizer.log(1, f"SkyGen: Exporting data from Target Mod: {target_mod_display_name}...")
                    xedit_output_path_target = run_xedit_export(
                        wrapped_organizer=self.wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=self.xedit_exe_path,
                        xedit_mo2_name=self.xedit_mo2_name,
                        game_root_path=self.game_root_path,
                        xedit_script_filename=xedit_script_filename, # CHANGED
                        output_base_dir=output_folder_path,
                        target_plugin_filename=target_plugin_filename,
                        game_version=self.dialog.selected_game_version,
                        target_mod_display_name=target_mod_display_name,
                        target_category="", # Export all from target to find replacements across categories if needed
                        broad_category_swap_enabled=False,
                        keywords=""
                    )

                    if not xedit_output_path_target:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export target mod data. Aborting YAML generation.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Target Mod. Check xEdit logs for details.")
                        # Updated cleanup call with correct output path and script filename
                        clean_temp_script_and_ini(self.xedit_exe_path, output_folder_path / "SkyGen_xEdit_Export.json", xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
                        return

                    target_exported_json = load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=xedit_output_path_target, description="Target Mod xEdit Export", dialog_instance=self.dialog)
                    # Updated cleanup call with correct output path and script filename
                    clean_temp_script_and_ini(self.xedit_exe_path, xedit_output_path_target, xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
 
                    if not target_exported_json or "baseObjects" not in target_exported_json:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                        self.dialog.showError("JSON Parse Error", "Target mod xedit export JSON is empty or malformed. Cannot generate YAML.")
                        return
                    
                    all_exported_target_bases = target_exported_json.get("baseObjects", [])
                    all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in all_exported_target_bases if "FormID" in obj}


                    # 2. Export data from the Source Mod for the specific category
                    self.wrapped_organizer.log(1, f"SkyGen: Exporting data from Source Mod: {source_mod_display_name} for category {category}...")
                    xedit_output_path_source = run_xedit_export(
                        wrapped_organizer=self.wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=self.xedit_exe_path,
                        xedit_mo2_name=self.xedit_mo2_name,
                        game_root_path=self.game_root_path,
                        xedit_script_filename=xedit_script_filename, # CHANGED
                        output_base_dir=output_folder_path,
                        target_plugin_filename=source_plugin_filename, # This is the plugin we're extracting data FROM
                        game_version=self.dialog.selected_game_version,
                        target_mod_display_name=source_mod_display_name, # For logging context
                        target_category=category, # Pass the specific category for source export
                        broad_category_swap_enabled=broad_category_swap_enabled,
                        keywords=keywords
                    )
                    
                    if not xedit_output_path_source:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export source mod data. Aborting YAML generation.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Source Mod. Check xEdit logs for details.")
                        # Updated cleanup call with correct output path and script filename
                        clean_temp_script_and_ini(self.xedit_exe_path, output_folder_path / "SkyGen_xedit_Export.json", xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
                        return

                    source_exported_json = load_json_data(wrapped_organizer=self.wrapped_organizer, file_path=xedit_output_path_source, description=f"xEdit Export for {source_mod_display_name}", dialog_instance=self.dialog)
                    # Updated cleanup call with correct output path and script filename
                    clean_temp_script_and_ini(self.xedit_exe_path, xedit_output_path_source, xedit_script_filename, wrapped_organizer=self.wrapped_organizer)
                    
                    if not source_exported_json or "baseObjects" not in source_exported_json:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Source mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                        self.dialog.showError("JSON Parse Error", "Source mod xedit export JSON is empty or malformed. Cannot generate YAML.")
                        return

                    # 3. Generate and write the YAML
                    generate_and_write_skypatcher_yaml(
                        wrapped_organizer=self.wrapped_organizer,
                        category=category,
                        target_mod_plugin_name=target_plugin_filename,
                        source_mod_plugin_name=source_plugin_filename,
                        source_mod_display_name=source_mod_display_name,
                        source_mod_base_objects=source_exported_json["baseObjects"],
                        all_exported_target_bases_by_formid=all_exported_target_bases_by_formid,
                        broad_category_swap_enabled=broad_category_swap_enabled,
                        search_keywords=keywords,
                        dialog_instance=self.dialog,
                        output_folder_path=output_folder_path
                    )

            elif selected_output_type == "BOS INI":
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

    def deinit(self):
        """
        Called by MO2 when the plugin is being unloaded.
        Ensures the custom debug log file is properly closed.
        """
        if self.wrapped_organizer:
            self.wrapped_organizer.log(1, "SkyGen: Plugin de-initializing. Closing debug log file.")
            self.wrapped_organizer.close_log_file()
        return True

    def __tr(self, str_):
        return self.mobase.qtTr(str_, self.name())

    def _open_log_file(self): # This method is unused and can be removed, or left with 'pass'
        if self._log_file_handle:
            pass
        if self._log_file_path:
            pass
        else:
            pass

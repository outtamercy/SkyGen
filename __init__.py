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
    safe_launch_xedit,  # New robust launch function for xEdit
    generate_and_write_skypatcher_yaml,
    generate_bos_ini_files,
    # clean_temp_files,  # Removed as it's handled internally by safe_launch_xedit
    # get_game_root_from_general_ini, # Not directly used by plugin, but by utilities
    # Removed write_pas_script_to_xedit import as it's now called internally by safe_launch_xedit
)

# Ensure necessary PyQt6 modules are imported for the main plugin if still used here,
# or for dummy QMessageBox if needed for initial checks.
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
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
    class QWidget: # Dummy QWidget for dialog parenting if needed
        def __init__(self, *args, **kwargs): pass
        def show(self): pass
        def close(self): pass
        def setWindowTitle(self, title): pass
        def setLayout(self, layout): pass
        def setFixedSize(self, width, height): pass
        def setSizePolicy(self, policy): pass
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
        return self.__tr("SkyGen")

    def author(self) -> str:
        """Returns the author of the tool."""
        return "ZanderLex"

    def description(self) -> str:
        """Returns a brief description of the tool."""
        return self.__tr("Automates generation of SkyPatcher YAML and BOS INI files using xEdit.")

    def version(self) -> mobase.VersionInfo:
        """Returns the version of the tool."""
        return mobase.VersionInfo(1, 1, 0, mobase.ReleaseType.BETA) # Current version

    def isActive(self) -> bool:
        """Determines if the plugin is active."""
        # The plugin should always be active for the tool to show up.
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


        if self.dialog.exec() == QMessageBox.StandardButton.Accepted:
            self.wrapped_organizer.log(1, "SkyGen: Dialog accepted. Starting generation process.")
            
            output_type = self.dialog.selected_output_type
            output_folder_path = Path(self.dialog.output_folder_path)
            
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

            # No longer need to get pascal_script_content here as safe_launch_xedit handles it internally
            
            if output_type == "SkyPatcher YAML":
                self.wrapped_organizer.log(1, "SkyGen: Generating SkyPatcher YAML...")
                
                target_mod_display_name = self.dialog.selected_target_mod_name
                source_mod_display_name = self.dialog.selected_source_mod_name
                category = self.dialog.selected_category
                keywords_str = self.dialog.keywords_lineEdit.text().strip()
                keywords = [k.strip() for k in keywords_str.split(',') if k.strip()] # Convert to list for Python usage
                broad_category_swap_enabled = self.dialog.broad_category_swap_checkbox.isChecked()

                if not target_mod_display_name:
                    self.dialog.showError("Input Error", "Please select a Target Mod.")
                    self.wrapped_organizer.log(3, "SkyGen: Target Mod not selected. Aborting.")
                    return
                if not category:
                    self.dialog.showError("Input Error", "Please select or enter a Category (Record Type).")
                    self.wrapped_organizer.log(3, "SkyGen: Category not selected. Aborting.")
                    return
                
                # Determine game mode flag for xEdit (e.g., -SE, -VR)
                game_mode_flag = ""
                if self.dialog.selected_game_version == "SkyrimSE":
                    game_mode_flag = "SE"
                elif self.dialog.selected_game_version == "SkyrimVR":
                    game_mode_flag = "VR"
                else:
                    self.dialog.showError("Game Version Error", "Could not determine game version. Please select SkyrimSE/AE or SkyrimVR.")
                    self.wrapped_organizer.log(4, "SkyGen: ERROR: Invalid or unselected game version.")
                    return

                # If "Generate All" is checked, iterate through all compatible source mods
                if self.dialog.generate_all:
                    self.wrapped_organizer.log(1, "SkyGen: 'Generate All' selected. Processing all compatible source mods.")
                    all_mods = self.organizer.modList().allMods()
                    generated_any_yaml = False
                    
                    # Ensure target mod has a plugin
                    target_plugin_filename = self.dialog._get_plugin_name_from_mod_name(target_mod_display_name, self.dialog._get_internal_mod_name_from_display_name(target_mod_display_name))
                    if not target_plugin_filename:
                        self.dialog.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_display_name}'. Please ensure it has a .esp/.esm/.esl file.")
                        self.wrapped_organizer.log(3, f"SkyGen: Target mod '{target_mod_display_name}' has no primary plugin. Aborting 'Generate All'.")
                        return

                    # 1. Export ALL data from the Target Mod first (only once)
                    self.wrapped_organizer.log(1, f"SkyGen: Exporting all data from Target Mod '{target_mod_display_name}' for 'Generate All' operation...")
                    
                    target_export_script_options = {
                        "TargetPlugin": target_plugin_filename,
                        "TargetCategory": "", # Empty string to export all categories
                        "Keywords": "",
                        "BroadCategorySwap": "false"
                    }

                    xedit_output_path_target_all = safe_launch_xedit(
                        self.organizer,
                        self.dialog,
                        self.xedit_exe_path,
                        self.xedit_mo2_name,
                        self.xedit_script_filename,
                        game_mode_flag,
                        target_export_script_options,
                        self.wrapped_organizer.log
                    )
                    
                    if not xedit_output_path_target_all:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export target mod data for 'Generate All'. Aborting.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Target Mod. Check xEdit logs for details.")
                        return

                    target_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_target_all, "Target Mod xEdit Export", self.dialog)
                    
                    # Clean up the output JSON from target export after loading
                    try:
                        xedit_output_path_target_all.unlink()
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up target export JSON: {xedit_output_path_target_all}")
                    except Exception as e:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete target export JSON '{xedit_output_path_target_all}': {e}")


                    if not target_exported_json or "baseObjects" not in target_exported_json:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting 'Generate All'.")
                        self.dialog.showError("JSON Parse Error", "Target mod xEdit export JSON is empty or malformed. Cannot proceed with 'Generate All'.")
                        return
                    
                    all_exported_target_bases = target_exported_json.get("baseObjects", [])
                    all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in all_exported_target_bases if "FormID" in obj}


                    # Iterate through each source mod and generate YAML
                    self.dialog.showInformation("Starting Batch Generation", f"Generating YAMLs for compatible source mods against target mod '{target_mod_display_name}' for category '{category}'. This may take some time...")

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
                                self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping mod '{mod_display_name}' (internal: {mod_name_internal}) as it's a master file or has no main plugin.")

                    if not source_mods_to_process:
                        self.dialog.showWarning("No Source Mods", "No suitable source mods found for 'Generate All'. Skipping.")
                        self.wrapped_organizer.log(2, "SkyGen: No suitable source mods found for 'Generate All'.")
                        return

                    successful_generations = 0
                    for current_source_mod_display_name, current_source_mod_internal_name, source_mod_plugin_filename in source_mods_to_process:
                        self.wrapped_organizer.log(1, f"SkyGen: Processing source mod: '{current_source_mod_display_name}' ({source_mod_plugin_filename})...")
                        
                        source_export_script_options = {
                            "TargetPlugin": source_mod_plugin_filename, # This is the plugin we're extracting data FROM
                            "TargetCategory": category,
                            "Keywords": ','.join(keywords),
                            "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                        }
                        
                        # Run xEdit export for the current source mod and specific category
                        xedit_output_path_source = safe_launch_xedit(
                            self.organizer,
                            self.dialog,
                            self.xedit_exe_path,
                            self.xedit_mo2_name,
                            self.xedit_script_filename,
                            game_mode_flag,
                            source_export_script_options,
                            self.wrapped_organizer.log
                        )
                        
                        if xedit_output_path_source:
                            source_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {current_source_mod_display_name}", dialog_instance=self.dialog)
                            
                            # Clean up the output JSON from source export after loading
                            try:
                                xedit_output_path_source.unlink()
                                self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                            except Exception as e:
                                self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
                            
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
                                    search_keywords=keywords_str, # Pass as string
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
                        self.wrapped_organizer.log(3, "SkyGen: Source Mod not selected for single YAML generation.")
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
                    
                    target_export_script_options = {
                        "TargetPlugin": target_plugin_filename,
                        "TargetCategory": "", # Export all from target to find replacements across categories if needed
                        "Keywords": "",
                        "BroadCategorySwap": "false"
                    }
                    
                    xedit_output_path_target = safe_launch_xedit(
                        self.organizer,
                        self.dialog,
                        self.xedit_exe_path,
                        self.xedit_mo2_name,
                        self.xedit_script_filename,
                        game_mode_flag,
                        target_export_script_options,
                        self.wrapped_organizer.log
                    )
                    
                    if not xedit_output_path_target:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export target mod data. Aborting YAML generation.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Target Mod. Check xEdit logs for details.")
                        return

                    target_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_target, "Target Mod xEdit Export", self.dialog)
                    
                    # Clean up the output JSON from target export after loading
                    try:
                        xedit_output_path_target.unlink()
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up target export JSON: {xedit_output_path_target}")
                    except Exception as e:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete target export JSON '{xedit_output_path_target}': {e}")
 
                    if not target_exported_json or "baseObjects" not in target_exported_json:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Target mod xEdit export JSON is empty or malformed. Aborting YAML generation.")
                        self.dialog.showError("JSON Parse Error", "Target mod xedit export JSON is empty or malformed. Cannot generate YAML.")
                        return
                    
                    all_exported_target_bases = target_exported_json.get("baseObjects", [])
                    all_exported_target_bases_by_formid = {obj["FormID"]: obj for obj in all_exported_target_bases if "FormID" in obj}


                    # 2. Export data from the Source Mod for the specific category
                    self.wrapped_organizer.log(1, f"SkyGen: Exporting data from Source Mod: {source_mod_display_name} for category {category}...")
                    
                    source_export_script_options = {
                        "TargetPlugin": source_plugin_filename, # This is the plugin we're extracting data FROM
                        "TargetCategory": category,
                        "Keywords": ','.join(keywords),
                        "BroadCategorySwap": str(broad_category_swap_enabled).lower()
                    }

                    xedit_output_path_source = safe_launch_xedit(
                        self.organizer,
                        self.dialog,
                        self.xedit_exe_path,
                        self.xedit_mo2_name,
                        self.xedit_script_filename,
                        game_mode_flag,
                        source_export_script_options,
                        self.wrapped_organizer.log
                    )
                    
                    if not xedit_output_path_source:
                        self.wrapped_organizer.log(3, "SkyGen: ERROR: Failed to export source mod data. Aborting YAML generation.")
                        self.dialog.showError("xEdit Export Failed", "Failed to export data from the Source Mod. Check xEdit logs for details.")
                        return

                    source_exported_json = load_json_data(self.wrapped_organizer, xedit_output_path_source, description=f"xEdit Export for {source_mod_display_name}", dialog_instance=self.dialog)
                    
                    # Clean up the output JSON from source export after loading
                    try:
                        xedit_output_path_source.unlink()
                        self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up source export JSON: {xedit_output_path_source}")
                    except Exception as e:
                        self.wrapped_organizer.log(2, f"SkyGen: WARNING: Failed to delete source export JSON '{xedit_output_path_source}': {e}")
                    
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
                        search_keywords=keywords_str, # Pass as string
                        dialog_instance=self.dialog,
                        output_folder_path=output_folder_path
                    )

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


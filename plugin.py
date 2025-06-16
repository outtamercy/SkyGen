import mobase
import os
import json
import yaml
import subprocess
import traceback
from pathlib import Path
from collections import defaultdict
import time # Added for time.sleep
from typing import Optional, Any

# Import functions from the utility file
from .skygen_file_utilities import (
        load_json_data,
        run_xedit_export,
        generate_and_write_skypatcher_yaml,
        generate_bos_ini_files,
        get_xedit_path_from_ini,
        get_xedit_exe_path,
        write_pas_script_to_xedit,
        clean_temp_script_and_ini,
        get_game_root_from_general_ini
    )

# Import UI classes from the new skygen_ui.py file
from .skygen_ui import SkyGenToolDialog, OrganizerWrapper # OrganizerWrapper is also needed here

# Ensure necessary PyQt6 modules are imported for the main plugin if still used here,
# or for dummy QMessageBox if needed for initial checks.
# Only import what's strictly necessary for *this* file's display method or plugin tool.
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtGui import QIcon # QIcon is used by the plugin tool directly
except ImportError:
    print("One or more required PyQt modules are not installed. Please ensure PyQt6 is installed.")
    class QApplication:
        def __init__(self, *args, **kwargs): pass
        def instance(self): return None
        def exec(self): return 0
    class QMessageBox:
        @staticmethod
        def critical(*args, **kwargs): print(f"CRITICAL: {args[2] if len(args) > 2 else 'No message'}")
    class QIcon:
        def __init__(self, *args, **kwargs): pass


class SkyGenPlugin(mobase.IPluginTool):
    # Plugin metadata defined as class attributes
    _name = "SkyGen"
    _description = "A tool for generating SkyPatcher YAMLs and BOS INIs."
    _author = "Ms. Mayhem & BoltBot"
    _version = mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)
    _tooltip = "Generate SkyPatcher YAMLs or BOS INIs"

    def init(self, organizer: mobase.IOrganizer): # Corrected signature
        # super().init(organizer) # <--- DELETED THIS LINE as per instruction
        self.organizer = organizer # Store the organizer instance
        self.wrapped_organizer = OrganizerWrapper(organizer) # Initialize the wrapper here
        
        # Ensure the plugin's data directory exists for logs/config
        self.plugin_data_path = Path(self.organizer.pluginDataPath()) / self.name() # Use self.name() for consistency
        self.plugin_data_path.mkdir(parents=True, exist_ok=True)
        
        # Pass the log file path to the wrapped organizer
        self.wrapped_organizer.set_log_file_path(self.plugin_data_path / "SkyGen_Debug.log")
        
        self.wrapped_organizer.log(1, f"SkyGen: Plugin '{self.name()}' initialized.")

        # Initialize other instance variables to None or default values
        # These will be populated more fully in the display method
        self.dialog: Optional[SkyGenToolDialog] = None
        self.xedit_exe_path: Optional[Path] = None
        self.xedit_mo2_name: Optional[str] = None
        self.game_root_path: Optional[Path] = None
        self.output_folder_path: Optional[Path] = None
        self.full_export_script_path: Optional[Path] = None
        self.selected_game_version: str = "SkyrimSE"
        self.selected_output_type: str = "SkyPatcher YAML"
        self.plugin_disambiguation_map: dict = {}

        return True

    def _validate_path(self, raw_path: Optional[str], label: str) -> Path:
        """
        Validates a given path, expands user directory, resolves it, and checks for a drive letter.
        Uses self.dialog for showing UI errors and self.wrapped_organizer for logging.
        """
        if not self.dialog or not self.wrapped_organizer:
            # This case should ideally not happen if called after display() sets them up
            raise RuntimeError("Dialog or wrapped organizer not initialized for path validation.")

        if not raw_path:
            self.dialog.showError("Config Error", f"Missing {label} in config.json.")
            raise ValueError(f"Missing {label}")
        try:
            path = Path(raw_path).expanduser()
            resolved = path.resolve(strict=False)
            if os.name == 'nt' and not resolved.drive: # Specific check for Windows
                raise ValueError("Path does not contain a drive letter (e.g., C:/).")
            
            # Log successful validation
            self.wrapped_organizer.log(0, f"SkyGen: DEBUG: Validated {label} path: {resolved}")
            return resolved
        except Exception as e:
            self.dialog.showError("Path Error", f"Invalid {label}: {raw_path}\nError: {e}")
            self.wrapped_organizer.log(3, f"SkyGen: ERROR: Invalid {label} '{raw_path}': {e}\n{traceback.format_exc()}")
            raise


    def run_export(self, target_plugin_name: str):
        """
        Executes the xEdit export process, handles temporary file cleanup,
        and provides UI feedback.
        Requires self.xedit_exe_path, self.xedit_mo2_name, self.game_root_path,
        self.full_export_script_path, self.output_folder_path,
        self.selected_game_version, and self.dialog to be set on the instance.
        """
        if not all([self.xedit_exe_path, self.xedit_mo2_name, self.game_root_path,
                    self.full_export_script_path, self.output_folder_path,
                    self.selected_game_version, self.dialog, self.wrapped_organizer]):
            self.wrapped_organizer.log(3, "SkyGen: ERROR: Missing one or more required attributes for run_export.")
            if self.dialog:
                self.dialog.showError("Internal Error", "Missing critical setup data for xEdit export. Please restart the tool.")
            return False

        try:
            # Determine if YAML mode is selected
            is_yaml = self.selected_output_type == "SkyPatcher YAML"
            if is_yaml:
                # This check remains for safety, assuming files are written by _on_output_type_toggled
                if not self.full_export_script_path.is_file():
                    self.dialog.showError("Script Not Found", "The xEdit Pascal script was not found. Please re-select 'SkyPatcher YAML' output type.")
                    self.wrapped_organizer.log(3, "SkyGen: ABORTING: Pascal script missing for xEdit launch.")
                    return False
            
            success = run_xedit_export(
                wrapped_organizer=self.wrapped_organizer,
                dialog=self.dialog,
                xedit_exe_path=self.xedit_exe_path,
                xedit_mo2_name=self.xedit_mo2_name,
                game_root_path=self.game_root_path,
                xedit_script_path=self.full_export_script_path,
                output_base_dir=self.output_folder_path,
                target_plugin_filename=target_plugin_name,
                game_version=self.selected_game_version,
                target_mod_display_name=target_plugin_name,
                target_category=getattr(self.dialog, "selected_category", None)
            )
            
            # Clean up temporary files if YAML export mode
            if is_yaml:
                clean_temp_script_and_ini(
                    xedit_exe_path=self.xedit_exe_path,
                    script_path=self.full_export_script_path,
                    wrapped_organizer=self.wrapped_organizer
                )
            
            if not success:
                self.dialog.showError("Export Failed", "The xEdit export did not succeed.")
            return success

        except Exception as e:
            self.dialog.showError("Runtime Error", f"An unexpected error occurred during export:\n{str(e)}")
            self.wrapped_organizer.log(3, f"Exception during run_export: {e}\n{traceback.format_exc()}")
            return False


    def name(self):
        return self._name

    def author(self):
        return self._author

    def description(self):
        return self._description

    def version(self):
        return self._version

    def displayName(self):
        return self.name()

    def tooltip(self):
        return self._tooltip

    def icon(self):
        return QIcon()

    def flags(self):
        return mobase.PluginFeature.Tool | mobase.PluginFeature.Python

    def isActive(self):
        return True

    def settings(self):
        return []

    def display(self):
        if QApplication.instance() is None:
            _ = QApplication([])

        # Use OrganizerWrapper from skygen_ui as it handles logging and MO2 interactions for the dialog
        # self.wrapped_organizer is already initialized in init()

        # 1. Load initial config data to pass to get_xedit_exe_path
        config_file_path = Path(__file__).parent / "config.json"
        config_data_for_path_lookup = {}
        if config_file_path.is_file():
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data_for_path_lookup = json.load(f)
            except Exception as e:
                self.wrapped_organizer.log(3, f"SkyGen: ERROR: Could not load config.json for initial path lookup: {e}")

        # 2. Determine xEdit path and MO2 name using the centralized logic
        # Pass a temporary QMessageBox instance for initial critical error messages
        temp_msg_box = QMessageBox()
        self.xedit_exe_path, self.xedit_mo2_name = get_xedit_exe_path( # Assigned to self.
            config_data_for_path_lookup, 
            self.wrapped_organizer, # Use self.wrapped_organizer here
            temp_msg_box # Pass a temporary dialog_instance for critical errors
        )

        # 3. If xEdit path could not be found, show a critical error and exit.
        if not self.xedit_exe_path or not self.xedit_exe_path.is_file() or not self.xedit_mo2_name:
            QMessageBox.critical(None, "xEdit Not Found", 
                                 "The xEdit executable could not be located or its MO2 name determined. "
                                 "Please ensure it's correctly configured as an executable in Mod Organizer 2, "
                                 "or manually set 'xedit_exe_path' and 'xedit_mo2_name' in the config.json file in the plugin directory.")
            self.wrapped_organizer.log(3, "SkyGen: xEdit executable or MO2 name not found during initial plugin display. Aborting.")
            self.wrapped_organizer.close_log_file()
            return

        # 4. Get the game root path for xEdit's CWD
        self.game_root_path = get_game_root_from_general_ini(self.wrapped_organizer, temp_msg_box) # Assigned to self., use self.wrapped_organizer
        if not self.game_root_path:
            QMessageBox.critical(None, "Game Root Not Found", 
                                 "Could not determine game root path from ModOrganizer.ini. "
                                 "Please ensure 'gamePath' is correctly configured in your MO2 settings.")
            self.wrapped_organizer.log(3, "SkyGen: Game root path not found during plugin display. Aborting.")
            self.wrapped_organizer.close_log_file()
            return

        # --- Begin initialization logic for other core properties ---
        # These properties are now set from config_data_for_path_lookup after xEdit and game paths are validated
        try:
            # IMPORTANT: _validate_path is currently NOT in this class. It needs to be re-added.
            # For now, we will assign directly and add a log warning if validation logic is desired here before re-adding the method.
            # self.output_folder_path = self._validate_path(
            #     config_data_for_path_lookup.get("output_folder_path"), 
            #     "Output Folder Path"
            # )
            self.output_folder_path = Path(config_data_for_path_lookup.get("output_folder_path", ""))
            if not self.output_folder_path.is_dir():
                 self.wrapped_organizer.log(2, f"SkyGen: WARNING: Output folder path from config.json is invalid or not a directory: {self.output_folder_path}. Proceeding, but may cause issues.")

            # self.full_export_script_path = self._validate_path(
            #     config_data_for_path_lookup.get("full_export_script_path"), 
            #     "Export Script Path"
            # )
            self.full_export_script_path = Path(config_data_for_path_lookup.get("full_export_script_path", ""))
            if not self.full_export_script_path.is_file():
                self.wrapped_organizer.log(2, f"SkyGen: WARNING: Full export script path from config.json is invalid or not a file: {self.full_export_script_path}. Proceeding, but may cause issues.")


        except ValueError: # _validate_path raises ValueError if path is invalid
            self.wrapped_organizer.log(3, "SkyGen: ABORTING: Invalid path from config.json. Error already shown to user.")
            self.wrapped_organizer.close_log_file()
            return

        self.selected_game_version = config_data_for_path_lookup.get("selected_game_version", "SkyrimSE")
        self.selected_output_type = config_data_for_path_lookup.get("selected_output_type", "SkyPatcher YAML")
        self.plugin_disambiguation_map = config_data_for_path_lookup.get("plugin_disambiguation_map", {})

        # --- End initialization logic for other core properties ---


        self.dialog = SkyGenToolDialog(self.wrapped_organizer) # Initialize dialog with wrapped_organizer
        self.dialog.determined_xedit_executable_name = self.xedit_mo2_name
        self.dialog.determined_xedit_exe_path = self.xedit_exe_path
        self.dialog.game_root_path = self.game_root_path # Set game_root_path on dialog

        result = self.dialog.exec()

        if result == 1:
            igpc_json_path = self.dialog.igpc_json_path
            pre_exported_xedit_json_path = self.dialog.xedit_json_lineEdit.text().strip()
            selected_game_version = self.dialog.selected_game_version
            selected_category = self.dialog.selected_category
            selected_target_mod_name = self.dialog.selected_target_mod_name
            selected_source_mod_name = self.dialog.selected_source_mod_name
            generate_all = self.dialog.generate_all
            search_keywords = self.dialog.keywords_lineEdit.text().strip()
            broad_category_swap_enabled = self.dialog.broad_category_swap_checkbox.isChecked() # Corrected retrieval

            # Retrieve the output folder path as a string from the dialog
            output_folder_path_str = self.dialog.output_folder_path

            selected_output_type = self.dialog.selected_output_type
            full_export_script_path = self.dialog.full_export_script_path


            self.wrapped_organizer.log(1, f"SkyGen: Dialog accepted. Output Type: {selected_output_type}")
            self.wrapped_organizer.log(1, f"SkyGen: IGPC Path: {igpc_json_path}")
            self.wrapped_organizer.log(1, f"SkyGen: Output Folder: {output_folder_path_str}")

            igpc_data = None
            if selected_output_type == "BOS INI":
                igpc_data = load_json_data(self.wrapped_organizer, Path(igpc_json_path), "IGPC JSON", self.dialog)
                if not igpc_data:
                    return

            if selected_output_type == "SkyPatcher YAML":
                self.wrapped_organizer.log(1, f"SkyGen: Preparing for SkyPatcher YAML generation.")

                self.wrapped_organizer.log(1, f"SkyGen: Determined xEdit Executable (MO2 Name): {self.xedit_mo2_name}") # Use self.
                self.wrapped_organizer.log(1, f"SkyGen: Actual xEdit Executable Path: {self.xedit_exe_path}") # Use self.
                self.wrapped_organizer.log(1, f"SkyGen: Full Export Script Path (from config): {full_export_script_path}")
                self.wrapped_organizer.log(1, f"SkyGen: Game Version: {selected_game_version}")
                self.wrapped_organizer.log(1, f"SkyGen: Category: {selected_category}")
                self.wrapped_organizer.log(1, f"SkyGen: Target Mod: {selected_target_mod_name}")
                self.wrapped_organizer.log(1, f"SkyGen: Source Mod (Single): {selected_source_mod_name}")
                self.wrapped_organizer.log(1, f"SkyGen: Search Keywords: {search_keywords}")
                self.wrapped_organizer.log(1, f"SkyGen: Broad Category Swap Enabled: {broad_category_swap_enabled}")


                target_mod_plugin_name = None
                target_mod_internal_name = None

                for mod_internal_name_candidate in self.wrapped_organizer.modList().allMods():
                    if self.wrapped_organizer.modList().displayName(mod_internal_name_candidate) == selected_target_mod_name:
                        target_mod_internal_name = mod_internal_name_candidate
                        self.wrapped_organizer.log(0, f"SkyGen: Found internal mod name for target mod '{selected_target_mod_name}': {target_mod_internal_name}")
                        break
                if not target_mod_internal_name and selected_target_mod_name.lower().endswith(".esm"):
                    if selected_target_mod_name in self.wrapped_organizer.pluginList().pluginNames():
                        if self.wrapped_organizer.pluginList().state(selected_target_mod_name) & mobase.PluginState.ACTIVE:
                            target_mod_internal_name = selected_target_mod_name
                            self.wrapped_organizer.log(0, f"SkyGen: Target mod is active base game ESM: {target_mod_internal_name}")

                if not target_mod_internal_name:
                    self.dialog.showError("Mod Error", f"Could not find internal mod name for target mod '{selected_target_mod_name}'.")
                    return

                target_mod_plugin_name = self.dialog._get_plugin_name_from_mod_name(selected_target_mod_name, target_mod_internal_name)
                if not target_mod_plugin_name:
                    self.dialog.showError("Plugin Selection Cancelled", f"Target mod plugin selection cancelled or failed for '{selected_target_mod_name}'.")
                    return

                all_exported_target_bases_by_formid = {}
                if pre_exported_xedit_json_path:
                    xedit_exported_data = load_json_data(self.wrapped_organizer, Path(pre_exported_xedit_json_path), "Pre-exported xEdit JSON", self.dialog)
                    if xedit_exported_data and isinstance(xedit_exported_data, dict):
                        for item in xedit_exported_data.get("sourceModBaseObjects", []):
                            if item.get("FormID"):
                                all_exported_target_bases_by_formid[item["FormID"]] = item
                    else:
                        self.dialog.showError("xEdit Data Error", "Pre-exported xedit JSON is not in the expected dictionary format or is empty.")
                        return
                else: # This block handles the case where pre_exported_xedit_json_path is NOT used
                    self.wrapped_organizer.log(1, f"SkyGen: Determined MO2 executable name for xEdit: '{self.xedit_mo2_name}' from path stem.")
                    self.wrapped_organizer.log(1, f"SkyGen: Using full export script path: {full_export_script_path}")

                    # This is the *only* call to run_xedit_export in this block now.
                    xedit_exported_json_path_from_run = run_xedit_export(
                        wrapped_organizer=self.wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=self.xedit_exe_path, # Use self.
                        xedit_mo2_name=self.xedit_mo2_name, # Use self.
                        game_root_path=self.game_root_path, # Pass game_root_path here
                        xedit_script_path=full_export_script_path,
                        output_base_dir=Path(output_folder_path_str),
                        target_plugin_filename=target_mod_plugin_name,
                        game_version=selected_game_version,
                        target_mod_display_name=target_mod_plugin_name,
                        target_category=selected_category,
                        broad_category_swap_enabled=broad_category_swap_enabled, # Pass broad category swap
                        keywords=search_keywords # Pass keywords
                    )

                    if not xedit_exported_json_path_from_run:
                        self.dialog.showError("xEdit Export Failed", "xEdit data export failed. Check MO2 logs for details.")
                        return
                    
                    xedit_exported_data = load_json_data(self.wrapped_organizer, xedit_exported_json_path_from_run, "xEdit Exported Data", self.dialog)
                    if xedit_exported_data and isinstance(xedit_exported_data, dict):
                        for item in xedit_exported_data.get("sourceModBaseObjects", []):
                            if item.get("FormID"):
                                all_exported_target_bases_by_formid[item["FormID"]] = item
                    else:
                        self.dialog.showError("xEdit Data Error", "xEdit exported JSON is not in the expected dictionary format or is empty.")
                        return
                    
                    try:
                        # Clean up the dynamically named export file here in plugin.py
                        if xedit_exported_json_path_from_run.is_file():
                            xedit_exported_json_path_from_run.unlink()
                            self.wrapped_organizer.log(1, f"SkyGen: Cleaned up temporary xEdit export file: {xedit_exported_json_path_from_run}")
                    except Exception as e:
                        self.wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit export file {xedit_exported_json_path_from_run}: {e}")

                if generate_all:
                    self.wrapped_organizer.log(1, "SkyGen: Generating YAMLs for all applicable source mods.")
                    generated_count = 0
                    for mod_internal_name in self.wrapped_organizer.modList().allMods():
                        if self.wrapped_organizer.modList().state(mod_internal_name) & mobase.ModState.ACTIVE:
                            current_source_mo2_name = self.wrapped_organizer.modList().displayName(mod_internal_name)
                            current_source_plugin_name = None
                            
                            if current_source_mo2_name.lower().endswith(".esm"):
                                if current_source_mo2_name in self.wrapped_organizer.pluginList().pluginNames():
                                    if self.wrapped_organizer.pluginList().state(current_source_mo2_name) & mobase.PluginState.ACTIVE:
                                        current_source_plugin_name = current_source_mo2_name
                                        self.wrapped_organizer.log(0, f"SkyGen: Source mod is active base game ESM: {current_source_plugin_name}")
                            else:
                                current_source_plugin_name = self.dialog._get_plugin_name_from_mod_name(current_source_mo2_name, mod_internal_name)
                            
                            if not current_source_plugin_name:
                                self.wrapped_organizer.log(0, f"SkyGen: Skipping '{current_source_mo2_name}' as no plugin name could be determined.")
                                continue

                            # Re-run export for each source mod to get its specific data if not using pre-exported
                            current_mod_exported_data = {}
                            if not pre_exported_xedit_json_path: # Only re-run if not using pre-exported JSON
                                self.wrapped_organizer.log(1, f"SkyGen: Running xEdit export for source mod '{current_source_mo2_name}' ({current_source_plugin_name}) in 'Generate All' mode.")
                                current_mod_export_json_path = run_xedit_export(
                                    wrapped_organizer=self.wrapped_organizer,
                                    dialog=self.dialog,
                                    xedit_exe_path=self.xedit_exe_path, # Use self.
                                    xedit_mo2_name=self.xedit_mo2_name, # Use self.
                                    game_root_path=self.game_root_path, # Pass game_root_path here
                                    xedit_script_path=full_export_script_path,
                                    output_base_dir=Path(output_folder_path_str),
                                    target_plugin_filename=current_source_plugin_name, # Export this specific source mod
                                    game_version=selected_game_version,
                                    target_mod_display_name=current_source_mo2_name,
                                    target_category=selected_category,
                                    broad_category_swap_enabled=broad_category_swap_enabled, # Pass broad category swap
                                    keywords=search_keywords # Pass keywords
                                )

                                if not current_mod_export_json_path:
                                    self.wrapped_organizer.log(2, f"SkyGen: xEdit export failed for source mod '{current_source_mo2_name}'. Skipping.")
                                    continue
                                
                                temp_exported_data = load_json_data(self.wrapped_organizer, current_mod_export_json_path, f"xEdit Exported Data for {current_source_mo2_name}", self.dialog)
                                if temp_exported_data and isinstance(temp_exported_data, dict):
                                    current_mod_exported_data = {item["FormID"]: item for item in temp_exported_data.get("sourceModBaseObjects", []) if item.get("FormID")}
                                else:
                                    self.wrapped_organizer.log(2, f"SkyGen: xEdit exported JSON for '{current_source_mo2_name}' is not in expected format or empty. Skipping.")
                                    continue
                                
                                try:
                                    if current_mod_export_json_path.is_file():
                                        current_mod_export_json_path.unlink()
                                        self.wrapped_organizer.log(1, f"SkyGen: Cleaned up temporary xEdit export file: {current_mod_export_json_path}")
                                except Exception as e:
                                    self.wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit export file {current_mod_export_json_path}: {e}")
                            else: # If using pre-exported JSON, filter from all_exported_target_bases_by_formid
                                current_mod_exported_data = {
                                    form_id: item for form_id, item in all_exported_target_bases_by_formid.items()
                                    if item.get("originMod") == current_source_plugin_name and item.get("category") == selected_category
                                }

                            current_source_mod_base_objects_for_yaml = list(current_mod_exported_data.values())

                            if current_source_mod_base_objects_for_yaml:
                                self.wrapped_organizer.log(1, f"SkyGen: Attempting to generate YAML for '{current_source_mo2_name}'...")
                                if generate_and_write_skypatcher_yaml(
                                    self.wrapped_organizer,
                                    selected_category,
                                    target_mod_plugin_name,
                                    current_source_plugin_name,
                                    current_source_mo2_name,
                                    current_source_mod_base_objects_for_yaml,
                                    all_exported_target_bases_by_formid,
                                    broad_category_swap_enabled,
                                    search_keywords,
                                    self.dialog,
                                    Path(output_folder_path_str)
                                ):
                                    generated_count += 1
                            else:
                                self.wrapped_organizer.log(0, f"SkyGen: No relevant base objects found for '{current_source_mo2_name}' in category '{selected_category}'. Skipping.")
                    self.dialog.showInformation("Generation Complete", f"Generated {generated_count} YAML file(s). Check SkyPatcher/Configs.")

                else: # Single generation
                    self.wrapped_organizer.log(1, f"SkyGen: Generating single YAML for source mod: {selected_source_mod_name}")
                    
                    selected_source_mod_plugin_name = None
                    selected_source_mod_internal_name = None

                    for mod_internal_name_candidate in self.wrapped_organizer.modList().allMods():
                        if self.wrapped_organizer.modList().displayName(mod_internal_name_candidate) == selected_source_mod_name:
                            selected_source_mod_internal_name = mod_internal_name_candidate
                            self.wrapped_organizer.log(0, f"SkyGen: Found internal mod name for source mod '{selected_source_mod_name}': {selected_source_mod_internal_name}")
                            break
                    if not selected_source_mod_internal_name and selected_source_mod_name.lower().endswith(".esm"):
                        if selected_source_mod_name in self.wrapped_organizer.pluginList().pluginNames():
                            if self.wrapped_organizer.pluginList().state(selected_source_mod_name) & mobase.PluginState.ACTIVE:
                                selected_source_mod_internal_name = selected_source_mod_name
                                self.wrapped_organizer.log(0, f"SkyGen: Source mod is active base game ESM: {selected_source_mod_internal_name}")

                    if not selected_source_mod_internal_name:
                        self.dialog.showError("Mod Error", f"Could not find internal mod name for source mod '{selected_source_mod_name}'.")
                        return

                    selected_source_mod_plugin_name = self.dialog._get_plugin_name_from_mod_name(selected_source_mod_name, selected_source_mod_internal_name)
                    if not selected_source_mod_plugin_name:
                        self.dialog.showError("Plugin Selection Cancelled", f"Source mod plugin selection cancelled or failed for '{selected_source_mod_name}'.")
                        return

                    # Re-run export for the single source mod if not using pre-exported
                    single_source_mod_exported_data = {}
                    if not pre_exported_xedit_json_path:
                        self.wrapped_organizer.log(1, f"SkyGen: Running xEdit export for single source mod '{selected_source_mod_name}' ({selected_source_mod_plugin_name}).")
                        single_mod_export_json_path = run_xedit_export(
                            wrapped_organizer=self.wrapped_organizer,
                            dialog=self.dialog,
                            xedit_exe_path=self.xedit_exe_path, # Use self.
                            xedit_mo2_name=self.xedit_mo2_name, # Use self.
                            game_root_path=self.game_root_path, # Pass game_root_path here
                            xedit_script_path=full_export_script_path,
                            output_base_dir=Path(output_folder_path_str),
                            target_plugin_filename=selected_source_mod_plugin_name, # Export this specific source mod
                            game_version=selected_game_version,
                            target_mod_display_name=selected_source_mod_name,
                            target_category=selected_category,
                            broad_category_swap_enabled=broad_category_swap_enabled, # Pass broad category swap
                            keywords=search_keywords # Pass keywords
                        )

                        if not single_mod_export_json_path:
                            self.dialog.showError("xEdit Export Failed", f"xEdit data export failed for '{selected_source_mod_name}'. Check MO2 logs.")
                            return

                        temp_exported_data = load_json_data(self.wrapped_organizer, single_mod_export_json_path, f"xEdit Exported Data for {selected_source_mod_name}", self.dialog)
                        if temp_exported_data and isinstance(temp_exported_data, dict):
                            single_source_mod_exported_data = {item["FormID"]: item for item in temp_exported_data.get("sourceModBaseObjects", []) if item.get("FormID")}
                        else:
                            self.dialog.showError("xEdit Data Error", f"xEdit exported JSON for '{selected_source_mod_name}' is not in expected format or empty.")
                            return
                        
                        try:
                            if single_mod_export_json_path.is_file():
                                single_mod_export_json_path.unlink()
                                self.wrapped_organizer.log(1, f"SkyGen: Cleaned up temporary xEdit export file: {single_mod_export_json_path}")
                        except Exception as e:
                            self.wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit export file {single_mod_export_json_path}: {e}")
                    else: # If using pre-exported JSON, filter from all_exported_target_bases_by_formid
                        single_source_mod_exported_data = {
                            form_id: item for form_id, item in all_exported_target_bases_by_formid.items()
                            if item.get("originMod") == selected_source_mod_plugin_name and item.get("category") == selected_category
                        }


                    selected_source_mod_base_objects_from_xedit = list(single_source_mod_exported_data.values())

                    if selected_source_mod_base_objects_from_xedit:
                        if generate_and_write_skypatcher_yaml(
                            self.wrapped_organizer,
                            selected_category,
                            target_mod_plugin_name,
                            selected_source_mod_plugin_name,
                            selected_source_mod_name,
                            selected_source_mod_base_objects_from_xedit,
                            all_exported_target_bases_by_formid,
                            broad_category_swap_enabled,
                            search_keywords,
                            self.dialog,
                            Path(output_folder_path_str)
                        ):
                            self.dialog.showInformation("Generation Complete", f"Successfully generated YAML for '{selected_source_mod_name}'. Check SkyPatcher/Configs.")
                        else:
                            self.dialog.showWarning("Generation Skipped", f"No replacements generated for '{selected_source_mod_name}'. YAML not created.")
                    else:
                        self.dialog.showWarning("No Relevant Bases", f"No relevant base objects found for '{selected_source_mod_name}'. YAML not created for category '{selected_category}'.")
            
            elif selected_output_type == "BOS INI":
                self.wrapped_organizer.log(1, f"SkyGen: Generating BOS INI files.")
                if generate_bos_ini_files(
                    self.wrapped_organizer,
                    igpc_data,
                    Path(output_folder_path_str),
                    self.dialog
                ):
                    self.dialog.showInformation("Generation Complete", f"Successfully generated BOS INI files. Check output folder.")
                else:
                    self.dialog.showWarning("Generation Skipped", f"No BOS INI files generated.")

        else:
            self.wrapped_organizer.log(1, "SkyGen: Dialog cancelled.")

        self.wrapped_organizer.close_log_file()

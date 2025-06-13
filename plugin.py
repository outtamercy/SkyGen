import mobase
import os
import json
import yaml
import subprocess
import traceback
from pathlib import Path
from collections import defaultdict
import time # Added for time.sleep
from typing import Optional

# Import functions from the utility file
from .skygen_file_utilities import (
        load_json_data,
        run_xedit_export,
        generate_and_write_skypatcher_yaml,
        generate_bos_ini_files,
        get_xedit_path_from_ini,
        get_xedit_exe_path,
        write_xedit_ini_for_skygen,
        write_pas_script_to_xedit,
        clean_temp_script_and_ini
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


# ───────── Plugin Logic ─────────
class SkyGenPlugin:
    def __init__(self, config_data, dialog, wrapped_organizer):
        self.dialog = dialog
        self.wrapped_organizer = wrapped_organizer

        self.output_folder_path: Path = self._validate_path(config_data.get("output_folder_path"), "Output Folder Path")
        self.full_export_script_path: Path = self._validate_path(config_data.get("full_export_script_path"), "Export Script Path")
        
        # xEdit path and MO2 name are now passed in via config_data, already determined by display()
        self.xedit_exe_path = Path(config_data.get("xedit_exe_path")) if config_data.get("xedit_exe_path") else None
        self.xedit_mo2_name = config_data.get("xedit_mo2_name")

        # Final check: if xEdit path is still not valid, raise an error.
        # The main display() method should have already shown a QMessageBox.
        if not self.xedit_exe_path or not self.xedit_exe_path.is_file() or not self.xedit_mo2_name:
            self.wrapped_organizer.log(3, "SkyGen: ERROR: SkyGenPlugin initialized with invalid xEdit path/name. This should have been caught earlier.")
            raise FileNotFoundError("SkyGenPlugin: xEdit executable or MO2 name is missing/invalid during initialization.")

        self.selected_game_version: str = config_data.get("selected_game_version", "SkyrimSE")
        self.selected_output_type: str = config_data.get("selected_output_type", "SkyPatcher YAML")
        self.plugin_disambiguation_map: dict = config_data.get("plugin_disambiguation_map", {})

    def _validate_path(self, raw_path: Optional[str], label: str) -> Path:
        if not raw_path:
            self.dialog.showError("Config Error", f"Missing {label} in config.json.")
            raise ValueError(f"Missing {label}")
        try:
            path = Path(raw_path).expanduser()
            resolved = path.resolve(strict=False)
            if not resolved.drive:
                raise ValueError("Path does not contain a drive letter.")
            return resolved
        except Exception as e:
            self.dialog.showError("Path Error", f"Invalid {label}: {raw_path}\nError: {e}")
            raise


    def run_export(self, target_plugin_name: str):
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


class SkyGenGeneratorTool(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self.organizer = None
        self.dialog = None

    def init(self, organizer: mobase.IOrganizer):
        self.organizer = organizer
        return True

    def name(self):
        return "SkyGen"

    def author(self):
        return "Ms. Mayhem & BoltBot"

    def description(self):
        return "SkyPatcher and BOS Gen Tool"

    def version(self):
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.ALPHA)

    def displayName(self):
        return self.name()

    def tooltip(self):
        return "Generate SkyPatcher YAMLs and BOS INIs (Requires SkyPatcher & BOS)"

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
        wrapped_organizer = OrganizerWrapper(self.organizer) 

        # 1. Load initial config data to pass to get_xedit_exe_path
        config_file_path = Path(__file__).parent / "config.json"
        config_data_for_path_lookup = {}
        if config_file_path.is_file():
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    config_data_for_path_lookup = json.load(f)
            except Exception as e:
                wrapped_organizer.log(3, f"SkyGen: ERROR: Could not load config.json for initial path lookup: {e}")

        # 2. Determine xEdit path and MO2 name using the centralized logic
        # Pass a temporary QMessageBox instance for initial critical error messages
        temp_msg_box = QMessageBox()
        initial_xedit_exe_path, initial_xedit_mo2_name = get_xedit_exe_path(
            config_data_for_path_lookup, 
            wrapped_organizer, 
            temp_msg_box # Pass a temporary dialog_instance for critical errors
        )

        # 3. If xEdit path could not be found, show a critical error and exit.
        if not initial_xedit_exe_path or not initial_xedit_exe_path.is_file() or not initial_xedit_mo2_name:
            QMessageBox.critical(None, "xEdit Not Found", 
                                 "The xEdit executable could not be located or its MO2 name determined. "
                                 "Please ensure it's correctly configured as an executable in Mod Organizer 2, "
                                 "or manually set 'xedit_exe_path' and 'xedit_mo2_name' in the config.json file in the plugin directory.")
            wrapped_organizer.log(3, "SkyGen: xEdit executable or MO2 name not found during initial plugin display. Aborting.")
            wrapped_organizer.close_log_file()
            return

        self.dialog = SkyGenToolDialog(wrapped_organizer) # Initialize dialog with wrapped_organizer
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
            broad_category_swap_enabled = self.dialog.broad_category_swap_enabled
            
            # Retrieve the determined paths from the dialog's state, as they were set during init
            mo2_exec_name_to_use = self.dialog.determined_xedit_executable_name
            xedit_actual_file_path = self.dialog.determined_xedit_exe_path

            # Retrieve the output folder path as a string from the dialog
            output_folder_path_str = self.dialog.output_folder_path

            selected_output_type = self.dialog.selected_output_type
            full_export_script_path = self.dialog.full_export_script_path


            wrapped_organizer.log(1, f"SkyGen: Dialog accepted. Output Type: {selected_output_type}")
            wrapped_organizer.log(1, f"SkyGen: IGPC Path: {igpc_json_path}")
            wrapped_organizer.log(1, f"SkyGen: Output Folder: {output_folder_path_str}")

            igpc_data = None
            if selected_output_type == "BOS INI":
                igpc_data = load_json_data(wrapped_organizer, Path(igpc_json_path), "IGPC JSON", self.dialog)
                if not igpc_data:
                    return

            if selected_output_type == "SkyPatcher YAML":
                wrapped_organizer.log(1, f"SkyGen: Preparing for SkyPatcher YAML generation.")

                wrapped_organizer.log(1, f"SkyGen: Determined xEdit Executable (MO2 Name): {mo2_exec_name_to_use}")
                wrapped_organizer.log(1, f"SkyGen: Actual xEdit Executable Path: {xedit_actual_file_path}")
                wrapped_organizer.log(1, f"SkyGen: Full Export Script Path (from config): {full_export_script_path}")
                wrapped_organizer.log(1, f"SkyGen: Game Version: {selected_game_version}")
                wrapped_organizer.log(1, f"SkyGen: Category: {selected_category}")
                wrapped_organizer.log(1, f"SkyGen: Target Mod: {selected_target_mod_name}")
                wrapped_organizer.log(1, f"SkyGen: Source Mod (Single): {selected_source_mod_name}")
                wrapped_organizer.log(1, f"SkyGen: Search Keywords: {search_keywords}")
                wrapped_organizer.log(1, f"SkyGen: Broad Category Swap Enabled: {broad_category_swap_enabled}")


                target_mod_plugin_name = None
                target_mod_internal_name = None

                for mod_internal_name_candidate in wrapped_organizer.modList().allMods():
                    if wrapped_organizer.modList().displayName(mod_internal_name_candidate) == selected_target_mod_name:
                        target_mod_internal_name = mod_internal_name_candidate
                        wrapped_organizer.log(0, f"SkyGen: Found internal mod name for target mod '{selected_target_mod_name}': {target_mod_internal_name}")
                        break
                if not target_mod_internal_name and selected_target_mod_name.lower().endswith(".esm"):
                    if selected_target_mod_name in wrapped_organizer.pluginList().pluginNames():
                        if wrapped_organizer.pluginList().state(selected_target_mod_name) & mobase.PluginState.ACTIVE:
                            target_mod_internal_name = selected_target_mod_name
                            wrapped_organizer.log(0, f"SkyGen: Target mod is active base game ESM: {target_mod_internal_name}")

                if not target_mod_internal_name:
                    self.dialog.showError("Mod Error", f"Could not find internal mod name for target mod '{selected_target_mod_name}'.")
                    return

                target_mod_plugin_name = self.dialog._get_plugin_name_from_mod_name(selected_target_mod_name, target_mod_internal_name)
                if not target_mod_plugin_name:
                    self.dialog.showError("Plugin Selection Cancelled", f"Target mod plugin selection cancelled or failed for '{selected_target_mod_name}'.")
                    return

                all_exported_target_bases_by_formid = {}
                if pre_exported_xedit_json_path:
                    xedit_exported_data = load_json_data(wrapped_organizer, Path(pre_exported_xedit_json_path), "Pre-exported xEdit JSON", self.dialog)
                    if xedit_exported_data and isinstance(xedit_exported_data, dict):
                        for item in xedit_exported_data.get("sourceModBaseObjects", []):
                            if item.get("FormID"):
                                all_exported_target_bases_by_formid[item["FormID"]] = item
                    else:
                        self.dialog.showError("xEdit Data Error", "Pre-exported xEdit JSON is not in the expected dictionary format or is empty.")
                        return
                else: # This block handles the case where pre_exported_xedit_json_path is NOT used
                    wrapped_organizer.log(1, f"SkyGen: Determined MO2 executable name for xEdit: '{mo2_exec_name_to_use}' from path stem.")
                    wrapped_organizer.log(1, f"SkyGen: Using full export script path: {full_export_script_path}")

                    # This is the *only* call to run_xedit_export in this block now.
                    xedit_exported_json_path_from_run = run_xedit_export(
                        wrapped_organizer=wrapped_organizer,
                        dialog=self.dialog,
                        xedit_exe_path=xedit_actual_file_path,
                        xedit_mo2_name=mo2_exec_name_to_use,
                        xedit_script_path=full_export_script_path,
                        output_base_dir=Path(output_folder_path_str),
                        target_plugin_filename=target_mod_plugin_name,
                        game_version=selected_game_version,
                        target_mod_display_name=target_mod_plugin_name,
                        target_category=selected_category
                    )

                    if not xedit_exported_json_path_from_run:
                        self.dialog.showError("xEdit Export Failed", "xEdit data export failed. Check MO2 logs for details.")
                        return
                    
                    xedit_exported_data = load_json_data(wrapped_organizer, xedit_exported_json_path_from_run, "xEdit Exported Data", self.dialog)
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
                            wrapped_organizer.log(1, f"SkyGen: Cleaned up temporary xEdit export file: {xedit_exported_json_path_from_run}")
                    except Exception as e:
                        wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit export file {xedit_exported_json_path_from_run}: {e}")

                if generate_all:
                    wrapped_organizer.log(1, "SkyGen: Generating YAMLs for all applicable source mods.")
                    generated_count = 0
                    for mod_internal_name in wrapped_organizer.modList().allMods():
                        if wrapped_organizer.modList().state(mod_internal_name) & mobase.ModState.ACTIVE:
                            current_source_mo2_name = wrapped_organizer.modList().displayName(mod_internal_name)
                            current_source_plugin_name = None
                            
                            if current_source_mo2_name.lower().endswith(".esm"):
                                if current_source_mo2_name in wrapped_organizer.pluginList().pluginNames():
                                    if wrapped_organizer.pluginList().state(current_source_mo2_name) & mobase.PluginState.ACTIVE:
                                        current_source_plugin_name = current_source_mo2_name
                                        wrapped_organizer.log(0, f"SkyGen: Source mod is active base game ESM: {current_source_plugin_name}")
                            else:
                                current_source_plugin_name = self.dialog._get_plugin_name_from_mod_name(current_source_mo2_name, mod_internal_name)
                            

                            current_source_mod_base_objects_from_xedit = [
                                item for item in all_exported_target_bases_by_formid.values()
                                if item.get("originMod") == current_source_plugin_name and item.get("category") == selected_category
                            ]

                            if current_source_mod_base_objects_from_xedit:
                                wrapped_organizer.log(1, f"SkyGen: Attempting to generate YAML for '{current_source_mo2_name}'...")
                                if generate_and_write_skypatcher_yaml(
                                    wrapped_organizer,
                                    selected_category,
                                    target_mod_plugin_name,
                                    current_source_plugin_name,
                                    current_source_mo2_name,
                                    current_source_mod_base_objects_from_xedit,
                                    all_exported_target_bases_by_formid,
                                    broad_category_swap_enabled,
                                    search_keywords,
                                    self.dialog,
                                    Path(output_folder_path_str)
                                ):
                                    generated_count += 1
                            else:
                                wrapped_organizer.log(0, f"SkyGen: No relevant base objects found for '{current_source_mo2_name}' in category '{selected_category}'. Skipping.")
                    self.dialog.showInformation("Generation Complete", f"Generated {generated_count} YAML file(s). Check SkyPatcher/Configs.")

                else: # Single generation
                    wrapped_organizer.log(1, f"SkyGen: Generating single YAML for source mod: {selected_source_mod_name}")
                    
                    selected_source_mod_plugin_name = None
                    selected_source_mod_internal_name = None

                    for mod_internal_name_candidate in wrapped_organizer.modList().allMods():
                        if wrapped_organizer.modList().displayName(mod_internal_name_candidate) == selected_source_mod_name:
                            selected_source_mod_internal_name = mod_internal_name_candidate
                            wrapped_organizer.log(0, f"SkyGen: Found internal mod name for source mod '{selected_source_mod_name}': {selected_source_mod_internal_name}")
                            break
                    if not selected_source_mod_internal_name and selected_source_mod_name.lower().endswith(".esm"):
                        if selected_source_mod_name in wrapped_organizer.pluginList().pluginNames():
                            if wrapped_organizer.pluginList().state(selected_source_mod_name) & mobase.PluginState.ACTIVE:
                                selected_source_mod_internal_name = selected_source_mod_name
                                wrapped_organizer.log(0, f"SkyGen: Source mod is active base game ESM: {selected_source_mod_internal_name}")

                    if not selected_source_mod_internal_name:
                        self.dialog.showError("Mod Error", f"Could not find internal mod name for source mod '{selected_source_mod_name}'.")
                        return

                    selected_source_mod_plugin_name = self.dialog._get_plugin_name_from_mod_name(selected_source_mod_name, selected_source_mod_internal_name)
                    if not selected_source_mod_plugin_name:
                        self.dialog.showError("Plugin Selection Cancelled", f"Source mod plugin selection cancelled or failed for '{selected_source_mod_name}'.")
                        return

                    selected_source_mod_base_objects_from_xedit = [
                        item for item in all_exported_target_bases_by_formid.values()
                        if item.get("originMod") == selected_source_mod_plugin_name and item.get("category") == selected_category
                    ]

                    if selected_source_mod_base_objects_from_xedit:
                        if generate_and_write_skypatcher_yaml(
                            wrapped_organizer,
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
                wrapped_organizer.log(1, f"SkyGen: Generating BOS INI files.")
                if generate_bos_ini_files(
                    wrapped_organizer,
                    igpc_data,
                    Path(output_folder_path_str),
                    self.dialog
                ):
                    self.dialog.showInformation("Generation Complete", f"Successfully generated BOS INI files. Check output folder.")
                else:
                    self.dialog.showWarning("Generation Skipped", f"No BOS INI files generated.")

        else:
            wrapped_organizer.log(1, "SkyGen: Dialog cancelled.")

        wrapped_organizer.close_log_file()

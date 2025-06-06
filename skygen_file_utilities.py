import mobase
import os
import json
import yaml
import traceback
from pathlib import Path
from collections import defaultdict
import time
import configparser
import re

# --- Utility Functions (Global helpers) ---

def load_json_data(organizer: mobase.IOrganizer, file_path: Path, description: str, dialog_instance) -> dict | None:
    """
    Loads JSON data from a specified file path.
    Requires organizer for logging and dialog_instance for showing UI errors.
    """
    # Modified: Check if file_path is not empty AND if it points to an actual file
    if not file_path or not file_path.is_file():
        organizer.log(2, f"SkyGen: WARNING: {description} file path is invalid or file not found at: {file_path}.") # WARNING
        dialog_instance.showError("File Not Found", f"{description} file not found at the specified path: {file_path}.")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            organizer.log(1, f"SkyGen: Successfully loaded {description} from: {file_path}") # INFO
            return data
    except (IOError, json.JSONDecodeError) as e:
        organizer.log(3, f"SkyGen: ERROR: Error loading {description} from {file_path}: {e}") # ERROR
        dialog_instance.showError("File Load Error", f"Error loading {description} from {file_path}: {e}")
        return None
    except Exception as e: # Catch any other unexpected error
        organizer.log(3, f"SkyGen: ERROR: Unexpected error loading {description} from {file_path}: {e}\n{traceback.format_exc()}") # ERROR
        dialog_instance.showError("File Load Error", f"An unexpected error occurred while loading {description} from {file_path}: {e}")
        return None

def get_xedit_path_from_ini(organizer: mobase.IOrganizer, game_version: str, dialog_instance) -> tuple[Path | None, str | None]:
    """
    Reads ModOrganizer.ini to find the xEdit executable path and its MO2 display name.
    Bypasses MO2's internal executable lookup API and manually parses the INI.
    Returns a tuple: (xedit_absolute_path, mo2_executable_name) or (None, None) on failure.
    """
    mo2_base_path = Path(organizer.basePath())
    ini_file_path = mo2_base_path / "ModOrganizer.ini"

    if not ini_file_path.is_file():
        organizer.log(3, f"SkyGen: ERROR: ModOrganizer.ini not found at: {ini_file_path}.")
        dialog_instance.showError("Error", f"ModOrganizer.ini not found at the expected path: {ini_file_path}.")
        return None, None

    xedit_exec_name_map = {
        "SkyrimSE": ["SSEEdit", "SSEEdit64"], # Common MO2 display names for SSEEdit
        "SkyrimVR": ["TES5VREdit", "TES5VREdit64"], # Common MO2 display names for TES5VREdit
        "SkyrimLE": ["TES5Edit"] # Common MO2 display names for TES5Edit
    }
    expected_xedit_titles = xedit_exec_name_map.get(game_version, [])

    if not expected_xedit_titles:
        organizer.log(3, f"SkyGen: ERROR: No expected xEdit executable titles defined for game version '{game_version}'.")
        dialog_instance.showError("xEdit Lookup Error", f"No xEdit executable titles defined for game version '{game_version}'.")
        return None, None

    exec_data = defaultdict(dict)
    in_custom_executables_section = False

    try:
        with open(ini_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line == '[customExecutables]':
                    in_custom_executables_section = True
                    continue
                if in_custom_executables_section and line.startswith('['): # End of section
                    in_custom_executables_section = False
                    break # Stop parsing once out of the section

                if in_custom_executables_section and '=' in line:
                    try:
                        key_value = line.split('=', 1)
                        key = key_value[0].strip()
                        value = key_value[1].strip()

                        if '\\' in key:
                            parts = key.split('\\', 1)
                            if len(parts) == 2:
                                exec_id = parts[0]
                                prop_name = parts[1]
                                if exec_id.isdigit():
                                    exec_data[exec_id][prop_name] = value
                    except Exception as e:
                        organizer.log(2, f"SkyGen: WARNING: Error parsing INI line '{line}': {e}")
                        continue # Continue to next line even if one line fails to parse

        organizer.log(1, f"SkyGen: Successfully parsed ModOrganizer.ini for custom executables.")

        for exec_id, props in exec_data.items():
            title = props.get('title')
            binary_path_str = props.get('binary')
            
            if title and binary_path_str:
                if title in expected_xedit_titles:
                    # Resolve relative path to absolute path
                    absolute_xedit_path = Path(binary_path_str)
                    if not absolute_xedit_path.is_absolute():
                        # Paths in INI are relative to MO2's base path
                        absolute_xedit_path = mo2_base_path / binary_path_str

                    if absolute_xedit_path.is_file():
                        organizer.log(1, f"SkyGen: Found xEdit executable '{title}' at: {absolute_xedit_path}")
                        return absolute_xedit_path, title # Return path and the MO2 display name
                    else:
                        organizer.log(2, f"SkyGen: WARNING: Found xEdit entry in INI ('{title}' -> '{binary_path_str}'), but binary not found at resolved path: {absolute_xedit_path}")
                else:
                    organizer.log(0, f"SkyGen: DEBUG: Skipping non-xEdit executable in INI: '{title}')")
    except Exception as e:
        organizer.log(3, f"SkyGen: ERROR: Error reading or parsing ModOrganizer.ini from {ini_file_path}: {e}\n{traceback.format_exc()}")
        dialog_instance.showError("INI Read Error", f"Error reading or parsing ModOrganizer.ini from {ini_file_path}: {e}")
        return None, None

    organizer.log(3, f"SkyGen: ERROR: xEdit executable (for game version '{game_version}') not found in ModOrganizer.ini.")
    dialog_instance.showError("xEdit Not Found", f"xEdit executable for {game_version} was not found in your ModOrganizer.ini. Please ensure it's configured in MO2's executables.")
    return None, None


def get_game_root_from_general_ini(organizer_base_path: str, organizer_logger: mobase.IOrganizer, dialog_instance) -> Path | None:
    """
    Reads the gamePath value from the [General] section of ModOrganizer.ini.
    Purpose: To get the game's root directory for xEdit's CWD.
    """
    ini_file_path = Path(organizer_base_path) / "ModOrganizer.ini"

    if not ini_file_path.is_file():
        organizer_logger.log(3, f"SkyGen: ERROR: ModOrganizer.ini not found at: {ini_file_path}.")
        dialog_instance.showError("Error", f"ModOrganizer.ini not found at the expected path: {ini_file_path}.")
        return None

    config = configparser.ConfigParser()
    try:
        config.read(ini_file_path, encoding='utf-8')
        game_path_str = config.get('General', 'gamePath', fallback=None)

        if game_path_str:
            organizer_logger.log(0, f"SkyGen: DEBUG: Found gamePath in ModOrganizer.ini (raw): {game_path_str}")

            # Strip the @ByteArray() prefix if it exists
            if game_path_str.startswith('@ByteArray(') and game_path_str.endswith(')'):
                game_path_str = game_path_str[len('@ByteArray('):-1]
                organizer_logger.log(0, f"SkyGen: DEBUG: Stripped @ByteArray() prefix, new path string: {game_path_str}")

            game_root_path = Path(game_path_str)
            
            if game_root_path.exists():
                organizer_logger.log(1, f"SkyGen: Found game root path from ModOrganizer.ini: {game_root_path}")
                return game_root_path
            else:
                organizer_logger.log(2, f"SkyGen: WARNING: gamePath '{game_path_str}' from ModOrganizer.ini does not exist.")
                return None
        else:
            organizer_logger.log(2, "SkyGen: WARNING: gamePath not found or empty in ModOrganizer.ini [General] section.")
            return None
    except (configparser.Error, IOError) as e:
        organizer_logger.log(3, f"SkyGen: ERROR: Error reading [General] section from ModOrganizer.ini ({ini_file_path}): {e}\n{traceback.format_exc()}")
        dialog_instance.showError("INI Read Error", f"Error reading ModOrganizer.ini for game path: {e}")
        return None

def sanitize_path_for_pascal(path_str):
    """
    Replaces problematic characters in a path string for Pascal file I/O with underscores.
    Ensures no trailing spaces or periods (Windows restriction).
    """
    # Replace problematic characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', path_str)
    # Ensure no trailing spaces or periods (Windows restriction)
    sanitized = sanitized.rstrip(' .')
    return sanitized

def run_xedit_export(organizer: mobase.IOrganizer, xedit_exe_path: Path, xedit_script_path: Path, mo2_exec_name_to_use: str, target_plugin_name: str, game_version: str, output_base_dir: Path, dialog) -> Path | bool:
    """
    Runs xEdit to export data for a specific target plugin.
    This function now directly accepts xedit_exe_path, xedit_script_path, and mo2_exec_name_to_use.
    Requires organizer for logging and dialog_instance for showing UI errors.
    """
    organizer.log(1, f"SkyGen: Preparing to run xEdit export for '{target_plugin_name}'...")

    if not xedit_exe_path.is_file():
        organizer.log(3, f"SkyGen: ERROR: xEdit executable not found at provided path: {xedit_exe_path}")
        dialog.showError("xEdit Not Found", f"xEdit executable not found at the specified path: {xedit_exe_path}. Please check your configuration.")
        return False

    if not xedit_script_path.is_file():
        organizer.log(3, f"SkyGen: ERROR: xEdit script not found at provided path: {xedit_script_path}")
        dialog.showError("xEdit Script Missing", f"xEdit script 'ExportPluginData.pas' not found at {xedit_script_path}.")
        return False

    # Ensure the output directory exists and is writable
    try:
        output_base_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        organizer.log(3, f"SkyGen: ERROR: Could not create output directory: {output_base_dir}. Error: {e}")
        dialog.showError("Output Directory Error", f"Could not create output directory: {output_base_dir}. Error: {e}")
        return False

    # Test File Creation:
    try:
        test_file_path = output_base_dir / "test_write_access.tmp"
        with open(test_file_path, "w") as f:
            f.write("Test write access")
        test_file_path.unlink()  # Delete the test file
        organizer.log(1, f"SkyGen: Successfully verified write access to output directory: {output_base_dir}")
    except Exception as e:
        organizer.log(3, f"SkyGen: ERROR: Cannot write to output directory: {output_base_dir}. Error: {e}")
        dialog.showError("Output Directory Error", f"Cannot write to output directory: {output_base_dir}. Error: {e}")
        return False


    # Generate unique output paths for the JSON data and the debug log
    timestamp = int(time.time())
    
    # NEW: Create a super-sanitized stem for ALL filenames used by xEdit/Pascal
    # This removes all characters that are not alphanumeric or underscore
    # This is CRITICAL for Pascal's file I/O to work correctly with filenames containing special characters.
    super_sanitized_filename_base = sanitize_path_for_pascal(Path(target_plugin_name).stem)

    export_json_path = output_base_dir.resolve() / f"SkyGen_xEdit_Export_{super_sanitized_filename_base}_{timestamp}.json"
    export_log_path = output_base_dir.resolve() / f"SkyGen_xEdit_Log_{super_sanitized_filename_base}_{timestamp}.log"
    
    # Define the path for the Pascal script's debug log using the same super-sanitized stem
    export_pascal_debug_log_path = output_base_dir.resolve() / f"ExportPluginData_Debug_{super_sanitized_filename_base}_{timestamp}.log"

    # Check for Existing Files and potential locks
    if export_json_path.exists():
        try:
            # Try to open the file in append mode to see if it's locked
            with open(export_json_path, 'a'):
                pass
        except IOError:
            organizer.log(2, f"SkyGen: WARNING: Output JSON file exists and may be locked: {export_json_path}. Generating new filename.")
            # Generate a new unique filename if it's locked
            export_json_path = output_base_dir.resolve() / f"SkyGen_xEdit_Export_{super_sanitized_filename_base}_{timestamp}_new.json"
            organizer.log(1, f"SkyGen: Using alternative output JSON path: {export_json_path}")
    
    # Sanitize target_plugin_name for passing to Pascal script via -D:TargetPlugin
    # This is separate because it's a value passed *into* the script, not part of a filename creation.
    sanitized_plugin_name_for_script = re.sub(r'[<>:"/\\|?*&\']', '_', target_plugin_name)


    # Construct the xEdit arguments
    xedit_args = [
        # The game mode argument (-sse or -tes5vr) will be inserted here at index 0
        # by the existing logic below.

        # Arguments for the Pascal script - using double backslashes for Windows paths
        f"-o:\"{str(export_json_path).replace('\\', '\\\\')}\"",
        f"-l:\"{str(export_log_path).replace('\\', '\\\\')}\"",
        f"-debuglog:\"{str(export_pascal_debug_log_path).replace('\\', '\\\\')}\"", # Correctly passing Pascal debug log path

        # Pass the target plugin name directly for DynDOLOD-style loading
        # Using the already sanitized version to avoid issues with special characters like '&' and "'"
        f"\"{sanitized_plugin_name_for_script}\"", # CORRECTED: Now uses sanitized name for loading

        # Pass target plugin name to the Pascal script via -D:TargetPlugin, using the sanitized version
        f"-D:TargetPlugin=\"{sanitized_plugin_name_for_script}\"",

        # Pass the full, normalized path of the script
        f"-script:\"{os.path.normpath(str(xedit_script_path))}\"",

        "-IKnowWhatImDoing",
        "-NoAutoUpdate",
        "-NoAutoBackup",
        f"-b:\"{os.path.normpath(str(output_base_dir / 'Backup'))}\"", # Point backups to a subfolder
        "-autoload", # Crucial: Ensures masters are loaded automatically
        "-nomenus", # Keep -nomenus to prevent UI
        "-exit"
    ]

    # Add game mode argument (this existing logic will insert at index 0)
    game_mode_arg = {
        "SkyrimSE": "-sse",
        "SkyrimVR": "-tes5vr"
    }.get(game_version)
    if game_mode_arg:
        xedit_args.insert(0, game_mode_arg)
    else:
        organizer.log(2, f"No specific game mode argument for xEdit for game version '{game_version}'. Launching without it.")

    organizer.log(1, f"SkyGen: Using MO2 executable name '{mo2_exec_name_to_use}' for xEdit.")

    # Determine the current working directory for MO2's startApplication
    cwd_path = None

    # Attempt 1: Get game root from ModOrganizer.ini directly (HIGHEST PRIORITY)
    game_root_candidate = get_game_root_from_general_ini(
        organizer.basePath(), # Pass MO2's base path to the helper
        organizer,            # Pass organizer for logging
        dialog                # Pass dialog for UI errors
    )
    if game_root_candidate and game_root_candidate.exists():
        cwd_path = game_root_candidate
        organizer.log(0, f"SkyGen: DEBUG: Using game root path from ModOrganizer.ini (highest priority): {cwd_path}")
    else:
        organizer.log(2, "SkyGen: WARNING: Could not get game root from ModOrganizer.ini or path does not exist. Trying fallback.")

    # Fallback 1: Use MO2's overwrite path (SECOND PRIORITY)
    if not cwd_path:
        overwrite_path = Path(organizer.overwritePath())
        if overwrite_path.exists():
            cwd_path = overwrite_path
            organizer.log(0, f"SkyGen: DEBUG: Falling back to MO2 overwrite path as CWD: {cwd_path}")
        else:
            organizer.log(2, f"SkyGen: WARNING: MO2 overwrite path does not exist: {overwrite_path}. Trying further fallback.")

    # Fallback 2: MO2 base path (LAST RESORT)
    if not cwd_path:
        if organizer.basePath():
            cwd_path = Path(organizer.basePath())
            organizer.log(2, f"SkyGen: WARNING: Falling back to MO2 base path as CWD: {cwd_path}")
        else:
            cwd_path = xedit_exe_path.parent
            organizer.log(2, f"SkyGen: WARNING: MO2 base path not valid, falling back to xEdit directory as CWD: {cwd_path}")

    cwd = os.path.normpath(str(cwd_path))
    organizer.log(0, f"SkyGen: DEBUG: Final CWD set for xEdit: {cwd}")
    
    # Verify Working Directory:
    if not cwd_path or not cwd_path.exists():
        organizer.log(3, f"SkyGen: ERROR: Working directory does not exist or is not accessible: {cwd_path}")
        dialog.showError("Working Directory Error", f"The working directory does not exist or is not accessible: {cwd_path}")
        return False
    else:
        organizer.log(1, f"SkyGen: Working directory exists: {cwd_path}")

    # Add Debug Logging:
    organizer.log(0, f"SkyGen: DEBUG: Full xEdit command: {' '.join(xedit_args)}")
    organizer.log(0, f"SkyGen: DEBUG: Export JSON path: {export_json_path}")
    organizer.log(0, f"SkyGen: DEBUG: Export log path: {export_log_path}")
    organizer.log(0, f"SkyGen: DEBUG: Pascal debug log path: {export_pascal_debug_log_path}")
    organizer.log(0, f"SkyGen: DEBUG: Current working directory: {cwd_path}")
    
    try:
        # Improve error handling when starting xEdit
        app_handle = organizer.startApplication(mo2_exec_name_to_use, xedit_args, str(cwd))
        if app_handle == 0:
            organizer.log(3, f"SkyGen: ERROR: Failed to start xEdit application.")
            dialog.showError("xEdit Launch Error", "Failed to start xEdit application.")
            return False

        organizer.log(1, f"xEdit launched with handle: {app_handle}. Polling for output file: {export_json_path}")

        max_poll_time = 60 # seconds
        wait_interval = 1   # seconds
        elapsed_time = 0
        while elapsed_time < max_poll_time:
            if export_json_path.is_file() and export_json_path.stat().st_size > 0:
                organizer.log(1, f"xEdit output file found and is not empty: {export_json_path}")
                # Brief pause to ensure file write is complete
                time.sleep(2)
                return export_json_path # Return the actual path
            
            # Check if xEdit process has exited prematurely
            # This is a basic check; real-world MO2 might offer process polling API
            # For now, rely on file creation as the primary indicator
            # if not organizer.isApplicationRunning(app_handle):
            #     organizer.log(3, "SkyGen: ERROR: xEdit process exited before output file was created.")
            #     dialog.showError("xEdit Error", "xEdit process exited prematurely. Check xEdit logs for errors.")
            #     return False

            organizer.log(0, f"Waiting for xEdit export ({elapsed_time}/{max_poll_time}s)... Output: {export_json_path.exists()}, Size: {export_json_path.stat().st_size if export_json_path.exists() else 'N/A'}")
            time.sleep(wait_interval)
            elapsed_time += wait_interval
        
        # Timeout occurred
        dialog.showError("xEdit Timeout", f"xEdit output file '{export_json_path.name}' was not created or was empty after {max_poll_time} seconds. Check xEdit logs for errors.")
        return False

    except Exception as e:
        organizer.log(4, f"Error launching or running xEdit: {e}\n{traceback.format_exc()}")
        dialog.showError("xEdit Error", f"An unexpected error occurred while trying to run xEdit: {e}. Check MO2 logs for more details.")
        return False
    finally:
        # Add this right after running xEdit
        # Check if logs were created, if not, check xEdit's default location
        if not export_pascal_debug_log_path.exists() or export_pascal_debug_log_path.stat().st_size == 0:
            organizer.log(2, f"SkyGen: WARNING: Pascal debug log not found or empty at expected path: {export_pascal_debug_log_path}")
            # Check xEdit directory for logs
            xedit_dir = xedit_exe_path.parent
            default_logs = list(xedit_dir.glob("ExportPluginData_Debug*.log"))
            if default_logs:
                organizer.log(1, f"SkyGen: Found potential debug logs in xEdit directory: {default_logs}")
            else:
                organizer.log(1, f"SkyGen: No Pascal debug logs found in xEdit directory ({xedit_dir}).")


def generate_replacements(organizer: mobase.IOrganizer, igpc_data: dict, selected_category: str, target_mod_plugin_name: str, source_mod_plugin_name: str, source_mod_mo2_name: str, source_mod_base_objects_from_xedit: list, all_exported_target_bases_by_formid: dict, broad_category_swap_enabled: bool, dialog_instance) -> list:
    """
    Generates replacement entries based on IGPC data, used primarily for BOS.
    This function remains as is, as it's used by generate_bos_ini_files.
    """
    replacements = []
    grouped_replacements = defaultdict(lambda: {"newBase": None, "references": set()})

    representative_source_base = None
    if broad_category_swap_enabled and source_mod_base_objects_from_xedit:
        sorted_source_bases = sorted(source_mod_base_objects_from_xedit, key=lambda x: x.get('EDID', '').lower() if x.get('EDID') else '')
        representative_source_base = sorted_source_bases[0]
        organizer.log(0, f"Broad Category Swap: Representative source base for category '{selected_category}' from '{source_mod_mo2_name}' is '{representative_source_base.get('EDID', 'N/A')}' (FormID: {representative_source_base.get('FormID', 'N/A')}).") # DEBUG

    igpc_records = igpc_data.get("records", [])
    if not isinstance(igpc_records, list):
        organizer.log(3, "IGPC JSON 'records' field is not a list. Aborting YAML generation for this mod.") # ERROR
        dialog_instance.showError("Error", "IGPC JSON format error: 'records' field is not a list.")
        return [] # Return empty list on error

    for ref_entry in igpc_records:
        ref_form_id = ref_entry.get("formId")
        base_object_form_id_from_igpc = ref_entry.get("base")
        ref_origin_mod_from_igpc = ref_entry.get("sourceName") # Plugin name of the reference itself

        if not ref_form_id or not base_object_form_id_from_igpc or not ref_origin_mod_from_igpc:
            organizer.log(2, f"Skipping IGPC reference due to missing formId, base, or sourceName: {ref_entry}") # WARNING
            continue

        base_info_from_xedit = all_exported_target_bases_by_formid.get(base_object_form_id_from_igpc)

        if not base_info_from_xedit:
            organizer.log(0, f"Base object {base_object_form_id_from_igpc} (from IGPC reference {ref_form_id}) not found in xEdit's exported base objects. Skipping.") # DEBUG
            continue

        base_origin_mod_from_xedit = base_info_from_xedit.get("originMod")
        base_category_from_xedit = base_info_from_xedit.get("category")
        base_edid_from_xedit = base_info_from_xedit.get("EDID")

        if base_origin_mod_from_xedit == target_mod_plugin_name and base_category_from_xedit == selected_category: # Only check category if broad swap is enabled, otherwise EDID match is primary
            new_base_form_id_from_source = None
            new_base_plugin_name = source_mod_plugin_name # Default to source mod for newBase

            if broad_category_swap_enabled:
                if representative_source_base:
                    new_base_form_id_from_source = representative_source_base.get('FormID')
                else:
                    organizer.log(2, f"Broad Category Swap enabled for '{selected_category}' but no representative source base found for '{source_mod_mo2_name}'. Skipping reference {ref_form_id}.") # WARNING
                    continue
            else: # Standard EDID matching
                if base_edid_from_xedit:
                    source_bases_by_edid = {obj.get("EDID"): obj.get("formId") for obj in source_mod_base_objects_from_xedit if obj.get("EDID") and obj.get("formId")}
                    found_source_base_formid = source_bases_by_edid.get(base_edid_from_xedit)
                    
                    if found_source_base_formid:
                        new_base_form_id_from_source = found_source_base_formid
                    else:
                        organizer.log(0, f"No EDID match for '{base_edid_from_xedit}' in source mod '{source_mod_plugin_name}' for category '{selected_category}'. Skipping reference {ref_form_id}.") # DEBUG
                        continue # Skip if no EDID match in standard mode
                else:
                    organizer.log(0, f"Base object {base_object_form_id_from_igpc} from target mod has no EDID. Skipping reference {ref_form_id}.") # DEBUG
                    continue # Skip if target base has no EDID in standard mode

            if new_base_form_id_from_source:
                new_base_identifier = f"{new_base_plugin_name}|{new_base_form_id_from_source}"
                # The reference here is the target mod's base object that needs to be replaced
                reference_identifier = f"{base_origin_mod_from_xedit}|{base_object_form_id}"
                
                grouped_replacements[new_base_identifier]["newBase"] = new_base_identifier
                grouped_replacements[new_base_identifier]["references"].add(reference_identifier)
            else:
                organizer.log(2, f"Could not determine new base for target base object {base_object_form_id} from {base_origin_mod_from_xedit}.") # WARNING

    # Convert grouped replacements to the final list format
    for _, data in grouped_replacements.items():
        if data["newBase"] and data["references"]:
            replacements.append({
                "newBase": data["newBase"],
                "references": sorted(list(data["references"]))
            })
    
    return replacements # Return the correctly formatted list


def generate_bos_ini_files(organizer: mobase.IOrganizer, igpc_data: dict, output_base_dir: Path, dialog_instance) -> bool:
    """
    Generates .ini files for Base Object Swapper (BOS) based on the provided IGPC data.
    It creates Pos_ and Remove_ INI files, grouped by source plugin, with specific formatting.
    """
    organizer.log(1, "SkyGen: Starting generation of BOS .ini files...")

    def _format_bos_form_id(form_id: str, source_name: str) -> str:
        """
        Formats a raw FormID string for BOS based on the source plugin type.
        - Ensures '0x' prefix and uppercase.
        - Handles base game ESMs, ESLs, and other ESPs specifically.
        """
        clean_form_id = form_id.lstrip("0x").upper()

        # Base game ESMs (Skyrim.esm, Update.esm, Dawnguard.esm, HearthFires.esm, Dragonborn.esm)
        base_esms = ["SKYRIM.ESM", "UPDATE.ESM", "DAWNGUARD.ESM", "HEARTHFIRES.ESM", "DRAGONBORN.ESM"]
        if source_name.upper() in base_esms:
            try:
                # Convert to int, then back to hex to strip redundant leading zeros
                # e.g., "00001234" -> "0x1234"
                return hex(int(clean_form_id, 16)).upper().replace("X", "x") # Ensure lowercase 'x'
            except ValueError:
                organizer.log(3, f"SkyGen: ERROR: Invalid FormID '{form_id}' for base ESM '{source_name}'. Returning as is with 0x prefix.")
                return f"0x{clean_form_id}"

        # FormIDs starting with FE or plugins ending in .esl (ESL-flagged ESPs or true ESLs)
        if clean_form_id.startswith("FE") or source_name.lower().endswith(".esl"):
            # For ESLs, BOS uses the last 3 characters of the FormID
            if len(clean_form_id) >= 3:
                return f"0xFE{clean_form_id[-3:]}"
            else:
                organizer.log(3, f"SkyGen: ERROR: ESL FormID '{form_id}' too short for '{source_name}'. Returning as is with 0xFE prefix.")
                return f"0xFE{clean_form_id}" # Fallback for malformed ESL ID

        # Other .esps
        # Assumes the first two characters are the load order prefix
        if len(clean_form_id) > 2:
            try:
                # Strip load order prefix, convert to int, then back to hex to strip leading zeros
                # e.g., "01001234" -> "0x1234"
                return hex(int(clean_form_id[2:], 16)).upper().replace("X", "x") # Ensure lowercase 'x'
            except ValueError:
                organizer.log(3, f"SkyGen: ERROR: Invalid FormID '{form_id}' for ESP '{source_name}'. Returning as is with 0x prefix.")
                return f"0x{clean_form_id}"
        else:
            organizer.log(3, f"SkyGen: ERROR: ESP FormID '{form_id}' too short for '{source_name}'. Returning as is with 0x prefix.")
            return f"0x{clean_form_id}" # Fallback for malformed ESP ID


    bos_output_dir = output_base_dir / "BosExtender_Generated"
    bos_output_dir.mkdir(parents=True, exist_ok=True) # Ensure output directory exists

    pos_entries_by_source = defaultdict(list)
    remove_entries_by_source = defaultdict(list)

    igpc_records = igpc_data.get("records", [])
    if not isinstance(igpc_records, list):
        organizer.log(3, "IGPC JSON 'records' field is not a list. Aborting BOS INI generation.")
        dialog_instance.showError("Error", "IGPC JSON format error: 'records' field is not a list for BOS INI generation.")
        return False

    for record in igpc_records:
        form_id = record.get("formId")
        is_disabled = record.get("isDisabled")
        source_name = record.get("sourceName") # Original plugin name of the reference

        if not form_id or not source_name:
            organizer.log(2, f"Skipping IGPC record for BOS due to missing 'formId' or 'source_name': {record}")
            continue

        # Format the FormID using the refined helper
        formatted_form_id = _format_bos_form_id(form_id, source_name)

        # Construct the INI key part: FORMID~SOURCE_PLUGIN
        ini_key = f"{formatted_form_id}~{source_name}"

        if is_disabled == 1:
            # Remove_ INI Format: FORMID~SOURCE_PLUGIN|0x3B~Skyrim.esm|posA(0.0,0.0,-30000.0),RotA(0.0,0.0,0.0)
            # The '0x3B~Skyrim.esm' is the fixed target FormID for removal/dummy.
            # The posA/RotA is the instruction to move it far away.
            target_plugin_form_id = "0x3B~Skyrim.esm" # This is a specific BOS dummy target often used
            dummy_pos_rot = "posA(0.000000,0.000000,-30000.000000),RotA(0.000000,0.000000,0.000000)"
            
            value_string = f"{target_plugin_form_id}|{dummy_pos_rot}"
            full_entry_string = f"{ini_key}|{value_string}"
            remove_entries_by_source[source_name].append(full_entry_string)
        else:
            # Pos_ INI Format: FORMID~SOURCE_PLUGIN|posA(X,Y,Z),RotA(X,Y,Z),Scale(S)
            pos_x = record.get("posX")
            pos_y = record.get("posY")
            pos_z = record.get("posZ")
            rot_x = record.get("rotX")
            rot_y = record.get("rotY")
            rot_z = record.get("rotZ")
            scale = record.get("scale")

            if all(v is not None for v in [pos_x, pos_y, pos_z, rot_x, rot_y, rot_z, scale]):
                pos_value_part = f"posA({pos_x:.6f},{pos_y:.6f},{pos_z:.6f})"
                rot_value_part = f"RotA({rot_x:.6f},{rot_y:.6f},{rot_z:.6f})"
                scale_value_part = f"Scale({scale:.6f})"
                
                value_string = f"{pos_value_part},{rot_value_part},{scale_value_part}"
                full_entry_string = f"{ini_key}|{value_string}"
                pos_entries_by_source[source_name].append(full_entry_string)
            else:
                organizer.log(2, f"Skipping Pos_ BOS entry for {form_id} due to incomplete position/rotation/scale data: {record}")


    generated_count = 0
    # Write Remove_ INI files
    for source_name, entries in remove_entries_by_source.items():
        if entries:
            sanitized_source_name = Path(source_name).stem.replace(' ', '_').replace("'", "")
            ini_filename = f"Remove_{sanitized_source_name}_SWAP.ini" # Updated suffix
            ini_file_path = bos_output_dir / ini_filename
            try:
                with open(ini_file_path, 'w', encoding='utf-8') as f:
                    f.write("[References]\n") # Header for Remove_ INIs
                    for entry_string in entries:
                        f.write(f"{entry_string}\n")
                organizer.log(1, f"Generated BOS Remove_ INI file: {ini_file_path}")
                generated_count += 1
            except Exception as e:
                organizer.log(3, f"Error generating BOS Remove_ INI file {ini_file_path}: {e}\n{traceback.format_exc()}")
                dialog_instance.showError("BOS File Generation Error", f"Failed to generate BOS Remove_ INI file: {ini_file_path}\nError: {e}")
                return False

    # Write Pos_ INI files
    for source_name, entries in pos_entries_by_source.items():
        if entries:
            sanitized_source_name = Path(source_name).stem.replace(' ', '_').replace("'", "")
            ini_filename = f"Pos_{sanitized_source_name}_SWAP.ini" # Updated suffix
            ini_file_path = bos_output_dir / ini_filename
            try:
                with open(ini_file_path, 'w', encoding='utf-8') as f:
                    f.write("[Transforms]\n") # Header for Pos_ INIs
                    for entry_string in entries:
                        f.write(f"{entry_string}\n")
                organizer.log(1, f"Generated BOS Pos_ INI file: {ini_file_path}")
                generated_count += 1
            except Exception as e:
                organizer.log(3, f"Error generating BOS Pos_ INI file {ini_file_path}: {e}\n{traceback.format_exc()}")
                dialog_instance.showError("BOS File Generation Error", f"Failed to generate BOS Pos_ INI file: {ini_file_path}\nError: {e}")
                return False

    if generated_count > 0:
        organizer.log(1, f"Successfully generated {generated_count} BOS .ini files.")
        return True
    else:
        organizer.log(1, "No BOS .ini files were generated (no valid entries found).")
        return False

def generate_skypatcher_replacements(organizer: mobase.IOrganizer, selected_category: str, target_mod_plugin_name: str, source_mod_plugin_name: str, source_mod_mo2_name: str, source_mod_base_objects_from_xedit: list, all_exported_target_bases_by_formid: dict, broad_category_swap_enabled: bool, dialog_instance) -> list:
    """
    Generates SkyPatcher replacement entries based on xEdit-exported base object data.
    This function does NOT use IGPC data directly.
    """
    replacements = []
    grouped_replacements = defaultdict(lambda: {"newBase": None, "references": set()})

    representative_source_base = None
    if broad_category_swap_enabled and source_mod_base_objects_from_xedit:
        sorted_source_bases = sorted(source_mod_base_objects_from_xedit, key=lambda x: x.get('EDID', '').lower() if x.get('EDID') else '')
        representative_source_base = sorted_source_bases[0]
        organizer.log(0, f"Broad Category Swap: Representative source base for category '{selected_category}' from '{source_mod_mo2_name}' is '{representative_source_base.get('EDID', 'N/A')}' (FormID: {representative_source_base.get('FormID', 'N/A')}).") # DEBUG

    # Iterate through the target mod's base objects exported by xEdit
    for base_object_form_id, base_info_from_xedit in all_exported_target_bases_by_formid.items():
        base_origin_mod_from_xedit = base_info_from_xedit.get("originMod")
        base_category_from_xedit = base_info_from_xedit.get("category")
        base_edid_from_xedit = base_info_from_xedit.get("EDID")

        # Only process base objects originating from the target mod and matching the selected category
        if base_origin_mod_from_xedit == target_mod_plugin_name and base_category_from_xedit == selected_category:
            new_base_form_id_from_source = None
            new_base_plugin_name = source_mod_plugin_name # Default to source mod for newBase

            if broad_category_swap_enabled:
                if representative_source_base:
                    new_base_form_id_from_source = representative_source_base.get('FormID')
                else:
                    organizer.log(2, f"Broad Category Swap enabled for '{selected_category}' but no representative source base found for '{source_mod_mo2_name}'. Skipping target base {base_object_form_id}.") # WARNING
                    continue
            else: # Standard EDID matching
                if base_edid_from_xedit:
                    source_bases_by_edid = {obj.get("EDID"): obj.get("formId") for obj in source_mod_base_objects_from_xedit if obj.get("EDID") and obj.get("formId")}
                    found_source_base_formid = source_bases_by_edid.get(base_edid_from_xedit)
                    
                    if found_source_base_formid:
                        new_base_form_id_from_source = found_source_base_formid
                    else:
                        organizer.log(0, f"No EDID match for '{base_edid_from_xedit}' in source mod '{source_mod_plugin_name}' for category '{selected_category}'. Skipping target base {base_object_form_id}.") # DEBUG
                        continue # Skip if no EDID match in standard mode
                else:
                    organizer.log(0, f"Target base object {base_object_form_id} has no EDID. Skipping.") # DEBUG
                    continue # Skip if target base has no EDID in standard mode

            if new_base_form_id_from_source:
                new_base_identifier = f"{new_base_plugin_name}|{new_base_form_id_from_source}"
                # The reference here is the target mod's base object that needs to be replaced
                reference_identifier = f"{base_origin_mod_from_xedit}|{base_object_form_id}"
                
                grouped_replacements[new_base_identifier]["newBase"] = new_base_identifier
                grouped_replacements[new_base_identifier]["references"].add(reference_identifier)
            else:
                organizer.log(2, f"Could not determine new base for target base object {base_object_form_id} from {base_origin_mod_from_xedit}.") # WARNING

    # Convert grouped replacements to the final list format
    for _, data in grouped_replacements.items():
        if data["newBase"] and data["references"]:
            replacements.append({
                "newBase": data["newBase"],
                "references": sorted(list(data["references"]))
            })
    
    return replacements # Return the correctly formatted list


def generate_and_write_skypatcher_yaml(organizer: mobase.IOrganizer, selected_category: str, target_mod_plugin_name: str, source_mod_plugin_name: str, source_mod_mo2_name: str, source_mod_base_objects_from_xedit: list, all_exported_target_bases_by_formid: dict, broad_category_swap_enabled: bool, search_keywords: str, dialog_instance, output_base_dir: Path) -> int: # Return 1 if YAML generated, 0 otherwise
    """
    Generates the SkyPatcher YAML content and writes it to a file within the specified output_base_dir
    (e.g., OutputFolder/SkyPatcher/Configs/). Returns 1 on success, 0 on failure/no replacements.
    This function now calls generate_skypatcher_replacements.
    Requires organizer for logging and dialog_instance for showing UI errors.
    The output_base_dir is now the root for SkyPatcher YAML files.
    """
    organizer.log(1, f"Generating YAML for source mod: {source_mod_mo2_name} (Plugin: {source_mod_plugin_name})") # INFO

    # Call the new function to generate replacements without IGPC data
    replacements = generate_skypatcher_replacements(
        organizer,
        selected_category,
        target_mod_plugin_name,
        source_mod_plugin_name,
        source_mod_mo2_name,
        source_mod_base_objects_from_xedit,
        all_exported_target_bases_by_formid,
        broad_category_swap_enabled,
        dialog_instance
    )

    if not replacements:
        organizer.log(1, f"No replacements generated for '{source_mod_mo2_name}' in category '{selected_category}'.") # INFO
        return 0

    yaml_data = {
        "replacements": replacements
    }
    
    # Determine the output path: MO2_Mod_Path/SkyPatcher/Configs/
    skypatcher_mod_path = None
    for mod_name in organizer.modList().allMods():
        mod_obj = organizer.getMod(mod_name)
        if mod_obj and mod_obj.displayName().lower() == "skypatcher": # Case-insensitive check
            # Changed from mobase.ModState.ACTIVE to mobase.ModState.ENABLED
            if organizer.modList().state(mod_name) & mobase.ModState.ENABLED: # Check if the mod is ENABLED (checked in left pane)
                skypatcher_mod_path = Path(mod_obj.absolutePath())
                break

    if skypatcher_mod_path is None:
        # If SkyPatcher mod is not found via MO2's mod list (e.g., if it's not a regular mod but part of MO2 install, or not enabled)
        # We will use the provided output_base_dir as the root and append "SkyPatcher/Configs"
        organizer.log(2, "SkyPatcher mod not found as an enabled mod in MO2. Using the selected output folder as the base for SkyPatcher/Configs.")
        output_dir = output_base_dir / "SkyPatcher" / "Configs"
    else:
        output_dir = skypatcher_mod_path / "SkyPatcher" / "Configs"
    
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        dialog_instance.showError("File System Error", f"Failed to create output directory {output_dir}:\n{e}")
        organizer.log(4, f"Failed to create output directory {output_dir}: {e}") # CRITICAL
        return 0

    # Sanitize the category name for the filename
    sanitized_category = "".join(c for c in selected_category if c.isalnum() or c in (' ', '-', '_')).strip()
    sanitized_category = sanitized_category.replace(' ', '-')

    # Filename format: SourceModMO2Name-Category-Replacements.yaml
    yaml_file_name = f"{source_mod_mo2_name}-{sanitized_category}-Replacements.yaml"
    yaml_file_path = output_dir / yaml_file_name
    
    try:
        with open(yaml_file_path, 'w', encoding='utf-8') as file:
            yaml.dump(yaml_data, file, default_flow_style=False, indent=2, sort_keys=False)
        organizer.log(1, f"YAML file created at {yaml_file_path}") # INFO
        return 1 # Success
    except Exception as e:
        dialog_instance.showError("File Write Error", f"Failed to write YAML file to {yaml_file_path}:\n{e}")
        organizer.log(4, f"Failed to write YAML file to {yaml_file_path}: {e}") # CRITICAL
        return 0

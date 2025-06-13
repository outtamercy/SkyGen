from pathlib import Path
import mobase
import os
import time
import subprocess
import json
import yaml
import configparser
import re
import traceback
from collections import defaultdict
from typing import Optional


# Define a constant for max poll time
MAX_POLL_TIME = 60 # Maximum seconds to wait for xEdit export to complete (increased from 30)


# --- Utility Functions (Global helpers) ---

def load_json_data(organizer: mobase.IOrganizer, file_path: Path, description: str, dialog_instance) -> dict | None:
    """
    Loads JSON data from a specified file path.
    Requires organizer for logging and dialog_instance for showing UI errors.
    """
    if not file_path or not file_path.is_file():
        organizer.log(2, f"SkyGen: WARNING: {description} file path is invalid or file not found at: {file_path}.") # WARNING
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Not Found", f"{description} file not found at the specified path: {file_path}.")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            organizer.log(1, f"SkyGen: Successfully loaded {description} from: {file_path}") # INFO
            return data
    except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e: # Added UnicodeDecodeError
        organizer.log(3, f"SkyGen: ERROR: Error loading {description} from {file_path}: {e}") # ERROR
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Load Error", f"Error loading {description} from {file_path}: {e}")
        return None
    except Exception as e: # Catch any other unexpected error
        organizer.log(3, f"SkyGen: ERROR: Unexpected error loading {description} from {file_path}: {e}\n{traceback.format_exc()}") # ERROR
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Load Error", f"An unexpected error occurred while loading {description} from {file_path}: {e}")
        return None

def get_xedit_path_from_ini(organizer: mobase.IOrganizer, game_version: str, dialog_instance=None) -> tuple[Path | None, str | None]:
    """
    Reads ModOrganizer.ini to find the xEdit executable path and its MO2 display name.
    Bypasses MO2's internal executable lookup API and manually parses the INI.
    Returns a tuple: (xedit_absolute_path, mo2_executable_name) or (None, None) on failure.
    """
    mo2_base_path = Path(organizer.basePath())
    ini_file_path = mo2_base_path / "ModOrganizer.ini"

    if not ini_file_path.is_file():
        organizer.log(3, f"SkyGen: ERROR: ModOrganizer.ini not found at: {ini_file_path}.")
        # Removed dialog_instance.showError() here, handled by caller
        return None, None

    xedit_exec_name_map = {
        "SkyrimSE": ["SSEEdit", "SSEEdit64"], # Common MO2 display names for SSEEdit
        "SkyrimVR": ["TES5VREdit", "TES5VREdit64"], # Common MO2 display names for TES5VREdit
        "SkyrimLE": ["TES5Edit"] # Common MO2 display names for TES5Edit
    }
    expected_xedit_titles = xedit_exec_name_map.get(game_version, [])

    if not expected_xedit_titles:
        organizer.log(3, f"SkyGen: ERROR: No expected xEdit executable titles defined for game version '{game_version}'.")
        # Removed dialog_instance.showError() here, handled by caller
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
                    organizer.log(0, f"SkyGen: DEBUG: Skipping non-xEdit executable in INI: '{title}'")
    except Exception as e:
        organizer.log(3, f"SkyGen: ERROR: Error reading or parsing ModOrganizer.ini from {ini_file_path}: {e}\n{traceback.format_exc()}")
        # Removed dialog_instance.showError() here, handled by caller
        return None, None

    organizer.log(3, f"SkyGen: ERROR: xEdit executable (for game version '{game_version}') not found in ModOrganizer.ini.")
    # Removed dialog_instance.showError() here, handled by caller
    return None, None


def get_game_root_from_general_ini(organizer_base_path: str, organizer_logger: mobase.IOrganizer, dialog_instance=None) -> Path | None:
    """
    Reads the gamePath value from the [General] section of ModOrganizer.ini.
    Purpose: To get the game's root directory for xEdit's CWD.
    """
    ini_file_path = Path(organizer_base_path) / "ModOrganizer.ini"

    if not ini_file_path.is_file():
        organizer_logger.log(3, f"SkyGen: ERROR: ModOrganizer.ini not found at: {ini_file_path}.")
        # Removed dialog_instance.showError() here, handled by caller
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
        # Removed dialog_instance.showError() here, handled by caller
        return None


def get_xedit_exe_path(config_data: dict, wrapped_organizer: mobase.IOrganizer, dialog_instance=None) -> tuple[Path | None, str | None]:
    """
    Determines the SSEEdit.exe path and its MO2 configured name, prioritizing:
    1. Path and name found in ModOrganizer.ini via get_xedit_path_from_ini.
    2. Path and name specified in config.json.
    3. Auto-detected path from MO2's managed game directory (fallback, name will be inferred).
    Returns (Path, str) for path and MO2 executable name, or (None, None).
    """
    game_version_from_config = config_data.get("selected_game_version", "SkyrimSE")

    # 1. Try reading from ModOrganizer.ini first
    # Pass dialog_instance to get_xedit_path_from_ini so it can show errors if necessary
    xedit_path_from_ini, mo2_name_from_ini = get_xedit_path_from_ini(wrapped_organizer, game_version_from_config, dialog_instance)
    if xedit_path_from_ini and xedit_path_from_ini.is_file():
        wrapped_organizer.log(1, f"SkyGen: Found xEdit.exe from ModOrganizer.ini: {xedit_path_from_ini} (MO2 name: {mo2_name_from_ini})")
        return xedit_path_from_ini, mo2_name_from_ini

    # 2. Fallback to the path from config.json
    path_from_config_str = config_data.get("xedit_exe_path", "")
    mo2_name_from_config = config_data.get("xedit_mo2_name", "")
    path_from_config = Path(path_from_config_str).expanduser() if path_from_config_str else None

    if path_from_config and path_from_config.is_file():
        wrapped_organizer.log(1, f"SkyGen: Using xEdit.exe path from config.json: {path_from_config} (MO2 name: {mo2_name_from_config or 'N/A'})")
        return path_from_config, mo2_name_from_config or path_from_config.stem # Use stem if MO2 name isn't explicit in config

    # 3. Fallback to MO2's managed game path detection
    try:
        mo2_game_root_path = Path(wrapped_organizer.managedGame().gamePath())
        auto_detected_from_game_path = mo2_game_root_path / "tools/SSEEdit/SSEEdit.exe"
        if auto_detected_from_game_path.exists():
            inferred_mo2_name = auto_detected_from_game_path.stem # Infer name from filename
            wrapped_organizer.log(1, f"SkyGen: Auto-detected SSEEdit.exe from MO2 game path: {auto_detected_from_game_path} (Inferred MO2 name: {inferred_mo2_name})")
            return auto_detected_from_game_path, inferred_mo2_name
    except Exception as e:
        wrapped_organizer.log(1, f"SkyGen: MO2 game path detection for SSEEdit failed: {e}")

    wrapped_organizer.log(3, "SkyGen: ERROR: Could not locate SSEEdit.exe. Check MO2 config, ModOrganizer.ini, game path, or update config.json.")
    # Do not raise FileNotFoundError here; return None to allow the calling context to handle it gracefully in the UI.
    return None, None


def sanitize_path_for_pascal(path_str: str) -> str:
    """
    Replaces problematic characters in a filename (not full path) for Pascal file I/O with underscores.
    Ensures no trailing spaces or periods (Windows restriction).
    Note: This should only be used for filenames, not full paths.
    """
    # Replace problematic characters with underscores (including apostrophes and ampersands)
    sanitized = re.sub(r'[<>:"|?*&\']', '_', path_str)
    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')
    # Ensure no trailing spaces or periods (Windows restriction).
    sanitized = sanitized.rstrip(' .')
    return sanitized


def write_xedit_ini_for_skygen(xedit_exe_path: Path, wrapped_organizer: mobase.IOrganizer, dialog_instance):
    """
    Writes a temporary INI file for xEdit to ensure it loads necessary plugins
    and uses the correct game mode for the export script.
    """
    if not xedit_exe_path:
        wrapped_organizer.log(3, "SkyGen: ERROR: xEdit executable path is not provided to write INI.")
        return

    ini_path = xedit_exe_path.with_suffix('.ini')
    wrapped_organizer.log(1, f"SkyGen: Attempting to write temporary xEdit INI to: {ini_path}")

    # Map game names to their full display names (for INI section) and short arguments (for GameMode setting)
    game_name_map = {
        "SkyrimSE": "Skyrim Special Edition",
        "SkyrimVR": "Skyrim VR",
        "Fallout4": "Fallout4",
        "FalloutNV": "FalloutNV",
        "Oblivion": "Oblivion",
        "Skyrim": "Skyrim"  # For TES5Edit
    }
    
    game_mode_arg_map = {
        "Skyrim Special Edition": "SSE",
        "Skyrim VR": "TES5VR",
        "Fallout4": "FO4",
        "FalloutNV": "FNV",
        "Oblivion": "TES4",
        "Skyrim": "TES5"
    }

    # Determine the game name from the active managed game
    detected_game_name_str = "Skyrim Special Edition"  # Default if detection fails
    if wrapped_organizer.managedGame():
        actual_game = wrapped_organizer.managedGame()
        if hasattr(actual_game, 'gameName'):  # Check for gameName()
            detected_game_name_str = actual_game.gameName()  # Use gameName()
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Detected game name from managedGame(): {detected_game_name_str}")
        else:
            wrapped_organizer.log(2, f"SkyGen: WARNING: managedGame() object has no attribute 'gameName'. Using default game name for INI: {detected_game_name_str}")
    else:
        wrapped_organizer.log(2, f"SkyGen: WARNING: managedGame() object is None. Using default game name for INI: {detected_game_name_str}")

    import configparser
    config = configparser.ConfigParser()
    config.optionxform = str  # Preserve case for options

    section_name = f"{Path(xedit_exe_path.name).stem} {detected_game_name_str}"  # e.g., "SSEEdit Skyrim Special Edition"
    
    # Ensure section exists
    if section_name not in config:
        config[section_name] = {}

    config[section_name]['AllowMasterFileEdit'] = 'TRUE'  # Required for script to modify masters if needed
    config[section_name]['Expert'] = 'TRUE'  # Usually enables more features/options
    config[section_name]['AllowMultipleInstances'] = 'TRUE'  # Important for automation

    # Set GameMode based on the detected game name
    determined_game_mode_arg = game_mode_arg_map.get(detected_game_name_str, "SSE")  # Default to SSE if not found in map
    if determined_game_mode_arg:
        config[section_name]['GameMode'] = determined_game_mode_arg
        wrapped_organizer.log(1, f"SkyGen: Set INI GameMode to: {determined_game_mode_arg}")
    else:
        wrapped_organizer.log(2, f"SkyGen: Could not map detected game name '{detected_game_name_str}' to specific GameMode INI argument. Using default if any, or none.")

    # Add other general INI settings as needed
    config[section_name]['RememberPluginSelection'] = 'False'
    config[section_name]['NoUpdate'] = 'True'
    config[section_name]['NoBackup'] = 'True'
    config[section_name]['BackupPrompt'] = 'False'
    config[section_name]['SkipHeaderValidation'] = 'True'
    config[section_name]['NoCRLF'] = 'True'
    # config[section_name]['Portable'] = 'True'  # <-- COMMENT OUT THIS LINE
    config[section_name]['LimitRecords'] = 'False'
    config[section_name]['ShowSplashScreen'] = 'False'

    try:
        with open(ini_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        wrapped_organizer.log(1, f"SkyGen: Successfully wrote temporary xEdit INI to: {ini_path}")
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write xEdit INI to {ini_path}: {e}\n{traceback.format_exc()}")
        dialog_instance.showError("INI Write Error", f"SkyGen: Failed to write temporary xEdit INI file to:\n{ini_path}\n\nError: {e}")

def write_pas_script_to_xedit(script_path: Path, wrapped_organizer) -> bool: # ADD -> bool
    wrapped_organizer.log(1, f"SkyGen: ENTERING write_pas_script_to_xedit for path: {script_path}")

uses xEditAPI, Classes, SysUtils;

var
  slParams, slOutput: TStringList;
  targetPluginName, targetCategory, outputPath, outputDir: string;

function Initialize: integer;
var
  i: integer;
  plugin, rec: IInterface;
  formID, edid, name, source: string;
begin
  AddMessage('SkyGen Export Script Initializing...');
  slParams := TStringList.Create;
  for i := 0 to ParamCount do
    slParams.Add(ParamStr(i));

  // Parse CLI parameters
  for i := 0 to slParams.Count - 1 do begin
    if Pos('-D:TargetPlugin="', slParams[i]) = 1 then
      targetPluginName := Copy(slParams[i], 19, Length(slParams[i]) - 19);
    if Pos('-D:TargetCategory="', slParams[i]) = 1 then
      targetCategory := Copy(slParams[i], 21, Length(slParams[i]) - 21);
    if Pos('-o:"', slParams[i]) = 1 then begin
      outputPath := Copy(slParams[i], 5, Length(slParams[i]) - 5);
      // NEW FIX: Explicitly strip trailing quote from outputPath
      if RightStr(outputPath, 1) = '"' then
        Delete(outputPath, Length(outputPath), 1);
    end;
  end;

  if (targetPluginName = '') or (targetCategory = '') or (outputPath = '') then begin
    AddMessage('ERROR: Missing parameters. Required: -D:TargetPlugin, -D:TargetCategory, and -o.');
    AddMessage('DEBUG: targetPluginName: "' + targetPluginName + '"');
    AddMessage('DEBUG: targetCategory: "' + targetCategory + '"');
    AddMessage('DEBUG: outputPath (parsed): "' + outputPath + '"');
    Result := 1;
    Exit;
  end;

  outputDir := ExtractFilePath(outputPath);
  AddMessage('DEBUG: outputDir (extracted): "' + outputDir + '"');

  if not DirectoryExists(outputDir) then begin
    AddMessage('DEBUG: Directory does not exist, attempting to create: "' + outputDir + '"');
    ForceDirectories(outputDir);
    if not DirectoryExists(outputDir) then begin
        AddMessage('ERROR: Failed to create directory: "' + outputDir + '"');
        Result := 1;
        Exit;
    end;
  end;

  plugin := FileByName(targetPluginName);
  if not Assigned(plugin) then begin
    AddMessage('ERROR: Plugin not found: ' + targetPluginName);
    Result := 1;
    Exit;
  end;

  slOutput := TStringList.Create;
  slOutput.Add('{');
  slOutput.Add('"sourceModBaseObjects": [');

  for i := 0 to RecordCount(plugin) - 1 do begin
    rec := RecordByIndex(plugin, i);
    if Signature(rec) <> targetCategory then Continue;

    formID := IntToHex(FixedFormID(rec), 8);
    edid := GetElementEditValues(rec, 'EDID');
    name := GetElementEditValues(rec, 'FULL');
    source := GetFileName(GetFile(rec));

    slOutput.Add('  {');
    slOutput.Add('    "formID": "0x' + formID + '",');
    slOutput.Add('    "edid": "' + StringReplace(edid, '"', '', [rfReplaceAll]) + '",');
    slOutput.Add('    "name": "' + StringReplace(name, '"', '', [rfReplaceAll]) + '",');
    slOutput.Add('    "source": "' + source + '"');
    if i < RecordCount(plugin) - 1 then
      slOutput.Add('  },')
    else
      slOutput.Add('  }');
  end;

  slOutput.Add(']');
  slOutput.Add('}');

  try
    AddMessage('Attempting to write JSON to: ' + outputPath);
    slOutput.SaveToFile(outputPath);
  except
    on e: Exception do begin
      AddMessage('ERROR: Could not save export file: ' + e.Message);
      Result := 1;
      Exit;
    end;
  end;

  AddMessage('✅ Export completed successfully.');
  Result := 0;
end;

function Finalize: integer;
begin
  if Assigned(slParams) then slParams.Free;
  if Assigned(slOutput) then slOutput.Free;
  AddMessage('SkyGen Export Script Finalized.');
end;

end.
"""
    try:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        wrapped_organizer.log(1, f"SkyGen: Directory ensured for Pascal script: {script_path.parent}")
        with script_path.open("w", encoding="utf-8") as f:
            f.write(pas_content.strip())
        wrapped_organizer.log(1, f"SkyGen: Successfully wrote Pascal script to: {script_path}")
        return True # ADD THIS LINE
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write ExportPluginData.pas: {e}\n{traceback.format_exc()}") # Added traceback
        return False # ADD THIS LINE


def clean_temp_script_and_ini(xedit_exe_path: Path, script_path: Path, wrapped_organizer):
    ini_path = xedit_exe_path.with_suffix(".ini")
    try:
        if ini_path.exists():
            ini_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted temporary INI: {ini_path}")
    except Exception as e:
        wrapped_organizer.log(2, f"SkyGen: Failed to delete INI: {e}")
    try:
        if script_path.exists():
            script_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted temporary .pas script: {script_path}")
    except Exception as e:
        wrapped_organizer.log(2, f"SkyGen: Failed to delete .pas: {e}")


def generate_and_write_skypatcher_yaml(organizer: mobase.IOrganizer, category: str,
                                       target_plugin: str, source_plugin: str,
                                       source_mod_name: str, source_mod_base_objects: list,
                                       all_exported_data: dict, broad_category_swap: bool,
                                       keywords: str, dialog, output_folder: Path) -> bool:
    """
    Generates a SkyPatcher-compatible YAML file based on the provided data then writes
    it to the specified output folder. Returns True upon success or False on failure.
    """
    try:
        # Convert keywords from comma-separated string to list
        keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
        
        # Prepare the YAML structure. Adjust structure per SkyPatcher's expected schema.
        yaml_data = {
            'category': category,
            'targetPlugin': target_plugin,
            'sourcePlugin': source_plugin,
            'sourceModName': source_mod_name,
            'broadSwap': broad_category_swap,
            'keywords': keyword_list,
            'baseObjects': source_mod_base_objects
        }
        
        # Create a unique file name using a timestamp and sanitized mod name.
        timestamp = int(time.time())
        sanitized_name = sanitize_path_for_pascal(source_mod_name)
        yaml_file = output_folder / f"SkyPatcher_{sanitized_name}_{timestamp}.yaml"
        
        with open(yaml_file, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True)
        
        organizer.log(1, f"Successfully generated YAML file: {yaml_file}")
        return True
    except Exception as e:
        organizer.log(3, f"Error generating YAML for {source_mod_name}: {e}\n{traceback.format_exc()}")
        dialog.showError("YAML Generation Error", f"An error occurred while generating YAML for {source_mod_name}:\n{e}")
        return False


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
            # 1. Typo or logic flaw: RotZ key handling - Use .get() with fallback
            rot_x = record.get("rotX")
            rot_y = record.get("rotY")
            rot_z = record.get("RotZ") or record.get("rotZ") # Prioritize "RotZ", fallback to "rotZ"

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
            # 2. INI Entry Key Validation Could Strip More Symbols - Use sanitize_path_for_pascal()
            sanitized_source_name = sanitize_path_for_pascal(Path(source_name).stem) # Use the full sanitization
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
            # 2. INI Entry Key Validation Could Strip More Symbols - Use sanitize_path_for_pascal()
            sanitized_source_name = sanitize_path_for_pascal(Path(source_name).stem) # Use the full sanitization
            ini_filename = f"Pos_{sanitized_source_name}_SWAP.ini" # Updated suffix
            ini_file_path = bos_output_dir / ini_filename
            try:
                with ini_file_path.open('w', encoding='utf-8') as f: # Changed to Path.open() for consistency
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


def run_xedit_export(
    wrapped_organizer: mobase.IOrganizer,  # Ensure correct type
    dialog,  # The dialog object (SkyGenToolDialog instance)
    xedit_exe_path: Path,
    xedit_mo2_name: str,  # NEW: MO2 executable display name (e.g. "SSEEdit")
    xedit_script_path: Path,
    output_base_dir: Path,  # This is the directory where we expect xEdit to write its default output (MO2's overwrite)
    target_plugin_filename: str,
    game_version: str,
    target_mod_display_name: str,
    target_category: str
) -> Path | None: # CHANGED: Now returns Path of output file or None
    try:
        if not xedit_exe_path.is_file():
            dialog.showError("xEdit Not Found", f"The xEdit executable was not found at:\n{xedit_exe_path}")
            return None # Changed from False to None

        # --- Create temporary xEdit INI file for automation ---
        write_xedit_ini_for_skygen(xedit_exe_path, wrapped_organizer, dialog) # Pass wrapped_organizer and dialog
        
        # Ensure standard xEdit subdirectories exist to prevent early initialization errors
        xedit_base_dir = xedit_exe_path.parent
        xedit_subdirs_to_create = [
            xedit_base_dir / "Cache",
            xedit_base_dir / "Data",
            xedit_base_dir / "Logs",
            xedit_base_dir / "Backups",
            xedit_base_dir / "Temp"
        ]
        for subdir in xedit_subdirs_to_create:
            try:
                subdir.mkdir(parents=True, exist_ok=True)
                wrapped_organizer.log(1, f"SkyGen: Ensured xEdit subdirectory exists: {subdir}")
            except Exception as e:
                wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to create xEdit subdirectory {subdir}: {e}\n{traceback.format_exc()}")
                dialog.showError("Directory Creation Error", f"SkyGen: Failed to create a critical xEdit subdirectory:\n{subdir}\n\nError: {e}\n\nThis usually indicates a permissions issue. Please try running Mod Organizer 2 as administrator.")
                return None # Crucial: Stop execution if a critical directory cannot be created

        # Build output paths for xEdit's script and main log
        safe_plugin_name = sanitize_path_for_pascal(target_plugin_filename).replace('.', '')
        timestamp = str(int(time.time()))
        # Define the actual output JSON path for the Pascal script
        output_path = output_base_dir / f"SkyGen_xEditExport{safe_plugin_name}{timestamp}.json"
        expected_output_path = output_path  # Define it here for consistency with polling message
                
        # Define xEdit's main log path
        log_path = output_base_dir / f"SkyGen_xEdit_Log_{safe_plugin_name}_{timestamp}.log"
                
        # Pascal script's debug log path
        pascal_debug_log_path = output_base_dir / f"ExportPluginData_Debug_{safe_plugin_name}_{timestamp}.log"
                
        # Backup directory (ensured to exist, but -b argument is not passed to xEdit)
        backup_dir = output_base_dir / "Backup"
        

        # Ensure directories for logs and potentially internal backups exist
        try:
            output_base_dir.mkdir(parents=True, exist_ok=True)
            backup_dir.mkdir(parents=True, exist_ok=True) 
            wrapped_organizer.log(1, f"SkyGen: Ensured output directory exists: {output_base_dir}")
            wrapped_organizer.log(1, f"SkyGen: Ensured backup directory exists: {backup_dir}")
        except Exception as e:
            dialog.showError("Directory Creation Error", f"Could not ensure output/backup directories exist:\n{output_base_dir}\n\n{e}")
            return None # Changed from False to None

        # Command arguments
        xedit_args = []

        game_mode_arg = {"SkyrimSE": "-sse", "SkyrimVR": "-tes5vr"}.get(game_version)
        if game_mode_arg:
            xedit_args.append(game_mode_arg)
        else:
            wrapped_organizer.log(2, f"No game mode flag for {game_version} -- launching without explicit game mode.")

        xedit_args.append(f'-script:"{os.path.normpath(str(xedit_script_path))}"')
        xedit_args.append(f'-o:"{output_path}"') # Pass the output path for the Pascal script
        xedit_args.append(f'-debuglog:"{pascal_debug_log_path}"') # Kept this for script-specific debug logs
        xedit_args.append(f'-L:"{log_path}"') # Explicitly set xEdit's main log path

        xedit_args.append(f'-plugin:"{target_plugin_filename}"')
        xedit_args.append(f'-D:TargetPlugin="{target_mod_display_name}"')
        xedit_args.append(f'-D:TargetCategory="{target_category}"')

        xedit_args.extend([
            '-IKnowWhatImDoing',
            '-NoAutoUpdate',
            '-NoAutoBackup',
            '-autoload',
            '-nomenus',
            '-exit'
        ])

        # Determine the CWD for xEdit
        # Since SSEEdit.ini sets Portable=True, xEdit expects its CWD to be its own directory.
        cwd = str(xedit_exe_path.parent) # Force CWD to xEdit's own directory
        wrapped_organizer.log(1, f"SkyGen: Setting xEdit Working Directory (CWD) to xEdit executable directory: {cwd}")

        wrapped_organizer.log(1, f"SkyGen: Calling xEdit with args: {xedit_args} and CWD: {cwd}")

        # Use the MO2 display name for the executable to ensure MO2 launches it correctly
        exe_to_launch = xedit_mo2_name # Using the MO2 configured name

        # This was the line we added for debugging, you can keep it or remove it after this test
        wrapped_organizer.log(1, f"SkyGen: Attempting to launch xEdit with MO2 registered name: '{exe_to_launch}'")
        
        result_handle = wrapped_organizer.startApplication(
            executableName=exe_to_launch,
            arguments=xedit_args,
            workingDirectory=cwd # Pass the explicitly set CWD
        )

        if result_handle == 0:
            dialog.showError("Execution Error", f"xEdit failed to launch. Return code: {result_handle}. Check MO2 logs.")
            return None # Changed from False to None

        wrapped_organizer.log(1, f"xEdit launched with handle: {result_handle}. Polling for output file: {expected_output_path}")

        success_flag = False
        for i in range(MAX_POLL_TIME):
            if expected_output_path.exists() and expected_output_path.stat().st_size > 0:
                wrapped_organizer.log(1, f"Export successful to {expected_output_path}")
                time.sleep(1) # Give xEdit a moment to finish writing
                success_flag = True
                break
            time.sleep(1)

        if not success_flag:
            dialog.showError("Timeout", f"xEdit did not produce the expected output at {expected_output_path} in time ({MAX_POLL_TIME}s). Check xEdit's generated logs.")
        
        # --- Clean up temporary xEdit INI file ---
        try:
            xedit_ini_path = xedit_exe_path.with_suffix('.ini')
            if xedit_ini_path.exists():
                xedit_ini_path.unlink()
                wrapped_organizer.log(1, f"SkyGen: Deleted temporary INI: {xedit_ini_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit INI '{xedit_ini_path}': {e}")
        # --- End cleanup ---

        return expected_output_path if success_flag else None # Return the path if successful

    except Exception as e:
        dialog.showError("Unexpected Error", f"An unexpected error occurred during xEdit export:\n{e}\n{traceback.format_exc()}")
        wrapped_organizer.log(3, f"Exception in run_xedit_export: {e}\n{traceback.format_exc()}")
        
        # Ensure INI cleanup even if other exceptions occur
        try:
            xedit_ini_path = xedit_exe_path.with_suffix('.ini')
            if xedit_ini_path.exists():
                xedit_ini_path.unlink()
                wrapped_organizer.log(1, f"SkyGen: Deleted temporary xEdit INI (due to export error): {xedit_ini_path}")
        except Exception as cleanup_e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit INI '{xedit_ini_path}' after export error: {cleanup_e}")

        return None # Changed from False to None

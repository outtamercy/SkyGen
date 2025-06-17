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
from typing import Optional, Any


# Define a constant for max poll time
MAX_POLL_TIME = 60 # Maximum seconds to wait for xEdit export to complete (increased from 30)


# --- Utility Functions (Global helpers) ---

def detect_root_mode(wrapped_organizer: Any, dialog_instance: Any) -> bool:
    """Detect if Root Builder is in Root Mode and warn the user.
    Uses wrapped_organizer for MO2 paths and dialog_instance for warnings.
    """
    try:
        # CRITICAL FIX: Use wrapped_organizer.gameInfo().path() for the actual game directory
        # This is the most reliable way to get the game's base installation path in MO2 2.5.2
        game_dir = Path(wrapped_organizer.gameInfo().path())
        data_dir = game_dir / "Data"

        if not data_dir.exists():
            wrapped_organizer.log(2, f"SkyGen: WARNING: Could not find Data folder to check for Root Builder at: {data_dir}")
            return False

        # Check for Root Builder marker file (.rootbuilder)
        marker_file = data_dir / ".rootbuilder"
        if marker_file.exists():
            dialog_instance.showWarning("Root Builder Detected",
                                "SkyGen detected that Root Builder is in Root Mode.\n\n"
                                "This may interfere with xEdit and cause incorrect patch results.\n"
                                "Please disable Root Mode in Root Builder before using SkyGen.")
            wrapped_organizer.log(2, f"SkyGen: WARNING: Found Root Builder marker at: {marker_file}")
            return True

        # Fallback: check for symlinks in Data folder (another sign of Root Mode)
        suspicious_symlinks = any(
            (data_dir / f).is_symlink()
            for f in os.listdir(data_dir)
            if f.lower().endswith(('.esp', '.esm', '.bsa'))
        )
        if suspicious_symlinks:
            dialog_instance.showWarning("Root Builder Symlinks Detected",
                                "SkyGen found symlinks in your Skyrim/Data folder — Root Mode may be active.\n"
                                "For best results, please use VFS Mode in Root Builder.")
            wrapped_organizer.log(2, "SkyGen: WARNING: Detected symlinks in Data — likely Root Mode.")
            return True

    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed Root Mode detection: {e}\n{traceback.format_exc()}")
    return False


def load_json_data(wrapped_organizer: Any, file_path: Path, description: str, dialog_instance: Any) -> dict | None:
    """
    Loads JSON data from a specified file path.
    Requires wrapped_organizer for logging and dialog_instance for showing UI errors.
    """
    if not file_path or not file_path.is_file():
        wrapped_organizer.log(2, f"SkyGen: WARNING: {description} file path is invalid or file not found at: {file_path}.")
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Not Found", f"{description} file not found at the specified path: {file_path}.")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            wrapped_organizer.log(1, f"SkyGen: Successfully loaded {description} from: {file_path}")
            return data
    except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Error loading {description} from {file_path}: {e}")
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Read Error", f"Error loading {description} from {file_path}:\n{e}")
        return None


def get_xedit_path_from_ini(wrapped_organizer: Any) -> tuple[Optional[Path], Optional[str]]:
    """
    Parses ModOrganizer.ini to find the path and display name of the registered xEdit executable.
    Does NOT require a dialog instance for UI messages; only logs.
    """
    mo2_ini_path = Path(wrapped_organizer.basePath()) / "ModOrganizer.ini"
    if not mo2_ini_path.is_file():
        wrapped_organizer.log(3, f"SkyGen: CRITICAL: ModOrganizer.ini not found at expected path: {mo2_ini_path}")
        return None, None

    config = configparser.ConfigParser()
    try:
        config.read(mo2_ini_path, encoding='utf-8')
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: CRITICAL: Failed to parse ModOrganizer.ini: {e}")
        return None, None

    if 'CustomExecutables' not in config:
        wrapped_organizer.log(2, "SkyGen: WARNING: [CustomExecutables] section not found in ModOrganizer.ini.")
        return None, None

    xedit_exe_path = None
    xedit_mo2_name = None

    for key, value in config.items('CustomExecutables'):
        if key.endswith('binary'):
            exe_path = Path(value.strip().strip('"'))
            if "xedit" in exe_path.name.lower() or "sseedit" in exe_path.name.lower():
                xedit_exe_path = exe_path
                # Find the corresponding display name
                try:
                    name_key = key.replace('binary', 'name')
                    xedit_mo2_name = config.get('CustomExecutables', name_key).strip().strip('"')
                    wrapped_organizer.log(1, f"SkyGen: Successfully parsed ModOrganizer.ini for xEdit. Path: {xedit_exe_path}, Name: {xedit_mo2_name}")
                    return xedit_exe_path, xedit_mo2_name
                except configparser.NoOptionError:
                    wrapped_organizer.log(2, f"SkyGen: WARNING: Could not find display name for xEdit binary: {exe_path}. Skipping.")
    
    wrapped_organizer.log(2, "SkyGen: WARNING: No xEdit executable found in ModOrganizer.ini [CustomExecutables].")
    return None, None


def get_xedit_exe_path(config_data: dict, wrapped_organizer: Any, dialog_instance: Any) -> tuple[Optional[Path], Optional[str]]:
    """
    Determines the xEdit executable path and its MO2 registered name.
    Prioritizes config.json, then ModOrganizer.ini parsing.
    """
    xedit_exe_path: Optional[Path] = None
    xedit_mo2_name: Optional[str] = None
    
    # --- Attempt 1: Try to get from config.json first (for subsequent runs) ---
    xedit_exe_path_str_config = config_data.get("xedit_exe_path")
    xedit_mo2_name_config = config_data.get("xedit_mo2_name")
    
    if xedit_exe_path_str_config and xedit_mo2_name_config:
        configured_path = Path(xedit_exe_path_str_config)
        if configured_path.is_file():
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Using xEdit path from config.json: {configured_path} (MO2 name: {xedit_mo2_name_config})")
            return configured_path, xedit_mo2_name_config
        else:
            wrapped_organizer.log(2, f"SkyGen: WARNING: Configured xEdit path '{configured_path}' in config.json not found. Attempting auto-detection via INI.")

    # --- Attempt 2: Auto-detect by parsing ModOrganizer.ini (reliable for first run/missing getExecutables) ---
    xedit_exe_path_ini, xedit_mo2_name_ini = get_xedit_path_from_ini(wrapped_organizer)
    if xedit_exe_path_ini and xedit_mo2_name_ini:
        wrapped_organizer.log(0, f"SkyGen: DEBUG: Auto-detected xEdit from ModOrganizer.ini: {xedit_exe_path_ini} (MO2 name: {xedit_mo2_name_ini})")
        return xedit_exe_path_ini, xedit_mo2_name_ini
    else:
        wrapped_organizer.log(3, "SkyGen: CRITICAL: xEdit executable not found via config.json or ModOrganizer.ini parsing. Please configure it manually in config.json.")
        # CONFIRMED: The problematic getExecutables() call is NOT here.
        return None, None


def get_game_root_from_general_ini(wrapped_organizer: Any, config_data: dict, dialog_instance: Any) -> Optional[Path]:
    """
    Attempts to determine the game root path.
    Prioritizes ModOrganizer.ini, then falls back to config_data.
    """
    game_root_path = None
    
    # --- Attempt 1: Read from ModOrganizer.ini ---
    mo2_ini_path = Path(wrapped_organizer.basePath()) / "ModOrganizer.ini"
    if mo2_ini_path.is_file():
        config = configparser.ConfigParser()
        try:
            config.read(mo2_ini_path, encoding='utf-8')
            if 'General' in config:
                game_path_str_ini = config.get("General", "gamePath", fallback="")
                
                # Strip @ByteArray(...) prefix if present
                if game_path_str_ini.startswith("@ByteArray("):
                    game_path_str_ini = game_path_str_ini[len("@ByteArray("):-1]
                    
                if game_path_str_ini:
                    potential_path = Path(game_path_str_ini)
                    if potential_path.is_dir():
                        game_root_path = potential_path
                        wrapped_organizer.log(0, f"SkyGen: DEBUG: Successfully read game root from ModOrganizer.ini: {game_root_path}")
                        return game_root_path # Return early if successful
                    else:
                        wrapped_organizer.log(2, f"SkyGen: WARNING: gamePath in ModOrganizer.ini ('{potential_path}') is not a valid directory. Attempting fallback.")
                        if dialog_instance: # Check if dialog is available before showing
                            dialog_instance.showWarning("Game Path Invalid", f"Game path in ModOrganizer.ini ('{potential_path}') is not a valid directory. Attempting fallback to config.json.")
                else:
                    wrapped_organizer.log(2, f"SkyGen: WARNING: 'gamePath' not found or empty in [General] section of ModOrganizer.ini. Attempting fallback.")
                    if dialog_instance: # Check if dialog is available before showing
                        dialog_instance.showWarning("Game Path Missing", "'gamePath' not found or empty in [General] section of ModOrganizer.ini. Attempting fallback to config.json.")
            else:
                wrapped_organizer.log(2, "SkyGen: WARNING: [General] section not found in ModOrganizer.ini. Attempting fallback.")
                if dialog_instance: # Check if dialog is available before showing
                    dialog_instance.showWarning("MO2 INI Section Missing", "[General] section not found in ModOrganizer.ini. Attempting fallback to config.json.")
        except Exception as e:
            wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to parse ModOrganizer.ini for game root: {e}. Attempting fallback.\n{traceback.format_exc()}")
            if dialog_instance: # Check if dialog is available before showing
                dialog_instance.showError("MO2 INI Parse Error", f"Failed to parse ModOrganizer.ini for game root: {e}. Attempting fallback to config.json.")
    else:
        wrapped_organizer.log(2, f"SkyGen: WARNING: ModOrganizer.ini not found at {mo2_ini_path}. Attempting fallback.")
        if dialog_instance: # Check if dialog is available before showing
            dialog_instance.showWarning("MO2 INI Not Found", f"ModOrganizer.ini not found at {mo2_ini_path}. Attempting fallback to config.json.")

    # --- Attempt 2: Fallback to config_data (from config.json) ---
    if config_data and "game_root_path" in config_data:
        game_path_str_config = config_data.get("game_root_path")
        if game_path_str_config:
            potential_path = Path(game_path_str_config)
            if potential_path.is_dir():
                game_root_path = potential_path
                wrapped_organizer.log(0, f"SkyGen: DEBUG: Successfully read game root from config.json: {game_root_path}")
                return game_root_path # Return if successful
            else:
                wrapped_organizer.log(3, f"SkyGen: ERROR: game_root_path in config.json ('{potential_path}') is not a valid directory.")
                if dialog_instance: # Check if dialog is available before showing
                    dialog_instance.showError("Configured Game Path Invalid", f"Game root path in config.json ('{potential_path}') is not a valid directory.")
        else:
            wrapped_organizer.log(3, "SkyGen: ERROR: 'game_root_path' not found or empty in config.json.")
            if dialog_instance: # Check if dialog is available before showing
                dialog_instance.showError("Configured Game Path Missing", "'game_root_path' not found or empty in config.json.")
    else:
        wrapped_organizer.log(3, "SkyGen: ERROR: config.json data not available or 'game_root_path' missing for fallback.")
        if dialog_instance: # Check if dialog is available before showing
            dialog_instance.showError("Config Data Missing", "Config.json data not available or 'game_root_path' missing for fallback.")

    # If all attempts fail
    wrapped_organizer.log(3, "SkyGen: CRITICAL: Could not determine game root path from ModOrganizer.ini or config.json. Please configure 'gamePath' in MO2 settings or 'game_root_path' in plugin's config.json.")
    if dialog_instance: # Check if dialog is available before showing
        dialog_instance.showError("Game Root Not Found", "Could not determine game root path. Please configure 'gamePath' in MO2 settings or 'game_root_path' in plugin's config.json.")
    return None


def write_xedit_ini_for_skygen(xedit_exe_path: Path, script_args: str, game_version: str, wrapped_organizer: Any):
    """
    Writes a temporary INI file for xEdit to ensure it runs the specified script
    with the correct game mode and passes script options.
    The INI file is named after the xEdit executable.
    """
    xedit_ini_path = xedit_exe_path.with_suffix('.ini')
    config = configparser.ConfigParser()
    
    # Ensure section exists even if empty initially
    if not config.has_section("Settings"):
        config.add_section("Settings")
    
    config.set("Settings", "Game", game_version)
    config.set("Settings", "AutoRun", script_args) # Pass the script path and arguments
    
    try:
        with open(xedit_ini_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        wrapped_organizer.log(0, f"SkyGen: DEBUG: Temporary xEdit INI written to: {xedit_ini_path} with Game='{game_version}' and AutoRun='{script_args}'")
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write temporary xEdit INI to {xedit_ini_path}: {e}\n{traceback.format_exc()}")
        raise # Re-raise to halt execution if INI write fails


def write_pas_script_to_xedit(script_path: Path, wrapped_organizer: Any):
    """
    Writes the fixed Pascal script content to the specified path within xEdit's script directory.
    The content is now hardcoded in this function.
    """
    script_content = """
unit ExportPluginData;

uses
  SysUtils, Classes, Dialogs, m_Common, m_Process, m_JSON;

var
  JsonOutput: TJSONArray; // Changed to TJSONArray to hold a list of objects

function Initialize: Integer;
begin
  Result := 0; // Initialize to success
end;

function Finalize: Integer;
begin
  Result := 0;
end;
function Process(ARecord: IInterface): Integer;
var
  Element: IInterface;
  Signature: string;
  FormID: string;
  EditorID: string;
  FullName: string;
  OriginMod: string;
  ParentName: string;
  ItemJSON: TJSONObject;
  TargetPlugin: string;
  TargetCategory: string;
  Keywords: string;
  KeywordsArray: TJSONArray;
  i: Integer;
  Keyword: string;
  MatchFound: Boolean;
begin
  Result := 0; // Initialize to success

  // Get parameters from xEdit arguments (passed via INI AutoRun)
  TargetPlugin := GetScriptOption('TargetPlugin');
  TargetCategory := GetScriptOption('TargetCategory');
  Keywords := GetScriptOption('Keywords');

  // Check if a record is provided and it's a main record (not a sub-record)
  if (ARecord <> nil) and (ARecord.GetElementFile = ARecord.GetElementFile.Root) then
  begin
    Signature := SignatureToString(ARecord.GetSignature);

    // Debugging logs - only enable if absolutely necessary, they spam the xEdit log
    // AddMessage(Format('Processing record: %s, Origin: %s', [LongName(ARecord), GetElementFile(ARecord).FileName]));

    // Filter by TargetPlugin if specified
    if (TargetPlugin <> '') and (GetElementFile(ARecord).FileName <> TargetPlugin) then
      Exit(0); // Skip if not the target plugin

    // Filter by TargetCategory if specified and it matches the record's signature
    if (TargetCategory <> '') and (Signature <> TargetCategory) then
    begin
      // Special handling for broad category swap if enabled
      if GetScriptOption('BroadCategorySwap') = 'true' then
      begin
        // Allow processing for broad category swap where signature != TargetCategory
        // No explicit skip here, continue to check keywords if any.
      end
      else
        Exit(0); // Skip if category filter is active and doesn't match
    end;

    // Filter by Keywords if specified
    MatchFound := True; // Assume match if no keywords or broad swap enabled
    if (Keywords <> '') and (GetScriptOption('BroadCategorySwap') <> 'true') then
    begin
      MatchFound := False; // Reset to false, require at least one keyword match
      KeywordsArray := TJSONArray.Create;
      // Split keywords string by comma and space, trim each keyword
      for Keyword in SplitString(Keywords, [',', ' ']) do
      begin
        Keyword := Trim(Keyword);
        if Keyword <> '' then
          KeywordsArray.Add(TJSONString.Create(Keyword));
      end;

      if KeywordsArray.Count > 0 then
      begin
        // Check if any of the specified keywords are in the record's EDID
        Element := ARecord.GetElementByPath('EDID');
        if (Element <> nil) then
        begin
          EditorID := Element.GetValue;
          for i := 0 to KeywordsArray.Count - 1 do
          begin
            Keyword := (KeywordsArray.Items[i] as TJSONString).Value;
            if Pos(Keyword, EditorID) > 0 then // Case-sensitive check
            begin
              MatchFound := True;
              Break;
            end;
          end;
        end;
      end;
      KeywordsArray.Free;
    end;

    if not MatchFound then
      Exit(0); // Skip if keywords did not match and broad swap is not enabled

    // Extract data
    FormID := IntToHex(ARecord.GetFormID, 8); // Format as 8-digit hex string
    EditorID := ARecord.GetEditorID;
    FullName := ARecord.GetName;
    OriginMod := GetElementFile(ARecord).FileName;
    // Get Parent Name for certain record types (e.g., ARMA parent ARMOR)
    ParentName := '';
    if Signature = 'ARMA' then
    begin
      Element := ARecord.GetElementByPath('PARE'); // Get parent reference
      if (Element <> nil) then
        ParentName := LongName(Element.AsLink.Target);
    end;

    // Create JSON object for the current record
    ItemJSON := TJSONObject.Create;
    ItemJSON.Add('Signature', Signature);
    ItemJSON.Add('FormID', FormID);
    ItemJSON.Add('EditorID', EditorID);
    ItemJSON.Add('FullName', FullName);
    ItemJSON.Add('OriginMod', OriginMod);
    if ParentName <> '' then
      ItemJSON.Add('ParentName', ParentName);

    // Add to the main JSON array
    JsonOutput.Add(ItemJSON); // Changed to Add to TJSONArray
  end;
  Result := 0; // Success
end;

function Main: Integer;
var
  OutputFilePath: string;
  MainOutputObject: TJSONObject; // New main object to hold the array under 'baseObjects'
begin
  Result := 0; // Initialize to success

  // Get output file path from command line option
  OutputFilePath := GetScriptOption('OutputFilePath');
  if OutputFilePath = '' then
  begin
    AddMessage('ERROR: OutputFilePath not provided as script option.'); // Added log message
    Result := 1; // Indicate error
    Exit;
  end;

  JsonOutput := TJSONArray.Create; // Initialize TJSONArray

  // Process all selected records
  ProcessRecords(Self);

  // Create the main output object with "baseObjects" key
  MainOutputObject := TJSONObject.Create;
  MainOutputObject.Add('baseObjects', JsonOutput); // Add the array under the key "baseObjects"

  // Save JSON to file
  try
    MainOutputObject.SaveToFile(OutputFilePath); // Save the main object
    AddMessage(Format('Successfully exported data to: %s', [OutputFilePath]));
  except
    on E: Exception do
    begin
      AddMessage(Format('ERROR: Failed to save JSON to file %s: %s', [OutputFilePath, E.Message]));
      Result := 1; // Indicate error
    end;
  end;

  MainOutputObject.Free; // Free the main object (which also frees JsonOutput)

  Result := 0; // Success
end;

end.
    """
    try:
        # Ensure the parent directory exists
        script_path.parent.mkdir(parents=True, exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        wrapped_organizer.log(0, f"SkyGen: DEBUG: Pascal script written to: {script_path}")
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write Pascal script to {script_path}: {e}\n{traceback.format_exc()}")
        raise # Re-raise to halt execution if script write fails


def run_xedit_export(
    wrapped_organizer: Any,
    dialog: Any,
    xedit_exe_path: Path,
    xedit_mo2_name: str,
    game_root_path: Path,
    xedit_script_path: Path,
    output_base_dir: Path,
    target_plugin_filename: str,
    game_version: str,
    target_mod_display_name: str,
    target_category: Optional[str] = None,
    broad_category_swap_enabled: bool = False,
    keywords: str = ""
) -> Optional[Path]:
    """
    Runs xEdit as a subprocess to export plugin data using a generated Pascal script.
    Monitors for the creation of the output JSON file and its log.
    """
    wrapped_organizer.log(1, f"SkyGen: Initiating xEdit export for '{target_plugin_filename}' (Category: '{target_category}')...")

    # The Pascal script content is now fixed and defined within write_pas_script_to_xedit.
    # No need to call generate_export_script_content here.
    
    # We write the script content to xedit_script_path
    try:
        write_pas_script_to_xedit(xedit_script_path, wrapped_organizer)
    except Exception as e:
        dialog.showError("Script Write Error", f"Failed to write xEdit Pascal script:\n{e}")
        return None

    # Define the expected output JSON path *within* the output_base_dir
    expected_output_path = output_base_dir / "SkyGen_xEdit_Export.json"
    expected_log_path = expected_output_path.with_suffix('.log')

    # Clean up previous output if it exists
    if expected_output_path.exists():
        try:
            expected_output_path.unlink()
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up old output: {expected_output_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: WARNING: Could not delete old output file '{expected_output_path}': {e}")
    if expected_log_path.exists():
        try:
            expected_log_path.unlink()
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Cleaned up old log: {expected_log_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: WARNING: Could not delete old log file '{expected_log_path}': {e}")

    # Construct arguments for xEdit's AutoRun INI setting
    # These will be read by the Pascal script using GetScriptOption
    script_options = [
        f"TargetPlugin='{target_plugin_filename}'",
        f"OutputFilePath='{expected_output_path.as_posix().replace('\\', '/')}'",
        f"TargetCategory='{target_category if target_category else ''}'",
        f"BroadCategorySwap='{str(broad_category_swap_enabled).lower()}'",
        f"Keywords='{keywords}'" # Keywords string passed as-is
    ]
    # Combine script filename with options for AutoRun
    ini_script_args = f"'{xedit_script_path.name}' " + " ".join([f"-scriptoption:{opt}" for opt in script_options])


    # Ensure the current working directory for xEdit is the game's root directory
    # This is crucial for xEdit to find game data correctly.
    xedit_cwd = str(game_root_path)

    wrapped_organizer.log(1, f"SkyGen: Launching xEdit '{xedit_mo2_name}' for export...")
    wrapped_organizer.log(0, f"SkyGen: DEBUG: xEdit binary: {xedit_exe_path}")
    wrapped_organizer.log(0, f"SkyGen: DEBUG: xEdit args (via INI AutoRun): {ini_script_args}")
    wrapped_organizer.log(0, f"SkyGen: DEBUG: xEdit CWD: {xedit_cwd}")

    process = None
    try:
        # write a temporary INI file to control xEdit's behavior
        write_xedit_ini_for_skygen(xedit_exe_path, ini_script_args, game_version, wrapped_organizer)

        # Reverted to using MO2's startApplication for correct VFS context.
        # Arguments to startApplication are specific.
        # The first argument is the MO2 executable name.
        # The second argument is a list of arguments for that executable.
        # When using AutoRun in INI, typically no further direct args are needed for the script itself.
        # Pass an empty list for args as the AutoRun handles the script execution.
        wrapped_organizer.startApplication(xedit_mo2_name, [], xedit_cwd) # No direct args needed if AutoRun is used

        # Poll for the output file
        success_flag = False
        start_time = time.time()
        while time.time() - start_time < MAX_POLL_TIME:
            if expected_output_path.is_file() and expected_output_path.stat().st_size > 0:
                # Basic check for non-empty file
                wrapped_organizer.log(1, f"SkyGen: Detected xEdit output file: {expected_output_path}")
                # Additionally check for the log file indicating script completion
                if expected_log_path.is_file():
                    with open(expected_log_path, 'r', encoding='utf-8', errors='ignore') as f_log:
                        log_content = f_log.read()
                        if "Successfully exported data to" in log_content: # Changed check for new Pascal script output
                            wrapped_organizer.log(1, "SkyGen: xEdit script reported successful export.")
                            success_flag = True
                            break
                        elif "ERROR" in log_content: # Generic error check
                            wrapped_organizer.log(3, f"SkyGen: xEdit script reported an error. Check log: {expected_log_path}")
                            break
                else:
                    wrapped_organizer.log(0, f"SkyGen: DEBUG: Output file found, but xEdit log not yet present: {expected_log_path}")
            time.sleep(0.5) # Poll every 0.5 seconds

        if not success_flag:
            wrapped_organizer.log(3, f"SkyGen: ERROR: xEdit export did not produce expected output at {expected_output_path} in time ({MAX_POLL_TIME}s). Check xEdit's generated logs.")
        
        # --- Clean up temporary xEdit INI file ---
        # The temporary INI is no longer created, so no cleanup is needed here.
        # However, the previous cleanup block is kept for robustness in case of old files.
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
            wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit INI (after error) '{xedit_ini_path}': {cleanup_e}")

        return None


def generate_and_write_skypatcher_yaml(
    wrapped_organizer: Any,
    category: str,
    target_mod_plugin_name: str,
    source_mod_plugin_name: str,
    source_mod_display_name: str,
    source_mod_base_objects: list[dict],
    all_exported_target_bases_by_formid: dict[str, dict], # All target bases for lookup
    broad_category_swap_enabled: bool,
    search_keywords: str,
    dialog_instance: Any,
    output_folder_path: Path
) -> bool:
    """
    Generates SkyPatcher YAML content based on the exported xEdit data
    and writes it to the appropriate file.
    """
    wrapped_organizer.log(1, f"SkyGen: Generating YAML for category '{category}', source '{source_mod_display_name}' targeting '{target_mod_plugin_name}'...")

    replacements = []
    generated_count = 0

    # Parse keywords string into a list for Python-side filtering
    keywords_list = [k.strip().lower() for k in search_keywords.split(',') if k.strip()]
    
    for obj in source_mod_base_objects:
        form_id = obj.get("FormID")
        editor_id = obj.get("EditorID", "")
        full_name = obj.get("FullName", "")
        obj_category = obj.get("Signature", "") # Changed from 'category' to 'Signature' for new Pascal script
        origin_mod = obj.get("OriginMod", "") # Changed from 'originMod' to 'OriginMod' for new Pascal script

        # Python-side keyword filtering (redundant if Pascal script works, but safe)
        if keywords_list:
            match_found = False
            for keyword in keywords_list:
                if keyword in editor_id.lower() or keyword in full_name.lower():
                    match_found = True
                    break
            if not match_found:
                wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping {editor_id} (FormID: {form_id}) - no keyword match (Python side).")
                continue # Skip this object if no keywords match

        # Python-side category filtering (redundant if Pascal script works, but safe)
        # Note: The Python side category filtering should ideally match the Pascal script's filtering.
        # The new Pascal script filters by TargetCategory which is the Signature (RecordType).
        # We need to ensure the `category` passed into this function aligns with the Signature.
        # If the category is meant to be a friendly name, this might need refinement.
        # For now, assuming `category` refers to the record Signature if present, otherwise ignore.
        if category and obj_category != category:
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping {editor_id} (FormID: {form_id}) - record signature mismatch (Python side). Expected '{category}', got '{obj_category}'.")
            continue # Skip if category doesn't match


        # Find a suitable replacement base object from the target mod
        replacement_base = None
        for target_form_id, target_obj in all_exported_target_bases_by_formid.items():
            if (target_obj.get("EditorID") == editor_id and target_obj.get("Signature") == obj_category): # Use Signature for comparison
                replacement_base = target_obj
                break
        
        if replacement_base:
            replacement_form_id = replacement_base["FormID"]
            replacement_editor_id = replacement_base.get("EditorID", "")
            replacement_full_name = replacement_base.get("FullName", "")

            replacement_entry = {
                "id": f"{editor_id} -> {replacement_editor_id}",
                "lookup": {
                    "formid": form_id,
                    "targetMod": source_mod_plugin_name
                },
                "replace": {
                    "formid": replacement_form_id,
                    "targetMod": target_mod_plugin_name
                },
                "notes": f"Replaced {full_name} from {source_mod_display_name} with {replacement_full_name} from {target_mod_plugin_name} (Record Type: {obj_category})" # Changed "Category" to "Record Type"
            }
            replacements.append(replacement_entry)
            generated_count += 1
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Added replacement for {editor_id} (From: {origin_mod}, To: {target_mod_plugin_name}).")
        else:
            wrapped_organizer.log(0, f"SkyGen: DEBUG: No direct replacement found for {editor_id} (FormID: {form_id}) in {target_mod_plugin_name} for record type {obj_category}. Skipping.")

    if not replacements:
        wrapped_organizer.log(1, f"SkyGen: No replacements generated for '{source_mod_display_name}' for category '{category}'.")
        return False

    yaml_data = {
        "name": f"SkyGen Generated - {source_mod_display_name} {category}",
        "author": "SkyGen",
        "description": f"Generated replacements for {source_mod_display_name} ({category}) based on {target_mod_plugin_name}.",
        "targetGame": "SkyrimSE", # Hardcoded for now
        "replacements": replacements
    }

    output_dir = output_folder_path / "SkyPatcher" / "Configs"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitize source_mod_display_name for filename
    sanitized_source_name = re.sub(r'[^\w\-_\. ]', '_', source_mod_display_name)
    sanitized_category = re.sub(r'[^\w\-_\. ]', '_', category)
    yaml_file_name = f"SkyGen_{sanitized_source_name}_{sanitized_category}.yaml"
    output_file_path = output_dir / yaml_file_name

    try:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(yaml_data, f, allow_unicode=True, sort_keys=False, indent=2)
        wrapped_organizer.log(1, f"SkyGen: Successfully wrote YAML to: {output_file_path}")
        dialog_instance.showInformation("YAML Generated", f"Successfully generated YAML for '{source_mod_display_name}' ({category}) to:\n{output_file_path}")
        return True
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write YAML file to {output_file_path}: {e}\n{traceback.format_exc()}")
        dialog_instance.showError("File Write Error", f"Failed to write YAML file for {source_mod_display_name}:\n{e}")
        return False


def generate_bos_ini_files(wrapped_organizer: Any, igpc_data: dict, output_folder_path: Path, dialog_instance: Any) -> bool:
    """
    Generates BOS INI files based on IGPC data.
    """
    wrapped_organizer.log(1, "SkyGen: Starting BOS INI file generation...")

    if not igpc_data:
        wrapped_organizer.log(2, "SkyGen: No IGPC data provided or loaded for BOS INI generation.")
        dialog_instance.showWarning("No IGPC Data", "No IGPC data available. Cannot generate BOS INI files.")
        return False

    bos_output_dir = output_folder_path / "BOS"
    bos_output_dir.mkdir(parents=True, exist_ok=True)

    generated_count = 0
    for plugin_name, records in igpc_data.items():
        ini_content = ["[IgnoredBaseObjects]"]
        
        # Sort records by formID for consistent INI order
        sorted_records = sorted(records, key=lambda x: x.get('FormID', ''))

        for record in sorted_records:
            form_id = record.get("FormID")
            editor_id = record.get("EditorID")
            if form_id and editor_id:
                ini_content.append(f"{form_id}={editor_id}")
            else:
                wrapped_organizer.log(2, f"SkyGen: WARNING: Skipping malformed record in IGPC data for plugin {plugin_name}: {record}")
        
        ini_file_path = bos_output_dir / f"BOS_{plugin_name}.ini"
        try:
            with open(ini_file_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(ini_content))
            wrapped_organizer.log(1, f"SkyGen: Generated BOS INI for '{plugin_name}' at: {ini_file_path}")
            generated_count += 1
        except Exception as e:
            dialog_instance.showError("BOS INI Write Error", f"Failed to write BOS INI for {plugin_name}:\n{e}")
            wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write BOS INI for {plugin_name}: {e}")

    if generated_count > 0:
        wrapped_organizer.log(1, "SkyGen: Successfully generated {generated_count} BOS INI file(s).")
        return True
    else:
        wrapped_organizer.log(1, "SkyGen: No BOS INI files were generated.")
        return False


def clean_temp_script_and_ini(xedit_exe_path: Path, script_path: Path, wrapped_organizer: Any):
    """
    Cleans up the temporary Pascal script and the xEdit-generated INI file.
    """
    # Clean up the Pascal script
    if script_path.exists():
        try:
            script_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted temporary xEdit script: {script_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit script '{script_path}': {e}")
    
    # Clean up the xEdit-generated INI file (often named after the xEdit executable)
    xedit_ini_path = xedit_exe_path.with_suffix('.ini')
    if xedit_ini_path.exists():
        try:
            xedit_ini_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted temporary xEdit INI: {xedit_ini_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete temporary xEdit INI '{xedit_ini_path}': {e}")

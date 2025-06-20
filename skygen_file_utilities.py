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
import shutil # Added shutil for file operations
from collections import defaultdict
from typing import Optional, Any


# Define a constant for max poll time
MAX_POLL_TIME = 60 # Maximum seconds to wait for xEdit export to complete (increased from 30)


# --- Utility Functions (Global helpers) ---

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
    except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e: # Added UnicodeDecodeError
        wrapped_organizer.log(3, f"SkyGen: ERROR: Error loading {description} from {file_path}: {e}")
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Read Error", f"Error loading {description} from {file_path}:\n{e}")
        return None


# NEW FUNCTION: get_xedit_path_from_ini
# MODIFIED: Changed signature to accept wrapped_organizer
def get_xedit_path_from_ini(wrapped_organizer: Any, game_version: str, dialog_instance: Any) -> tuple[Path | None, str | None]:
    """
    Reads ModOrganizer.ini to find the xEdit executable path and its MO2 display name.
    Bypasses MO2's internal executable lookup API and manually parses the INI.
    Returns a tuple: (xedit_absolute_path, mo2_executable_name) or (None, None) on failure.
    """
    # MODIFIED: Use wrapped_organizer.basePath()
    mo2_base_path = Path(wrapped_organizer.basePath())
    ini_file_path = mo2_base_path / "ModOrganizer.ini"

    if not ini_file_path.is_file():
        wrapped_organizer.log(3, f"SkyGen: ERROR: ModOrganizer.ini not found at: {ini_file_path}.")
        dialog_instance.showError("Error", f"ModOrganizer.ini not found at the expected path: {ini_file_path}.")
        return None, None

    xedit_exec_name_map = {
        "SkyrimSE": ["SSEEdit", "SSEEdit64"], # Common MO2 display names for SSEEdit
        "SkyrimVR": ["TES5VREdit", "TES5VREdit64"], # Common MO2 display names for TES5VREdit
    }
    expected_xedit_titles = xedit_exec_name_map.get(game_version, [])
    if not expected_xedit_titles:
        wrapped_organizer.log(3, f"SkyGen: ERROR: No expected xEdit executable titles defined for game version '{game_version}'.")
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
                        wrapped_organizer.log(2, f"SkyGen: WARNING: Error parsing INI line '{line}': {e}")
                        continue # Continue to next line even if one line fails to parse

            wrapped_organizer.log(1, f"SkyGen: Successfully parsed ModOrganizer.ini for custom executables.")

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
                            wrapped_organizer.log(1, f"SkyGen: Found xEdit executable '{title}' at: {absolute_xedit_path}")
                            return absolute_xedit_path, title # Return path and the MO2 display name
                        else:
                            wrapped_organizer.log(2, f"SkyGen: WARNING: Found xEdit entry in INI ('{title}' -> '{binary_path_str}'), but binary not found at resolved path: {absolute_xedit_path}")
                    else:
                        wrapped_organizer.log(0, f"SkyGen: DEBUG: Skipping non-xEdit executable in INI: '{title}'")
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Error reading or parsing ModOrganizer.ini from {ini_file_path}: {e}\n{traceback.format_exc()}")
        dialog_instance.showError("INI Read Error", f"Error reading or parsing ModOrganizer.ini from {ini_file_path}: {e}")
        return None, None
    wrapped_organizer.log(3, "SkyGen: CRITICAL: No xEdit executable matching expected titles found in ModOrganizer.ini [customExecutables].")
    dialog_instance.showError("xEdit Not Found", "No xEdit executable matching the expected titles found in ModOrganizer.ini. Please ensure it's configured in MO2 and its display name matches (e.g., SSEEdit for SkyrimSE).")
    return None, None


# MODIFIED FUNCTION: get_xedit_exe_path
def get_xedit_exe_path(config_data: dict, wrapped_organizer: Any, dialog_instance: Any, game_version: str) -> tuple[Optional[Path], Optional[str]]:
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
    # MODIFIED: Changed to pass wrapped_organizer directly
    xedit_exe_path_ini, xedit_mo2_name_ini = get_xedit_path_from_ini(wrapped_organizer, game_version, dialog_instance)
    if xedit_exe_path_ini and xedit_mo2_name_ini:
        wrapped_organizer.log(0, f"SkyGen: DEBUG: Auto-detected xEdit from ModOrganizer.ini: {xedit_exe_path_ini} (MO2 name: {xedit_mo2_name_ini})")
        return xedit_exe_path_ini, xedit_mo2_name_ini
    else:
        wrapped_organizer.log(3, "SkyGen: CRITICAL: No xEdit executable found via config.json or ModOrganizer.ini parsing. Please configure it manually in config.json.")
        return None, None


# REPLACED FUNCTION: get_game_root_from_general_ini
def get_game_root_from_general_ini(wrapped_organizer: Any, config_data: dict) -> Optional[Path]:
    """
    Attempts to determine the game root path by parsing ModOrganizer.ini,
    then falls back to organizer.gameDirectory(), then config_data.
    """
    game_root_path = None
    # --- Attempt 1: Read from ModOrganizer.ini (most reliable based on user feedback) ---
    # MODIFIED: Using _organizer.basePath()
    mo2_ini_path = Path(wrapped_organizer._organizer.basePath()).resolve() / "ModOrganizer.ini"
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
                    potential_path = Path(game_path_str_ini).resolve() # Added .resolve()
                    if potential_path.is_dir():
                        wrapped_organizer.log(0, f"SkyGen: DEBUG: Successfully read game root from ModOrganizer.ini: {potential_path}")
                        return potential_path # Return early if successful
                    else:
                        wrapped_organizer.log(2, f"SkyGen: WARNING: gamePath in ModOrganizer.ini ('{potential_path}') is not a valid directory. Attempting fallback.")
                else:
                    wrapped_organizer.log(2, f"SkyGen: WARNING: 'gamePath' not found or empty in [General] section of ModOrganizer.ini. Attempting fallback.")
            else:
                wrapped_organizer.log(2, "SkyGen: WARNING: [General] section not found in ModOrganizer.ini. Attempting fallback.")
        except Exception as e:
            wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to parse ModOrganizer.ini for game root: {e}. Attempting fallback.\n{traceback.format_exc()}")
    else:
        wrapped_organizer.log(2, f"SkyGen: WARNING: ModOrganizer.ini not found at {mo2_ini_path}. Attempting fallback.")

    # --- Attempt 2: Get directly from MO2's organizer.gameDirectory() ---
    try:
        # MODIFIED: Using _organizer.gameDirectory() and .resolve()
        game_root_path_from_organizer = Path(wrapped_organizer._organizer.gameDirectory()).resolve()
        if game_root_path_from_organizer.is_dir():
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Successfully read game root from organizer.gameDirectory(): {game_root_path_from_organizer}")
            return game_root_path_from_organizer
        else:
            wrapped_organizer.log(2, f"SkyGen: WARNING: organizer.gameDirectory() returned '{game_root_path_from_organizer}', which is not a valid directory. Attempting fallback to config.json.")
    except AttributeError:
        wrapped_organizer.log(2, "SkyGen: WARNING: 'mobase.IOrganizer' object has no attribute 'gameDirectory'. Attempting fallback to config.json.")
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Error getting game root from organizer.gameDirectory(): {e}. Attempting fallback.\n{traceback.format_exc()}")

    # --- Attempt 3: Fallback to config_data (from config.json) ---
    if config_data and "game_root_path" in config_data:
        game_path_str_config = config_data.get("game_root_path")
        if game_path_str_config:
            potential_path = Path(game_path_str_config).resolve() # Added .resolve()
            if potential_path.is_dir():
                wrapped_organizer.log(0, f"SkyGen: DEBUG: Successfully read game root from config.json: {potential_path}")
                return potential_path
            else:
                wrapped_organizer.log(3, f"SkyGen: ERROR: game_root_path in config.json ('{potential_path}') is not a valid directory.")
        else:
            wrapped_organizer.log(3, "SkyGen: ERROR: 'game_root_path' not found or empty in config.json.")
    else:
        wrapped_organizer.log(3, "SkyGen: ERROR: config.json data not available or 'game_root_path' missing for fallback.")

    # If all attempts fail
    wrapped_organizer.log(3, "SkyGen: CRITICAL: Could not determine game root path from ModOrganizer.ini, organizer.gameDirectory(), or config.json. Please configure 'gamePath' in MO2 settings or 'game_root_path' in plugin's config.json.")
    return None
    

# ADDED AND MODIFIED FUNCTION: detect_root_mode
def detect_root_mode(wrapped_organizer: Any) -> bool:
    """
    Detects if MO2 is operating in a 'root' mode (e.g., Root Builder active or game installed to MO2 folder).
    This affects how certain file paths are handled by xEdit.
    Returns True if a root mode is detected, False otherwise.
    """
    wrapped_organizer.log(1, "SkyGen: Detecting MO2 root mode...")
    
    # 1. Check if game is installed directly into MO2's base path (portable setup)
    # MODIFIED: Changed to use wrapped_organizer._organizer and .resolve()
    mo2_base_path = Path(wrapped_organizer._organizer.basePath()).resolve()
    game_dir = Path(wrapped_organizer._organizer.gameDirectory()).resolve() # MODIFIED: Added .resolve()

    if game_dir == mo2_base_path: # Compare resolved paths
        wrapped_organizer.log(1, "SkyGen: Detected portable MO2 setup (game installed in MO2 root).")
        return True

    # 2. Check for Root Builder ini/settings (if installed)
    # This might depend on Root Builder's specific implementation
    # MODIFIED: Changed to use wrapped_organizer._organizer
    root_builder_ini_path = Path(wrapped_organizer._organizer.basePath()).resolve() / "ModOrganizer.ini" 
    
    config = configparser.ConfigParser()
    try:
        config.read(root_builder_ini_path, encoding='utf-8')
        if 'RootBuilder' in config:
            if config.getboolean('RootBuilder', 'enabled', fallback=False):
                wrapped_organizer.log(1, "SkyGen: Detected Root Builder is enabled.")
                return True
    except Exception as e:
        wrapped_organizer.log(2, f"SkyGen: WARNING: Could not read Root Builder settings from ModOrganizer.ini: {e}")
        
    wrapped_organizer.log(1, "SkyGen: No root mode detected.")
    return False


def write_pas_script_to_xedit(script_full_path: Path, wrapped_organizer: Any):
    """
    Writes the fixed Pascal script content to the specified full path (xEdit's script directory).
    The content is now hardcoded in this function, with m_Common and m_Process dependency removed.
    """
    script_content = """
unit ExportPluginData;

uses
  SysUtils, Classes, Dialogs, m_JSON; // m_Common and m_Process removed

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
  WorldspacePath: string; // Declared
  WorldspaceFormID: string; // Declared
  WorldspaceName: string; // Declared
  VMADElement: IInterface; // Declared for VMAD iteration
  PropElement: IInterface; // Declared for VMAD iteration
  KeywordFormID: string; // Declared for VMAD iteration
  KeywordEditorID: string; // Declared for VMAD iteration
  KeywordName: string; // Declared for VMAD iteration
  KeywordObject: TJSONObject; // Declared for VMAD iteration
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
    // AddMessage(Format('Processing record: %s, Origin: %s', [LongName(ARecord), GetElementFile(ARecord).FileName])); // REMOVED AddMessage

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
        begin
          if Pos(Keyword, EditorID) > 0 then // Case-sensitive check. NOTE: EditorID must be populated before this.
          begin
            MatchFound := True;
            Break;
          end;
        end;
      end;
    end;

    if not MatchFound then
      Exit(0); // Skip if keywords did not match and broad swap is not enabled

    // Extract data
    FormID := IntToHex(ARecord.GetFormID, 8); // Format as 8-digit hex string
    EditorID := ARecord.GetEditorID; // Ensure EditorID is populated here
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

    // Add Worldspace and Location
    if HasElement(ARecord, 'FULL\\NAME') then
    begin
        ItemJSON.Add('FullName', EscapeJsonString(ElementEditValues(ARecord, 'FULL\\NAME')));
    end;

    // New: Extract Worldspace FormID and Name
    if Signature = 'CELL' then // Only relevant for CELL records
    begin
        // Try to get Worldspace from its reference
        // Assuming parent field 'PNAM' points to Worldspace
        WorldspacePath := 'PNAM'; // Standard path for Worldspace for CELLs
        if HasElement(ARecord, WorldspacePath) then
        begin
            WorldspaceFormID := IntToHex(GetFormID(GetElement(ARecord, WorldspacePath)), 8);
            WorldspaceName := Name(GetElement(ARecord, WorldspacePath));
            ItemJSON.Add('WorldspaceFormID', WorldspaceFormID);
            ItemJSON.Add('WorldspaceName', EscapeJsonString(WorldspaceName));
        end;
    end
    else if HasElement(ARecord, 'WRLD') then // For records that have a WRLD property
    begin
        WorldspacePath := 'WRLD'; // Standard path for Worldspace
        if HasElement(ARecord, WorldspacePath) then
        begin
            WorldspaceFormID := IntToHex(GetFormID(GetElement(ARecord, WorldspacePath)), 8);
            WorldspaceName := Name(GetElement(ARecord, WorldspacePath));
            ItemJSON.Add('WorldspaceFormID', WorldspaceFormID);
            ItemJSON.Add('WorldspaceName', EscapeJsonString(WorldspaceName));
        end;
    end;


    // Get relevant model path (MODL)
    if HasElement(ARecord, 'MODL') then
    begin
        ItemJSON.Add('Model', EscapeJsonString(ElementEditValues(ARecord, 'MODL')));
    end;

    // Get Object Bounds
    if HasElement(ARecord, 'OBND') then
    begin
        ItemJSON.Add('ObjectBounds', TJSONObject.Create);
        (ItemJSON.Get('ObjectBounds') as TJSONObject).Add('X1', StrToInt(ElementEditValues(ARecord, 'OBND\\\\X1')));
        (ItemJSON.Get('ObjectBounds') as TJSONObject).Add('Y1', StrToInt(ElementEditValues(ARecord, 'OBND\\\\Y1')));
        (ItemJSON.Get('ObjectBounds') as TJSONObject).Add('Z1', StrToInt(ElementEditValues(ARecord, 'OBND\\\\Z1')));
        (ItemJSON.Get('ObjectBounds') as TJSONObject).Add('X2', StrToInt(ElementEditValues(ARecord, 'OBND\\\\X2')));
        (ItemJSON.Get('ObjectBounds') as TJSONObject).Add('Y2', StrToInt(ElementEditValues(ARecord, 'OBND\\\\Y2')));
        (ItemJSON.Get('ObjectBounds') as TJSONObject).Add('Z2', StrToInt(ElementEditValues(ARecord, 'OBND\\\\Z2')));
    end;


    // Get Keywords (VMAD)
    if HasElement(ARecord, 'VMAD') then
    begin
        KeywordsArray := TJSONArray.Create; // Re-introduced initialization for KeywordsArray
        try
            SetElementActive(ARecord); // Set current object as active for iterating keywords
            // Iterate through all properties within the VMAD section, looking for FormIDs that are Keywords
            // Assuming keywords are typically 'KWDA' or similar sub-records within VMAD or directly referenced.
            // This might require more specific knowledge of the VMAD structure.
            // For now, we'll iterate direct child elements if VMAD is the form.
            if ElementCount(ElementByPath(ARecord, 'VMAD')) > 0 then
            begin
                VMADElement := ElementByPath(ARecord, 'VMAD');
                SetElementActive(VMADElement);
                SetIterator(VMADElement, "", false); // Iterate children of VMAD
                while HasNext do
                begin
                    PropElement := GetNext; // This would be the property, e.g., "Property 0", "Property 1"
                    if Assigned(PropElement) then
                    begin
                        // Get the Value (FormID of the Keyword)
                        KeywordFormID := IntToHex(GetFormID(ElementByPath(PropElement, 'Value')), 8);
                        if (KeywordFormID <> '') then
                        begin
                            KeywordEditorID := EditorID(GetElement(PropElement, 'Value'));
                            KeywordName := Name(GetElement(PropElement, 'Value'));
                            
                            KeywordObject := TJSONObject.Create;
                            KeywordObject.Add('FormID', KeywordFormID);
                            KeywordObject.Add('EditorID', EscapeJsonString(KeywordEditorID));
                            KeywordObject.Add('Name', EscapeJsonString(KeywordName));
                            KeywordsArray.Add(KeywordObject);
                        end;
                    end;
                end;
            end;
        finally
            // This finally block might free KeywordsArray prematurely if it's meant for outer scope.
            // If KeywordsArray is added to ItemJSON, then ItemJSON owns it and should free it later.
            // Removing `KeywordsArray.Free;` from here to prevent double-free or premature freeing.
            # KeywordsArray.Free; // Moved or removed based on usage. If added to ItemJSON, ItemJSON handles freeing.
        end;
        // Re-check after populating if any keywords were actually found
        if KeywordsArray.Count > 0 then
        begin
            ItemJSON.Add('Keywords', KeywordsArray); // Add KeywordsArray to ItemJSON
        end else begin
            KeywordsArray.Free; // Free if not added to JSON
        end;
    end;

    JsonOutput.Add(ItemJSON); // Add as JSON object to the main array
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
    // AddMessage('ERROR: OutputFilePath not provided as script option.'); // REMOVED AddMessage
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
    // AddMessage(Format('Successfully exported data to: %s', [OutputFilePath])); // REMOVED AddMessage
  except
    on E: Exception do
    begin
      // AddMessage(Format('ERROR: Failed to save JSON to file %s: %s', [OutputFilePath, E.Message])); // REMOVED AddMessage
      Result := 1; // Indicate error
    end;
  end;

  MainOutputObject.Free; // Free the main object (which also frees JsonOutput)

  Result := 0; // Success
end;

end.
    """
    try:
        script_full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(script_full_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        wrapped_organizer.log(0, f"SkyGen: DEBUG: Pascal script written to: {script_full_path}")
    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write Pascal script to {script_full_path}: {e}\n{traceback.format_exc()}")
        raise # Re-raise to halt execution if script write fails


def run_xedit_export(
    wrapped_organizer: Any,
    dialog: Any,
    xedit_exe_path: Path,
    xedit_mo2_name: str,
    game_root_path: Path,
    xedit_script_filename: str,
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

    # Define the full path where the Pascal script will be written in xEdit's script directory
    xedit_script_dir = xedit_exe_path.parent / "Edit Scripts"
    xedit_script_dir.mkdir(parents=True, exist_ok=True) # Ensure xEdit's script directory exists
    xedit_target_script_path = xedit_script_dir / xedit_script_filename

    # We write the script content directly to xEdit's script path
    try:
        write_pas_script_to_xedit(xedit_target_script_path, wrapped_organizer)
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
        f"TargetPlugin={target_plugin_filename}", # NO single quotes around the value
        f"OutputFilePath={expected_output_path.as_posix().replace('\\', '/')}", # NO single quotes
        f"TargetCategory={target_category if target_category else ''}", # NO single quotes
        f"BroadCategorySwap={str(broad_category_swap_enabled).lower()}", # NO single quotes
        f"Keywords={keywords}" # NO single quotes
    ]

    # Ensure the current working directory for xEdit is the game's root directory
    # This is crucial for xEdit to find game data correctly.
    xedit_cwd = str(game_root_path)

    # The xEdit preload block has been REMOVED as it was causing double launches.
    # It used to be here:
    # wrapped_organizer.log(0, "SkyGen: DEBUG: Pre-loading xEdit to force MO2 VFS engagement...")
    # ... (preload_args, startApplication, time.sleep) ...
    # wrapped_organizer.log(0, "SkyGen: DEBUG: xEdit pre-load executed, VFS should be engaged.")
    wrapped_organizer.log(1, f"SkyGen: Launching xEdit '{xedit_mo2_name}' for export...")
    wrapped_organizer.log(0, f"SkyGen: DEBUG: xEdit binary: {xedit_exe_path}")
    wrapped_organizer.log(0, f"SkyGen: DEBUG: xEdit CWD: {xedit_cwd}")

    process = None
    try:
        # Construct the command-line arguments for xEdit
        xedit_args = [
            # Game version argument (e.g., -SSE, -VR). Empty string if not applicable.
            f"-{game_version.replace('Skyrim', '').upper()}" if game_version and game_version.startswith("Skyrim") else "",
            "-r",                                # Recommended: Force xEdit to use clean masters
            "-quickshow",                        # Prevents xEdit from opening its UI
            "-autoload",                         # Loads all plugins without prompt
            "-AutoExit",                         # NEW: Force xEdit to exit automatically
            "-Quit",                             # NEW: Another command to ensure exit
            f"-script:{xedit_script_filename}", # Uses the script already in Edit Scripts folder
        ] + [f"-scriptoption:{opt}" for opt in script_options]
            # Filter out any empty strings from xedit_args (e.g., if game_version arg is empty)
        xedit_args = [arg for arg in xedit_args if arg]

        wrapped_organizer.log(0, f"SkyGen: DEBUG: xEdit arguments for startApplication: {xedit_args}")

        # Use organizer.startApplication to launch xEdit with VFS integration
        # The first argument is the MO2 executable name, second is a list of arguments for that executable.
        # The last argument is the working directory (game root).
        success = wrapped_organizer._organizer.startApplication(xedit_mo2_name, xedit_args, xedit_cwd)
        
        if not success:
            dialog.showError("xEdit Launch Error", f"Failed to launch xEdit ('{xedit_mo2_name}'). Check MO2's main log for details.")
            wrapped_organizer.log(4, f"SkyGen: CRITICAL: startApplication failed for xEdit '{xedit_mo2_name}'.")
            return None
        
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
        
        return expected_output_path if success_flag else None # Return the path if successful

    except Exception as e:
        dialog.showError("Unexpected Error", f"An unexpected error occurred during xEdit export:\n{e}\n{traceback.format_exc()}")
        wrapped_organizer.log(3, f"Exception in run_xedit_export: {e}\n{traceback.format_exc()}")
        
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
            dialog_instance.showError("BOS INI Write Error", f"Failed to write BOS INI for '{plugin_name}': {e}")
            wrapped_organizer.log(3, f"SkyGen: ERROR: Failed to write BOS INI for {plugin_name}: {e}")

    if generated_count > 0:
        wrapped_organizer.log(1, f"SkyGen: Successfully generated {generated_count} BOS INI file(s).")
        return True
    else:
        wrapped_organizer.log(1, "SkyGen: No BOS INI files were generated.")
        return False


def clean_temp_script_and_ini(xedit_exe_path: Path, output_json_path: Path, xedit_script_filename: str, wrapped_organizer: Any):
    """
    Cleans up the Pascal script from xEdit's script directory, and the xEdit-generated
    log and JSON output files.
    """
    # Recalculate xedit_target_script_path for deletion
    xedit_script_dir = xedit_exe_path.parent / "Edit Scripts"
    xedit_target_script_path = xedit_script_dir / xedit_script_filename

    # Clean up the Pascal script from xEdit's script directory
    if xedit_target_script_path.exists():
        try:
            xedit_target_script_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted Pascal script from xEdit's script directory: {xedit_target_script_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete Pascal script '{xedit_target_script_path}': {e}")

    # Define the expected log path based on the output JSON path
    expected_log_path = output_json_path.with_suffix('.log')

    # Clean up the xEdit-generated JSON output
    if output_json_path.exists():
        try:
            output_json_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted xEdit output JSON: {output_json_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete xEdit output JSON '{output_json_path}': {e}")
            
    # Clean up the xEdit-generated log file
    if expected_log_path.exists():
        try:
            expected_log_path.unlink()
            wrapped_organizer.log(1, f"SkyGen: Deleted xEdit output log: {expected_log_path}")
        except Exception as e:
            wrapped_organizer.log(2, f"SkyGen: Failed to delete xEdit output log '{expected_log_path}': {e}")

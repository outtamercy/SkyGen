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
import tempfile # Added for temporary file creation
import psutil # Added for process monitoring
from PyQt5.QtCore import QStringList, QProcess # Added for MO2's startApplication and process handling


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
        if dialog_instance:
            dialog_instance.showError("File Read Error", f"Failed to load {description} from {file_path}: {e}")
        return None


def get_xedit_exe_path(wrapped_organizer: Any, dialog_instance: Any) -> Optional[tuple[Path, str]]:
    """
    Attempts to find the xEdit executable (SSEEdit.exe, FO4Edit.exe, etc.)
    through MO2's executables list.
    Returns a tuple of (Path to xEdit.exe, MO2 executable name).
    """
    xedit_executables = []
    # Using .getExecutables() to get a list of registered executables in MO2
    executables = wrapped_organizer.getExecutables()
    for name in executables.keys(): # Iterate over executable names
        exe = executables[name]
        # Check for common xEdit executable names (case-insensitive)
        if "edit" in exe.binary().lower() and ("sse" in exe.binary().lower() or "fo4" in exe.binary().lower() or "skyrimvr" in exe.binary().lower()):
            xedit_executables.append((Path(exe.binary()), name))
            wrapped_organizer.log(0, f"SkyGen: DEBUG: Found xEdit executable: {exe.binary()} (MO2 Name: {name})")

    if not xedit_executables:
        dialog_instance.showError(
            "xEdit Not Found",
            "Could not find any xEdit executable (SSEEdit.exe, FO4Edit.exe, etc.) configured in Mod Organizer 2. "
            "Please add your xEdit executable to MO2's executables list."
        )
        wrapped_organizer.log(4, "SkyGen: ERROR: No xEdit executable found in MO2 settings.")
        return None
    elif len(xedit_executables) == 1:
        wrapped_organizer.log(1, f"SkyGen: Found xEdit executable: {xedit_executables[0][0]} (MO2 Name: {xedit_executables[0][1]})")
        return xedit_executables[0]
    else:
        # If multiple xEdit executables are found, try to pick the one associated with the current game
        current_game_type = wrapped_organizer.currentGame().type()
        for exe_path, mo2_name in xedit_executables:
            if current_game_type == mobase.GameType.SSE and "sseedit" in exe_path.name.lower():
                wrapped_organizer.log(1, f"SkyGen: Found multiple xEdit executables, selecting SSEEdit for current game: {exe_path} (MO2 Name: {mo2_name})")
                return exe_path, mo2_name
            elif current_game_type == mobase.GameType.SkyrimVR and "skyrimvredit" in exe_path.name.lower():
                wrapped_organizer.log(1, f"SkyGen: Found multiple xEdit executables, selecting SkyrimVREdit for current game: {exe_path} (MO2 Name: {mo2_name})")
                return exe_path, mo2_name
            # Add other game types if needed

        # Fallback if specific game version not found among multiple xEdits
        dialog_instance.showWarning(
            "Multiple xEdit Found",
            f"Multiple xEdit executables found. Please ensure the correct one is named appropriately "
            f"for your current game ({wrapped_organizer.currentGame().displayName()}). Using: {xedit_executables[0][0].name}"
        )
        wrapped_organizer.log(3, f"SkyGen: WARNING: Multiple xEdit executables found, selected first one by default: {xedit_executables[0][0]} (MO2 Name: {xedit_executables[0][1]})")
        return xedit_executables[0]


def write_pas_script_to_xedit(script_full_path: Path, wrapped_organizer: Any):
    """
    Writes the Pascal script content to the specified full path (xEdit's script directory).
    The content is now hardcoded in this function, with m_Common and m_Process dependency removed.
    """
    script_content = """
unit ExportPluginData;

uses
  SysUtils, Classes, Dialogs, m_JSON, m_INI; 

var
  JsonOutput: TJSONArray;
  GlobalTargetPlugin: string;
  GlobalOutputFilePath: string;
  GlobalTargetCategory: string;
  GlobalBroadCategorySwap: Boolean;
  GlobalKeywords: string;


procedure ReadSkyGenINI; 
var
  ini: IwbIniFile;
  iniPath: string;
  BroadCategorySwapStr: string; 
begin
  Result := 0; 
  iniPath := ScriptsPath + ExtractFileNameWithoutExt(ScriptName) + '.ini';
  
  if not FileExists(iniPath) then begin
    AddMessage('[SkyGen] ERROR: Failed to load INI - INI file not found: ' + iniPath);
    Result := 1; 
    Exit;
  end;

  try
    ini := TObject(CreateAPI(iniPath)) as IwbIniFile;
  except
    on E: Exception do
    begin
      AddMessage(Format('[SkyGen] ERROR: Failed to create INI object for %s: %s', [iniPath, E.Message]));
      Result := 1;
      Exit;
    end;
  end;

  if not ini.SectionExists('SkyGenOptions') then begin
    AddMessage('[SkyGen] ERROR: Failed to load INI - missing [SkyGenOptions] section in ' + iniPath);
    Result := 1;
    Exit;
  end;

  GlobalTargetPlugin := ini.ReadString('SkyGenOptions', 'TargetPlugin', '');
  GlobalOutputFilePath := ini.ReadString('SkyGenOptions', 'OutputFilePath', '');
  GlobalTargetCategory := ini.ReadString('SkyGenOptions', 'TargetCategory', '');
  BroadCategorySwapStr := ini.ReadString('SkyGenOptions', 'BroadCategorySwap', 'false');
  GlobalKeywords := ini.ReadString('SkyGenOptions', 'Keywords', '');

  GlobalBroadCategorySwap := (LowerCase(BroadCategorySwapStr) = 'true');

  if (GlobalTargetPlugin = '') or (GlobalOutputFilePath = '') then begin
    AddMessage('[SkyGen] ERROR: Failed to load INI - missing required values (TargetPlugin or OutputFilePath) in ' + iniPath);
    Result := 1;
    Exit;
  end;
  AddMessage(Format('[SkyGen] INFO: Successfully loaded INI options from: %s', [iniPath]));
  AddMessage(Format('[SkyGen] INFO: TargetPlugin=%s, OutputFilePath=%s, Category=%s, BroadSwap=%s, Keywords=%s', [GlobalTargetPlugin, GlobalOutputFilePath, GlobalTargetCategory, BroadCategorySwapStr, GlobalKeywords]));
end;


function Initialize: Integer;
begin
  Result := 0; 
  ReadSkyGenINI; 
  if Result <> 0 then 
  begin
    AddMessage('[SkyGen] CRITICAL: INI loading failed during Initialize. Aborting xEdit script.');
    Exit; 
  end;
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
  KeywordsArray: TJSONArray;
  i: Integer;
  Keyword: string;
  MatchFound: Boolean;
  WorldspacePath: string;
  WorldspaceFormID: string;
  WorldspaceName: string;
  VMADElement: IInterface;
  PropElement: IInterface;
  KeywordFormID: string;
  KeywordEditorID: string;
  KeywordName: string;
  KeywordObject: TJSONObject;
begin
  Result := 0; 

  if (ARecord <> nil) and (ARecord.GetElementFile = ARecord.GetElementFile.Root) then
  begin
    Signature := SignatureToString(ARecord.GetSignature);

    if (GlobalTargetPlugin <> '') and (GetElementFile(ARecord).FileName <> GlobalTargetPlugin) then
      Exit(0); 

    if (GlobalTargetCategory <> '') and (Signature <> GlobalTargetCategory) then
    begin
      if GlobalBroadCategorySwap then
      begin
      end
      else
        Exit(0); 
    end;

    MatchFound := True;
    if (GlobalKeywords <> '') and (not GlobalBroadCategorySwap) then
    begin
      MatchFound := False;
      EditorID := ARecord.GetEditorID; 
      for Keyword in SplitString(GlobalKeywords, [',', ' ']) do
      begin
        Keyword := Trim(Keyword);
        if Keyword <> '' then
        begin
          if Pos(Keyword, EditorID) > 0 then
          begin
            MatchFound := True;
            Break;
          end;
        end;
      end;
    end;

    if not MatchFound then
      Exit(0);

    FormID := IntToHex(ARecord.GetFormID, 8);
    EditorID := ARecord.GetEditorID;
    FullName := ARecord.GetName;
    OriginMod := GetElementFile(ARecord).FileName;
    ParentName := '';
    if Signature = 'ARMA' then
    begin
      Element := ARecord.GetElementByPath('PARE');
      if (Element <> nil) then
        ParentName := LongName(Element.AsLink.Target);
    end;

    ItemJSON := TJSONObject.Create;
    ItemJSON.Add('Signature', Signature);
    ItemJSON.Add('FormID', FormID);
    ItemJSON.Add('EditorID', EditorID);
    ItemJSON.Add('FullName', FullName);
    ItemJSON.Add('OriginMod', OriginMod);
    if ParentName <> '' then
      ItemJSON.Add('ParentName', ParentName);

    if HasElement(ARecord, 'FULL\\NAME') then
    begin
        ItemJSON.Add('FullName', EscapeJsonString(ElementEditValues(ARecord, 'FULL\\NAME')));
    end;

    if Signature = 'CELL' then
    begin
        WorldspacePath := 'PNAM';
        if HasElement(ARecord, WorldspacePath) then
        begin
            WorldspaceFormID := IntToHex(GetFormID(GetElement(ARecord, WorldspacePath)), 8);
            WorldspaceName := Name(GetElement(ARecord, WorldspacePath));
            ItemJSON.Add('WorldspaceFormID', WorldspaceFormID);
            ItemJSON.Add('WorldspaceName', EscapeJsonString(WorldspaceName));
        end;
    end
    else if HasElement(ARecord, 'WRLD') then
    begin
        WorldspacePath := 'WRLD';
        if HasElement(ARecord, WorldspacePath) then
        begin
            WorldspaceFormID := IntToHex(GetFormID(GetElement(ARecord, WorldspacePath)), 8);
            WorldspaceName := Name(GetElement(ARecord, WorldspacePath));
            ItemJSON.Add('WorldspaceFormID', WorldspaceFormID);
            ItemJSON.Add('WorldspaceName', EscapeJsonString(WorldspaceName));
        end;
    end;


    if HasElement(ARecord, 'MODL') then
    begin
        ItemJSON.Add('Model', EscapeJsonString(ElementEditValues(ARecord, 'MODL')));
    end;

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


    if HasElement(ARecord, 'VMAD') then
    begin
        KeywordsArray := TJSONArray.Create;
        try
            SetElementActive(ARecord);
            if ElementCount(ElementByPath(ARecord, 'VMAD')) > 0 then
            begin
                VMADElement := ElementByPath(ARecord, 'VMAD');
                SetElementActive(VMADElement);
                SetIterator(VMADElement, "", false);
                while HasNext do
                begin
                    PropElement := GetNext;
                    if Assigned(PropElement) then
                    begin
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
        end;
        if KeywordsArray.Count > 0 then
        begin
            ItemJSON.Add('Keywords', KeywordsArray);
        end else begin
            KeywordsArray.Free;
        end;
    end;

    JsonOutput.Add(ItemJSON);
  end;
  Result := 0; 
end;


function Main: Integer;
var
  MainOutputObject: TJSONObject;
begin
  Result := 0; 

  if Result <> 0 then Exit; 

  if GlobalOutputFilePath = '' then
  begin
    AddMessage('[SkyGen] ERROR: GlobalOutputFilePath is empty after INI load. Aborting.');
    Result := 1;
    Exit;
  end;

  JsonOutput := TJSONArray.Create;

  ProcessRecords(Self);

  MainOutputObject := TJSONObject.Create;
  MainOutputObject.Add('baseObjects', JsonOutput);

  try
    MainOutputObject.SaveToFile(GlobalOutputFilePath);
    AddMessage(Format('[SkyGen] Successfully exported data to: %s', [GlobalOutputFilePath]));
  except
    on E: Exception do
    begin
      AddMessage(Format('[SkyGen] ERROR: Failed to save JSON to file %s: %s', [GlobalOutputFilePath, E.Message]));
      Result := 1;
    end;
  end;

  MainOutputObject.Free;

  Result := 0; 
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


def generate_and_write_skypatcher_yaml(
    wrapped_organizer: Any,
    json_data: dict,
    target_mod_name: str,
    output_folder_path: Path,
    record_type: str,
    broad_category_swap_enabled: bool
) -> bool:
    """
    Generates SkyPatcher YAML content from JSON data and writes it to a file.
    """
    if not json_data:
        wrapped_organizer.log(3, "SkyGen: No JSON data provided for YAML generation.")
        return False

    if not target_mod_name:
        wrapped_organizer.log(3, "SkyGen: Target mod name is required for YAML generation.")
        return False
    
    # Find the internal name for the target mod
    target_mod_internal_name = _get_internal_mod_name_from_display_name(wrapped_organizer, target_mod_name)
    if not target_mod_internal_name:
        wrapped_organizer.log(3, f"SkyGen: Could not determine internal name for target mod '{target_mod_name}'. Cannot generate YAML.")
        return False

    # Ensure output directory exists
    output_folder_path.mkdir(parents=True, exist_ok=True)

    yaml_data = {
        "patchName": "SkyGen Patch", # Default name, could be made configurable
        "patches": []
    }

    generated_count = 0
    # The JSON data structure from xEdit export is expected to be a list of records.
    # Each record is a dictionary with 'Signature', 'EditorID', 'FormID', 'OriginMod', 'Fields'.
    
    # Correctly access the list of records from 'baseObjects' key
    records_list = json_data.get('baseObjects', [])
    filtered_records = [rec for rec in records_list if rec.get('Signature') == record_type.upper()]

    if not filtered_records:
        wrapped_organizer.log(2, f"SkyGen: No records of type '{record_type}' found in the exported JSON data.")
        return False

    for record in filtered_records:
        record_form_id = record.get("FormID")
        record_editor_id = record.get("EditorID")
        record_origin_mod = record.get("OriginMod") # Corrected from "Plugin" to "OriginMod"

        if not record_form_id or not record_editor_id or not record_origin_mod:
            wrapped_organizer.log(3, f"SkyGen: Skipping malformed record: {record}")
            continue

        patch_entry = {
            "type": "Form",
            "form": f"{record_origin_mod}:{record_form_id}", # Use OriginMod here
            "target": f"{target_mod_internal_name}", # Use internal name for target
            "mode": "patch",
            "changes": {}
        }
        
        # Determine the field to copy based on broad_category_swap_enabled and record_type
        field_to_copy = None
        if record_type.upper() == "STAT":
            field_to_copy = "OBND" if broad_category_swap_enabled else "FNAM"
        elif record_type.upper() == "TREE":
            field_to_copy = "MODL" # Trees typically use MODL for model path
        elif record_type.upper() == "GRAS":
            field_to_copy = "FULL" # Grass uses FULL
        elif record_type.upper() == "FLOR":
            field_to_copy = "MODL" # Flora typically uses MODL for model path
        elif record_type.upper() == "MISC":
            field_to_copy = "MODL" # MISC uses MODL for model path
        elif record_type.upper() == "CONT":
            field_to_copy = "MODL" # CONT uses MODL for model path
        elif record_type.upper() == "LIGH":
            field_to_copy = "MODL" # LIGH often uses MODL for model path
        elif record_type.upper() == "ACTI":
            field_to_copy = "MODL" # Activators often use MODL
        elif record_type.upper() == "WEAP":
            field_to_copy = "MODL" # Weapons use MODL
        elif record_type.upper() == "ARMO":
            field_to_copy = "MODL" # Armor uses MODL
        elif record_type.upper() == "AMMO":
            field_to_copy = "MODL" # Ammo uses MODL

        # Add more record types and their corresponding fields as needed
        # Default fallback if a specific field isn't found or type isn't handled
        if field_to_copy is None:
            # Attempt to find a "MODL" or "FNAM" field as a general fallback for model/NIF paths
            if "MODL" in record.get("Fields", {}):
                field_to_copy = "MODL"
            elif "FNAM" in record.get("Fields", {}):
                field_to_copy = "FNAM"
            elif "FULL" in record.get("Fields", {}):
                field_to_copy = "FULL"
            # If still none, log and skip this record's change generation
            if field_to_copy is None:
                wrapped_organizer.log(2, f"SkyGen: INFO: No specific field defined for record type '{record_type}' (EditorID: {record_editor_id}). Skipping automatic field copy for this record.")
                continue # Skip this record if no relevant field can be determined
        
        field_value = record.get("Fields", {}).get(field_to_copy)

        if field_value:
            # Construct the path within the YAML "changes" dictionary
            # For MODL, FNAM, FULL fields, the path is typically direct.
            # SkyPatcher expects paths relative to the data folder.
            patch_entry["changes"][field_to_copy] = field_value
            yaml_data["patches"].append(patch_entry)
            generated_count += 1
        else:
            wrapped_organizer.log(2, f"SkyGen: Skipping record '{record_editor_id}' (Type: {record_type}) as field '{field_to_copy}' was not found or was empty.")

    if not yaml_data["patches"]:
        wrapped_organizer.log(2, f"SkyGen: No valid patches generated for record type '{record_type}'.")
        return False

    # Create a descriptive filename based on target mod and category
    safe_target_mod_name = "".join(c for c in target_mod_name if c.isalnum() or c in (' ', '_', '-')).strip()
    safe_category = "".join(c for c in record_type if c.isalnum()).strip()
    timestamp = int(time.time()) # Unique timestamp
    filename = f"SkyGen_Patch_{safe_target_mod_name}_{safe_category}_{timestamp}.yaml"
    output_yaml_path = output_folder_path / filename

    try:
        with open(output_yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False) # sort_keys=False to preserve order
        wrapped_organizer.log(1, f"SkyGen: Successfully generated SkyPatcher YAML at: {output_yaml_path}")
        return True
    except Exception as e:
        wrapped_organizer.log(4, f"SkyGen: ERROR: Failed to write SkyPatcher YAML to {output_yaml_path}: {e}")
        return False


def generate_bos_ini_files(wrapped_organizer: Any, igpc_data: dict, output_folder_path: Path, dialog_instance: Any) -> bool:
    """
    Generates BOS INI files from IGPC data.
    """
    if not igpc_data:
        wrapped_organizer.log(3, "SkyGen: No IGPC data provided for BOS INI generation.")
        dialog_instance.showError("BOS INI Error", "No IGPC data provided. Cannot generate BOS INI files.")
        return False

    bos_output_dir = output_folder_path / "BOS_INI_Generated"
    bos_output_dir.mkdir(parents=True, exist_ok=True)
    wrapped_organizer.log(1, f"SkyGen: BOS INI files will be saved to: {bos_output_dir}")

    generated_count = 0

    # IGPC data structure: {plugin_name: {editor_id: {record_data}}}
    for plugin_name, records in igpc_data.items():
        ini_content = [f"[{plugin_name}]"]
        added_entries = 0
        for editor_id, record_data in records.items():
            form_id = record_data.get("FormID")
            if form_id:
                # Ensure FormID is uppercase for consistency with BOS format
                ini_content.append(f"{editor_id}={form_id.upper()}")
                added_entries += 1
            else:
                wrapped_organizer.log(2, f"SkyGen: WARNING: Skipping record '{editor_id}' in '{plugin_name}' due to missing FormID.")
        
        if added_entries > 0:
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
        dialog_instance.showInformation("BOS INI Generation Complete", f"Successfully generated {generated_count} BOS INI file(s) in:\n{bos_output_dir}")
        return True
    else:
        wrapped_organizer.log(1, "SkyGen: No BOS INI files were generated.")
        dialog_instance.showWarning("BOS INI Generation", "No BOS INI files were generated. Ensure your IGPC JSON data is valid.")
        return False


def clean_temp_files(script_path: Path, ini_path: Path, debug_logger: Any):
    """
    Cleans up the Pascal script and INI file from xEdit's Edit Scripts folder.
    """
    if script_path.exists():
        try:
            script_path.unlink()
            debug_logger(f"SkyGen: DEBUG: Deleted Pascal script: {script_path}")
        except Exception as e:
            debug_logger(f"SkyGen: WARNING: Failed to delete Pascal script '{script_path}': {e}")

    if ini_path.exists():
        try:
            ini_path.unlink()
            debug_logger(f"SkyGen: DEBUG: Deleted INI file: {ini_path}")
        except Exception as e:
            debug_logger(f"SkyGen: WARNING: Failed to delete INI file '{ini_path}': {e}")


def get_game_root_from_general_ini(wrapped_organizer: Any) -> Optional[Path]:
    """
    Attempts to read the sResourceArchive2List setting from the game's Skyrim.ini
    to determine the game's root directory. This is a fallback/additional check.
    """
    game_ini_path = None
    
    # MO2 stores game INI paths in game features if available
    if hasattr(wrapped_organizer, 'gameInfo') and wrapped_organizer.gameInfo() is not None:
        game_info = wrapped_organizer.gameInfo()
        if hasattr(game_info, 'iniFiles') and game_info.iniFiles():
            for ini_file in game_info.iniFiles():
                if "skyrim.ini" in str(ini_file).lower():
                    game_ini_path = Path(ini_file)
                    break
    
    if not game_ini_path:
        wrapped_organizer.log(2, "SkyGen: WARNING: Could not find game's Skyrim.ini via MO2's gameInfo(). Attempting common paths.")
        # Fallback to common user documents path for Skyrim.ini
        documents_path = Path.home() / "Documents" / "My Games"
        game_variants = ["Skyrim Special Edition", "Skyrim VR"]
        for variant in game_variants:
            potential_ini = documents_path / variant / "Skyrim.ini"
            if potential_ini.is_file():
                game_ini_path = potential_ini
                wrapped_organizer.log(1, f"SkyGen: Found Skyrim.ini at fallback path: {game_ini_path}")
                break

    if not game_ini_path or not game_ini_path.is_file():
        wrapped_organizer.log(3, "SkyGen: ERROR: Could not locate Skyrim.ini. Cannot determine game root from INI.")
        return None

    config = configparser.ConfigParser()
    config.optionxform = str # Preserve case for keys
    try:
        # Read the file with utf-8-sig to handle BOM if present
        with open(game_ini_path, 'r', encoding='utf-8-sig') as f:
            config.read_string(f.read())
        
        # Check in [Archive] section for sResourceArchive2List
        if 'Archive' in config and 'sResourceArchive2List' in config['Archive']:
            archive_list_line = config['Archive']['sResourceArchive2List']
            # The line usually looks like: Skyrim - Textures0.bsa, Skyrim - Textures1.bsa, ...
            # We need to extract a path from one of these BSAs.
            # A simple approach is to assume the BSAs are in the Data folder,
            # and the Data folder is relative to the game root.
            
            # Extract the first BSA filename
            first_bsa = archive_list_line.split(',')[0].strip()
            if first_bsa:
                # The Data folder is typically one level up from the .bsa
                # The game root is typically one level up from the Data folder
                
                # This is a heuristic. A more robust way might be to look for SkyrimSE.exe
                # in the parent directories of the INI or the detected data path.
                
                # Let's try to infer from the xEdit log file.
                # The xEdit log itself often states "Using Skyrim Special Edition Data Path: X:\..."
                # It's more reliable to parse this from the xEdit log itself if available.
                wrapped_organizer.log(2, "SkyGen: Info: sResourceArchive2List found, but direct game root inference from it is complex. Relying on xEdit's reported Data Path if available.")
                return None # Indicate not found via this method for now

    except configparser.Error as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Error parsing Skyrim.ini at {game_ini_path}: {e}")
    except IOError as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: IO Error reading Skyrim.ini at {game_ini_path}: {e}")
    
    return None # If no game root could be determined


def detect_root_mode(wrapped_organizer: Any, xedit_log_path: Path) -> Optional[str]:
    """
    Attempts to detect the xEdit root mode (Game, Base, Overwrite, Mod)
    by analyzing the xEdit log file.
    """
    if not xedit_log_path.is_file():
        wrapped_organizer.log(3, f"SkyGen: ERROR: xEdit log file not found at: {xedit_log_path}. Cannot detect root mode.")
        return None

    try:
        with open(xedit_log_path, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()

        # Search for lines indicating which folders xEdit is using for output.
        # This is a heuristic and might need refinement.
        # Look for explicit "Using xEdit Cache Path:" or similar, then infer where the plugin resides.
        # For our use case, we are checking where DynDOLOD Output.esp or similar gets placed.

        # Example relevant lines in xEdit log:
        # Using Skyrim Special Edition Data Path: H:\SteamLibrary\steamapps\common\Skyrim Special Edition\Data\
        # Using save path: C:\Users\Lore\Documents\My Games\Skyrim Special Edition\__MO_Saves\

        # The key is to find where the *target plugin* ultimately lives.
        # This function might be better off determining the game's Data path.
        # The MO2 mod list gives us the path to the mod folder.

        # Let's try to extract the main "Data Path" from the xEdit log.
        data_path_match = re.search(r"Using Skyrim Special Edition Data Path: (.*)", log_content, re.IGNORECASE)
        if data_path_match:
            data_path = Path(data_path_match.group(1).strip())
            wrapped_organizer.log(1, f"SkyGen: Detected xEdit Data Path: {data_path}")
            
            # Now, compare this to MO2's known paths
            mo2_mods_path = Path(wrapped_organizer.modsPath())
            mo2_overwrite_path = Path(wrapped_organizer.basePath()) / wrapped_organizer.modPath("overwrite") # This gives the full path to overwrite

            # Heuristic:
            # If the data path contains "overwrite", it's likely an Overwrite mode export.
            if str(data_path).lower().endswith(str(mo2_overwrite_path).lower()):
                return "Overwrite"
            
            # If the data path is within MO2's mods folder, it's a Mod mode export.
            # This check needs to be careful as data_path might be the actual game Data folder.
            # A Mod mode means the output plugin is *directly* in a mod folder.
            # This logic needs refinement.

            # The xEdit script itself is exporting to output_json_path.
            # We need to determine if the *target plugin* (like DynDOLOD Output) is an ESL/ESP
            # loaded directly from the Data folder, or from a mod.
            
            # This function is trying to infer the "root mode" which might be too complex from the log alone.
            # The "root mode" depends on where the *target plugin* resides, not necessarily the xEdit data path.
            # DynDOLOD Output, for example, is a mod in MO2.

            # Instead of trying to deduce "Root Mode" from xEdit log, which is about xEdit's *input* paths,
            # we need to know the *output* location for the generated YAML/INI and where the target plugin *resides*.
            # This is already handled by the `output_folder_path` and `target_mod_name` in `generate_and_write_skypatcher_yaml`.

            # The concept of "root mode" was more relevant for older methods where xEdit directly modified game data.
            # With SkyPatcher YAML, we're generating a separate patch file for MO2 to manage.
            # Thus, this function seems to be designed for a slightly different purpose than what the current workflow requires.

            # Let's simplify its purpose: maybe it's just to confirm xEdit loaded the right game data?
            # Or perhaps it's for `get_game_root_from_general_ini` to cross-reference?

            # For now, let's just return "Game" as a default, assuming MO2 is handling paths.
            # The more important aspect is that the target_mod_name is correctly resolved to its internal MO2 path.
            return "Game" # Default assumption if we detect data path.

    except Exception as e:
        wrapped_organizer.log(3, f"SkyGen: ERROR: Error reading xEdit log file {xedit_log_path}: {e}")
    
    return None # Could not detect root mode



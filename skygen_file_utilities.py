from pathlib import Path
import mobase
import os
import time
import json
import yaml
import configparser
import re
import traceback
import shutil
from collections import defaultdict
from typing import Optional, Any
from datetime import datetime

# MODIFIED: Changed QStringList to QByteArray for PyQt6 compatibility
try:
    from PyQt6.QtCore import QProcess, QByteArray
    from PyQt6.QtWidgets import QMessageBox
except ImportError:
    class QProcess:
        ProcessState = type('ProcessState', (object,), {'NotRunning': 0, 'Starting': 1, 'Running': 2})
        ExitStatus = type('ExitStatus', (object,), {'NormalExit': 0, 'CrashExit': 1})
        def __init__(self, *args, **kwargs): pass
        def setProgram(self, program): pass
        def setArguments(self, args): pass
        def setWorkingDirectory(self, path): pass
        def start(self): pass
        def waitForFinished(self, timeout): return True
        def kill(self): pass
        def terminate(self): pass
        def exitCode(self): return 0
        def exitStatus(self): return self.ExitStatus.NormalExit
        def state(self): return self.ProcessState.NotRunning
        def pid(self): return 0
        def readAllStandardOutput(self): return b''
        def readAllStandardError(self): return b''
        def errorString(self): return "Dummy QProcess Error"
        def readyReadStandardOutput(self): return DummySignal()
        def readyReadStandardError(self): return DummySignal()

    class QMessageBox:
        @staticmethod
        def critical(parent, title, message): print(f"CRITICAL: {title}: {message}")
        @staticmethod
        def warning(parent, title, message): print(f"WARNING: {title}: {message}")
        @staticmethod
        def information(parent, title, message): print(f"INFORMATION: {title}: {message}")

    class DummySignal:
        def connect(self, func): pass


# Define a constant for max poll time
MAX_POLL_TIME = 60

# Import MO2_LOG_* constants from skygen_constants
from .skygen_constants import MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO, MO2_LOG_DEBUG, MO2_LOG_TRACE


# --- Utility Functions (Global helpers) ---

def make_file_logger(log_file_path: Path) -> callable:
    """
    Creates and returns a logging function that writes messages to a specified file.
    Messages are prepended with a timestamp and log level name.
    """
    # Open the log file in append mode. It will be created if it doesn't exist.
    # Use a try-except block here to handle potential file opening errors.
    try:
        log_file_handle = open(log_file_path, 'a', encoding='utf-8')
    except Exception as e:
        print(f"SkyGen: CRITICAL ERROR: Could not open log file '{log_file_path}': {e}")
        log_file_handle = None # Ensure handle is None if opening fails

    def logger_func(level: int, message: str):
        if not log_file_handle:
            # Fallback to print if file handle is not available
            print(f"[ERROR - No File Log] [{datetime.now().isoformat()}] {message}")
            return

        level_name = {
            MO2_LOG_CRITICAL: "CRITICAL", MO2_LOG_ERROR: "ERROR", MO2_LOG_WARNING: "WARNING",
            MO2_LOG_INFO: "INFO", MO2_LOG_DEBUG: "DEBUG", MO2_LOG_TRACE: "TRACE"
        }.get(level, "UNKNOWN")
        
        full_message = f"[{datetime.now().isoformat()}] [{level_name}] {message}"
        try:
            log_file_handle.write(f"{full_message}\n")
            log_file_handle.flush() # Ensure immediate write to disk
        except Exception as e:
            # If writing fails, print to console as a last resort
            print(f"SkyGen: CRITICAL ERROR: Failed to write to log file '{log_file_path}': {e}. Message: {message}")
            # Optionally, disable further file logging attempts for this session
            # This is handled in OrganizerWrapper.log, so no need here.

    return logger_func


def load_json_data(wrapped_organizer: Any, file_path: Path, description: str, dialog_instance: Any) -> dict | None:
    """
    Loads JSON data from a specified file path.
    Requires wrapped_organizer for logging and dialog_instance for showing UI errors.
    """
    if not file_path or not file_path.is_file():
        wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: {description} file path is invalid or file not found at: {file_path}.")
        if dialog_instance:
            dialog_instance.showError("File Not Found", f"{description} file not found at the specified path: {file_path}.")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Successfully loaded {description} from: {file_path}")
            return data
    except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e:
        wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Error loading {description} from {file_path}: {e}")
        if dialog_instance:
            dialog_instance.showError("File Read Error", f"Error loading {description} from {file_path}:\n{e}")
        return None


def get_xedit_exe_path(wrapped_organizer: Any, dialog_instance: Any) -> tuple[Path, str] | None:
    """
    Determines the xEdit executable path and its MO2 registered name.
    Prioritizes official xEdit names used by MO2, with case-insensitive matching.
    """
    xedit_names_lower = {"sseedit", "tes5edit", "fo4edit", "fnvedit", "oblivionedit", "xedit"}
    executables = wrapped_organizer.getExecutables()

    for exe_name, exe_info in executables.items():
        exe_path = Path(exe_info.binary())
        
        if exe_info.displayName().lower() in xedit_names_lower or exe_path.stem.lower() in xedit_names_lower:
            wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Found xEdit executable: '{exe_info.displayName()}' at '{exe_path}' (MO2 Name: '{exe_name}')")
            return exe_path, exe_name

    wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: xEdit not found in MO2's registered executables. Attempting Wabbajack-style fallback.")
    
    mo2_base_path = Path(wrapped_organizer.profilePath()).parent.parent
    fallback_path = mo2_base_path / "tools" / "SSEEdit" / "SSEEdit.exe"

    if fallback_path.is_file():
        wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Found xEdit via Wabbajack-style fallback: {fallback_path}")
        return fallback_path, "SSEEdit"

    wrapped_organizer.log(MO2_LOG_WARNING, "SkyGen: WARNING: No recognized xEdit executable found in MO2 settings or via Wabbajack fallback.")
    if dialog_instance:
        dialog_instance.showWarning("xEdit Not Found", "Could not automatically detect xEdit executable. Please ensure it's added to MO2's executables (named 'SSEEdit', 'TES5Edit', etc.) or located in a standard Wabbajack 'tools' directory.")
    return None


def write_pas_script_to_xedit() -> str:
    """
    Returns the content of the Pascal script as a string.
    This script is used by xEdit to export plugin data.
    """
    # The Pascal script for xEdit
    pascal_script_content = """
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
    // AddMessage('[SkyGen] ERROR: Failed to load INI - INI file not found: ' + iniPath); // Removed
    Result := 1; 
    Exit;
  end;

  try
    ini := TObject(CreateAPI(iniPath)) as IwbIniFile;
  except
    on E: Exception do
    begin
      // AddMessage(Format('[SkyGen] ERROR: Failed to create INI object for %s: %s', [iniPath, E.Message])); // Removed
      Result := 1;
      Exit;
    end;
  end;

  if not ini.SectionExists('SkyGenOptions') then begin
    // AddMessage('[SkyGen] ERROR: Failed to load INI - missing [SkyGenOptions] section in ' + iniPath); // Removed
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
    // AddMessage('[SkyGen] ERROR: Failed to load INI - missing required values (TargetPlugin or OutputFilePath) in ' + iniPath); // Removed
    Result := 1;
    Exit;
  end;
  // AddMessage(Format('[SkyGen] INFO: Successfully loaded INI options from: %s', [iniPath])); // Removed
  // AddMessage(Format('[SkyGen] INFO: TargetPlugin=%s, OutputFilePath=%s, Category=%s, BroadSwap=%s, Keywords=%s', [GlobalTargetPlugin, GlobalOutputFilePath, BroadCategorySwapStr, GlobalKeywords])); // Removed
end;


function Initialize: Integer;
begin
  Result := 0; 
  ReadSkyGenINI; 
  if Result <> 0 then 
  begin
    // AddMessage('[SkyGen] CRITICAL: INI loading failed during Initialize. Aborting xEdit script.'); // Removed
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
        // If broad category swap is enabled, and the signature doesn't match the target category,
        // we still proceed if any keyword matches.
        // If no keywords are specified, this branch is effectively skipped as no filter is applied.
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

    // Apply keyword filter for broad category swap if keywords are present and broad swap is enabled
    if (GlobalKeywords <> '') and GlobalBroadCategorySwap then
    begin
      MatchFound := False; // Assume no match until one is found
      EditorID := ARecord.GetEditorID; // Get EditorID for keyword matching
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

    // Fetch FULL\\NAME if available and not already set by ARecord.GetName
    if HasElement(ARecord, 'FULL\\NAME') then
    begin
        ItemJSON.Add('FullName', EscapeJsonString(ElementEditValues(ARecord, 'FULL\\NAME')));
    end;

    // Worldspace information for CELL and other records with WRLD
    if Signature = 'CELL' then
    begin
        WorldspacePath := 'PNAM'; // For CELL, worldspace is typically PNAM
        if HasElement(ARecord, WorldspacePath) then
        begin
            WorldspaceFormID := IntToHex(GetFormID(GetElement(ARecord, WorldspacePath)), 8);
            WorldspaceName := Name(GetElement(ARecord, WorldspacePath));
            ItemJSON.Add('WorldspaceFormID', WorldspaceFormID);
            ItemJSON.Add('WorldspaceName', EscapeJsonString(WorldspaceName));
        end;
    end
    else if HasElement(ARecord, 'WRLD') then // For other records that might link to a worldspace
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

    // Model path
    if HasElement(ARecord, 'MODL') then
    begin
        ItemJSON.Add('Model', EscapeJsonString(ElementEditValues(ARecord, 'MODL')));
    end;

    // Object Bounds (OBND)
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

    // Keywords (VMAD)
    if HasElement(ARecord, 'VMAD') then
    begin
        KeywordsArray := TJSONArray.Create;
        try
            SetElementActive(ARecord);
            if ElementCount(ElementByPath(ARecord, 'VMAD')) > 0 then
            begin
                VMADElement := ElementByPath(ARecord, 'VMAD');
                SetElementActive(VMADElement);
                SetIterator(VMADElement, "", false); // Iterate through array elements
                while HasNext do
                begin
                    PropElement := GetNext; // Get individual property element
                    if Assigned(PropElement) then
                    begin
                        // The keyword FormID is under 'Value' sub-element of the property
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
            // No explicit cleanup for iterators needed, they are usually stack-allocated or self-managed.
            // Just ensure KeywordsArray is freed if not added to ItemJSON.
        end;
        if KeywordsArray.Count > 0 then
        begin
            ItemJSON.Add('Keywords', KeywordsArray);
        end else begin
            KeywordsArray.Free; // Free if empty to prevent memory leak
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

  // Read INI options again to ensure they are fresh for the Main function,
  // especially important if Initialize didn't run or if options changed.
  ReadSkyGenINI; 
  if Result <> 0 then Exit; // Exit if INI loading failed

  if GlobalOutputFilePath = '' then
  begin
    // AddMessage('[SkyGen] ERROR: GlobalOutputFilePath is empty after INI load. Aborting.'); // Removed
    Result := 1;
    Exit;
  end;

  JsonOutput := TJSONArray.Create;

  ProcessRecords(Self); // Process all relevant records

  MainOutputObject := TJSONObject.Create;
  MainOutputObject.Add('baseObjects', JsonOutput);

  try
    MainOutputObject.SaveToFile(GlobalOutputFilePath);
    // AddMessage(Format('[SkyGen] Successfully exported data to: %s', [GlobalOutputFilePath])); // Removed
  except
    on E: Exception do
    begin
      // AddMessage(Format('[SkyGen] ERROR: Failed to save JSON to file %s: %s', [GlobalOutputFilePath, E.Message])); // Removed
      Result := 1;
    end;
  end;

  MainOutputObject.Free; // Free the main JSON object

  Result := 0; 
end;

end.
"""
    return pascal_script_content


def generate_and_write_skypatcher_yaml(
    wrapped_organizer: Any,
    json_data: dict,
    target_mod_name: str,
    output_folder_path: Path,
    record_type: str,
    broad_category_swap_enabled: bool,
    search_keywords: list[str]
) -> bool:
    """
    Generates a SkyPatcher YAML file from the xEdit exported JSON data.
    """
    wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Generating SkyPatcher YAML for {target_mod_name}, record type: {record_type}, keywords: {search_keywords}")

    output_folder_path.mkdir(parents=True, exist_ok=True)

    internal_target_mod_name = None
    target_mod_list = wrapped_organizer.modList()
    for mod_internal_name in target_mod_list.allMods():
        if target_mod_list.displayName(mod_internal_name) == target_mod_name:
            mod_path = Path(target_mod_list.modPath(mod_internal_name))
            plugin_files = list(mod_path.glob("*.esp")) + list(mod_path.glob("*.esm")) + list(mod_path.glob("*.esl"))
            if plugin_files:
                found_plugin = None
                for pf in plugin_files:
                    if pf.stem.lower() == mod_internal_name.lower():
                        found_plugin = pf.name
                        break
                if not found_plugin:
                    found_plugin = plugin_files[0].name
                internal_target_mod_name = found_plugin
                break
    
    if not internal_target_mod_name:
        wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Could not find plugin file for target mod '{target_mod_name}'. Cannot generate YAML.")
        wrapped_organizer.dialog_instance.showError("Target Mod Error", f"Could not determine plugin file for target mod '{target_mod_name}'. Please ensure it has a .esp/.esm/.esl file and is active.")
        return False


    yaml_output = []
    base_objects = json_data.get("baseObjects", [])

    all_exported_target_bases_by_formid = wrapped_organizer.dialog_instance.all_exported_target_bases_by_formid
    
    filtered_source_objects = []
    for obj in base_objects:
        if "EditorID" in obj:
            editor_id_lower = obj["EditorID"].lower()
            
            keywords_match = True
            if search_keywords:
                keywords_match = any(k.lower() in editor_id_lower for k in search_keywords)

            if broad_category_swap_enabled:
                if keywords_match:
                    filtered_source_objects.append(obj)
            else:
                if obj.get("Signature") == record_type and keywords_match:
                    filtered_source_objects.append(obj)
        else:
            wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Object missing 'EditorID', skipping: {obj}")

    if not filtered_source_objects:
        wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: No matching objects found for record type '{record_type}' with keywords '{search_keywords}'. No YAML generated for this source.")
        wrapped_organizer.dialog_instance.showWarning("No Matches", f"No matching objects found for record type '{record_type}' with keywords '{', '.join(search_keywords)}' in source mod. No YAML generated.")
        return False

    for source_obj in filtered_source_objects:
        source_form_id = source_obj.get("FormID")
        source_editor_id = source_obj.get("EditorID")
        source_signature = source_obj.get("Signature")
        source_origin_mod = source_obj.get("OriginMod")

        if not source_form_id:
            wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: Skipping object with missing FormID: {source_obj.get('EditorID', 'N/A')}")
            continue

        target_obj = all_exported_target_bases_by_formid.get(source_form_id)

        if target_obj:
            target_editor_id = target_obj.get("EditorID")
            target_signature = target_obj.get("Signature")
            target_origin_mod = target_obj.get("OriginMod")

            yaml_entry = {
                "base": f"{source_form_id}~{source_origin_mod}",
                "match": {},
                "patch": {}
            }
            
            if broad_category_swap_enabled and source_signature != target_signature:
                yaml_entry["match"]["signature"] = target_signature
                if "FullName" in target_obj and target_obj["FullName"] != source_obj.get("FullName"):
                    yaml_entry["match"]["fullName"] = target_obj["FullName"]
                wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Broad swap enabled: Mismatched signature. Source '{source_editor_id}' ({source_signature}) will match target '{target_editor_id}' ({target_signature}).")
            
            if not broad_category_swap_enabled or source_signature == target_signature:
                yaml_entry["match"]["signature"] = source_signature

            if source_editor_id != target_editor_id and not (broad_category_swap_enabled and source_signature != target_signature):
                yaml_entry["match"]["editorID"] = target_editor_id

            if "FullName" in target_obj and target_obj["FullName"] != source_obj.get("FullName") and not (broad_category_swap_enabled and source_signature != target_signature):
                yaml_entry["match"]["fullName"] = target_obj["FullName"]
            
            if "Model" in target_obj and target_obj["Model"] != source_obj.get("Model"):
                yaml_entry["patch"]["MODL"] = target_obj["Model"]

            if "ObjectBounds" in target_obj and target_obj["ObjectBounds"] != source_obj.get("ObjectBounds"):
                yaml_entry["patch"]["OBND"] = target_obj["ObjectBounds"]

            target_keywords = target_obj.get("Keywords", [])
            source_keywords = source_obj.get("Keywords", [])
            
            target_keyword_formids = {kw["FormID"] for kw in target_keywords if "FormID" in kw}
            source_keyword_formids = {kw["FormID"] for kw in source_keywords if "FormID" in kw}

            added_keywords = []
            removed_keywords = []

            for tk_obj in target_keywords:
                if tk_obj.get("FormID") not in source_keyword_formids:
                    added_keywords.append(f"0x{tk_obj['FormID']}~{tk_obj['OriginMod']}")
            
            for sk_obj in source_keywords:
                if sk_obj.get("FormID") not in target_keyword_formids:
                    removed_keywords.append(f"0x{sk_obj['FormID']}~{sk_obj['OriginMod']}")

            if added_keywords or removed_keywords:
                yaml_entry["patch"]["VMAD"] = {}
                if added_keywords:
                    yaml_entry["patch"]["VMAD"]["add"] = added_keywords
                if removed_keywords:
                    yaml_entry["patch"]["VMAD"]["remove"] = removed_keywords

            if "WorldspaceFormID" in target_obj and target_obj["WorldspaceFormID"] != source_obj.get("WorldspaceFormID"):
                yaml_entry["patch"]["WRLD"] = f"0x{target_obj['WorldspaceFormID']}~{target_obj['OriginMod']}"

            if "WorldspaceName" in target_obj and target_obj["WorldspaceName"] != source_obj.get("WorldspaceName"):
                 pass

            if yaml_entry["patch"]:
                yaml_output.append(yaml_entry)
        else:
            wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: INFO: No matching object found in target mod for source FormID: {source_form_id} ({source_editor_id}). Skipping YAML entry for this object.")

    if yaml_output:
        actual_source_mod_display_name = "UnknownSource"
        if filtered_source_objects:
            first_obj_origin_mod_filename = filtered_source_objects[0].get("OriginMod")
            if first_obj_origin_mod_filename:
                mod_list = wrapped_organizer.modList()
                for mod_internal_name in mod_list.allMods():
                    mod_path = Path(mod_list.modPath(mod_internal_name))
                    if (mod_path / first_obj_origin_mod_filename).is_file():
                        actual_source_mod_display_name = mod_list.displayName(mod_internal_name)
                        break
                if actual_source_mod_display_name == "UnknownSource":
                    actual_source_mod_display_name = Path(first_obj_origin_mod_filename).stem.replace(".esm", "").replace(".esp", "").replace(".esl", "")

        keywords_suffix = "_" + "_".join(search_keywords) if search_keywords else ""
        
        sanitized_source_mod_name = re.sub(r'[^\w\-_\. ]', '', actual_source_mod_display_name).strip()
        sanitized_record_type = re.sub(r'[^\w]', '', record_type).strip()

        output_filename = f"SkyPatcher_{sanitized_source_mod_name}_{sanitized_record_type}{keywords_suffix}.yaml"
        output_filepath = output_folder_path / output_filename

        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_output, f, sort_keys=False, default_flow_style=False, Dumper=NoAliasDumper)
            wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Successfully generated SkyPatcher YAML to: {output_filepath}")
            wrapped_organizer.dialog_instance.showInformation("YAML Generated", f"Successfully generated YAML for '{actual_source_mod_display_name}' ({record_type}) to:\n{output_filepath}")
            return True
        except Exception as e:
            wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write SkyPatcher YAML to '{output_filepath}': {e}\n{traceback.format_exc()}")
            wrapped_organizer.dialog_instance.showError("YAML Write Error", f"Failed to write SkyPatcher YAML to '{output_filepath}':\n{e}")
            return False
    else:
        wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: No YAML content generated for record type '{record_type}' from source '{target_mod_name}' and keywords '{search_keywords}'.")
        return False


def generate_bos_ini_files(wrapped_organizer: Any, igpc_data: dict, output_folder_path: Path, dialog_instance: Any) -> bool:
    """
    Generates BOS INI files based on the provided IGPC JSON data.
    """
    wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: Starting BOS INI generation.")

    if not igpc_data:
        wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: IGPC data is empty. Cannot generate BOS INI files.")
        if dialog_instance:
            dialog_instance.showError("BOS INI Error", "IGPC data is empty or malformed. Cannot generate BOS INI files.")
        return False

    bos_output_dir = output_folder_path / "BOS"
    bos_output_dir.mkdir(parents=True, exist_ok=True)
    
    generated_count = 0

    if "baseObjects" not in igpc_data:
        wrapped_organizer.log(MO2_LOG_ERROR, "SkyGen: ERROR: IGPC JSON is missing 'baseObjects' key. Invalid format for BOS INI generation.")
        if dialog_instance:
            dialog_instance.showError("BOS INI Error", "IGPC JSON is in an unexpected format (missing 'baseObjects').")
        return False

    for item in igpc_data["baseObjects"]:
        form_id = item.get("FormID")
        editor_id = item.get("EditorID")
        signature = item.get("Signature")
        origin_mod = item.get("OriginMod")

        if not all([form_id, editor_id, signature, origin_mod]):
            wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: Skipping item due to missing required data: {item}")
            continue

        formatted_form_id = f"0x{form_id}"

        sanitized_editor_id = re.sub(r'[^\w\-. ]', '_', editor_id) if editor_id else form_id
        ini_filename = f"{sanitized_editor_id}.ini"
        ini_filepath = bos_output_dir / ini_filename

        config = configparser.ConfigParser()
        config.optionxform = str

        config[signature] = {
            "FormID": formatted_form_id,
            "EditorID": editor_id,
            "OriginMod": origin_mod
        }

        if "FullName" in item and item["FullName"]:
            config[signature]["FullName"] = item["FullName"]

        if "Model" in item and item["Model"]:
            config[signature]["Model"] = item["Model"]

        if "ObjectBounds" in item and isinstance(item["ObjectBounds"], dict):
            obnd = item["ObjectBounds"]
            config[signature]["ObjectBounds"] = f"{obnd.get('X1',0)},{obnd.get('Y1',0)},{obnd.get('Z1',0)},{obnd.get('X2',0)},{obnd.get('Y2',0)},{obnd.get('Z2',0)}"

        if "Keywords" in item and isinstance(item["Keywords"], list):
            keywords_list = []
            for kw in item["Keywords"]:
                if isinstance(kw, dict) and "FormID" in kw:
                    keywords_list.append(f"0x{kw['FormID']}~{kw.get('OriginMod', 'Unknown.esp')}")
            if keywords_list:
                config[signature]["Keywords"] = ", ".join(keywords_list)

        if "WorldspaceFormID" in item and item["WorldspaceFormID"]:
            config[signature]["WorldspaceFormID"] = f"0x{item['WorldspaceFormID']}"
        if "WorldspaceName" in item and item["WorldspaceName"]:
            config[signature]["WorldspaceName"] = item["WorldspaceName"]

        try:
            with open(ini_filepath, 'w', encoding='utf-8') as f:
                config.write(f)
            wrapped_organizer.log(MO2_LOG_DEBUG, f"SkyGen: Generated BOS INI: {ini_filepath}")
            generated_count += 1
        except Exception as e:
            wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write BOS INI for '{editor_id}' to '{ini_filepath}': {e}\n{traceback.format_exc()}")
            if dialog_instance:
                dialog_instance.showError("BOS INI Write Error", f"Failed to write INI for '{editor_id}':\n{e}")
            continue

    if generated_count > 0:
        wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Successfully generated {generated_count} BOS INI file(s) in: {bos_output_dir}")
        if dialog_instance:
            dialog_instance.showInformation("BOS INI Generation Complete", f"Successfully generated {generated_count} BOS INI file(s) in:\n{bos_output_dir}")
        return True
    else:
        wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: No BOS INI files were generated. This might be due to empty IGPC data or invalid format.")
        if dialog_instance:
            dialog_instance.showWarning("No BOS INI Generated", "No BOS INI files were generated. This might be due to empty IGPC data or invalid format.")
        return False


def safe_launch_xedit(wrapped_organizer: Any, dialog: Any, xedit_path: Path, xedit_mo2_name: str, script_name: str, game_version: str, script_options: dict, debug_logger: Any) -> Optional[Path]:
    """
    Launches xEdit (SSEEdit/FO4Edit/etc.) via QProcess (MO2's full PyQt6 environment),
    writes the Pascal script and INI file, and captures xEdit's output.
    The output JSON and log files are temporarily written to xEdit's 'Edit Scripts' folder
    and then moved to their final destination in MO2's overwrite.
    """
    debug_logger(MO2_LOG_INFO, f"SkyGen: Preparing to launch xEdit ('{xedit_mo2_name}') for script '{script_name}'.")

    xedit_edit_scripts_path = xedit_path.parent / "Edit Scripts"
    temp_script_path = xedit_edit_scripts_path / script_name
    temp_ini_path = xedit_edit_scripts_path / f"{Path(script_name).stem}.ini"
    
    output_json_filename = f"SkyGen_xEdit_Export_{int(time.time())}.json"
    
    mo2_overwrite_path = Path(wrapped_organizer.modsPath()) / "overwrite"
    plugin_temp_path = Path(wrapped_organizer.pluginDataPath()) / "SkyGen" / "temp"

    final_output_folder = mo2_overwrite_path if mo2_overwrite_path.is_dir() and os.access(mo2_overwrite_path, os.W_OK) else plugin_temp_path
    final_output_folder.mkdir(parents=True, exist_ok=True)

    final_export_json_path = final_output_folder / output_json_filename

    temp_script_output_json_path = xedit_edit_scripts_path / f"temp_{output_json_filename}"
    temp_script_log_path = xedit_edit_scripts_path / f"SkyGen_xEdit_Script_Log_{int(time.time())}.txt"

    script_options["OutputFilePath"] = str(temp_script_output_json_path)

    try:
        pascal_script_content = write_pas_script_to_xedit()
        with open(temp_script_path, 'w', encoding='utf-8') as f:
            f.write(pascal_script_content)
        debug_logger(MO2_LOG_DEBUG, f"SkyGen: Pascal script written to: {temp_script_path}")
    except Exception as e:
        dialog.showError("Script Write Error", f"Failed to write Pascal script to '{temp_script_path}': {e}")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write Pascal script: {e}")
        return None

    try:
        ini_content = "[SkyGenOptions]\n"
        for key, value in script_options.items():
            ini_content += f"{key}={value}\n"
        with open(temp_ini_path, 'w', encoding='utf-8') as f:
            f.write(ini_content)
        debug_logger(MO2_LOG_DEBUG, f"SkyGen: INI file written to: {temp_ini_path}")
    except Exception as e:
        dialog.showError("INI Write Error", f"Failed to write INI file to '{temp_ini_path}': {e}")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write INI file: {e}")
        clean_temp_files(temp_script_path, None, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None

    target_plugin_name = script_options.get("TargetPlugin", "")
    if not target_plugin_name:
        dialog.showError("Script Configuration Error", "Pascal script 'TargetPlugin' option is missing. Cannot proceed.")
        debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: Pascal script TargetPlugin option is missing.")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None

    process = QProcess(dialog)
    tool_entry = None
    for exe in wrapped_organizer.getExecutables().values():
        if Path(exe.binary()).resolve() == xedit_path.resolve():
            tool_entry = exe
            break

    if tool_entry:
        mo2_exec_name_to_use = tool_entry.displayName()
        debug_logger(MO2_LOG_INFO, f"SkyGen: Found matching MO2 tool entry: '{mo2_exec_name_to_use}' for path '{xedit_path}'.")
    else:
        mo2_exec_name_to_use = xedit_path.stem
        debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: No registered MO2 tool matched exact path '{xedit_path}'. Attempting launch via filename stem '{mo2_exec_name_to_use}'. VFS may not be active.")

    xedit_args = [
        f"-D:ExportPath=\"{os.path.normpath(str(temp_script_output_json_path))}\"",
        f"-D:TargetPlugin=\"{target_plugin_name}\"",
        f"-D:LogPath=\"{os.path.normpath(str(temp_script_log_path))}\"",
        f"-script:\"{os.path.normpath(str(temp_script_path))}\"",
        "-IKnowWhatImDoing",
        "-NoAutoUpdate",
        "-NoAutoBackup",
        "-exit"
    ]

    # Add game mode argument based on game_version
    game_mode_arg = {
        "SkyrimSE": "-sse",
        "SkyrimVR": "-tes5vr"
    }.get(game_version)
    if game_mode_arg:
        xedit_args.insert(0, game_mode_arg)
    else:
        debug_logger(MO2_LOG_INFO, f"SkyGen: No specific game mode argument for xEdit for game version '{game_version}'. Launching without it.")

    cwd_path = xedit_path.parent / "Edit Scripts"
    
    if not cwd_path.is_dir():
        dialog.showError("xEdit Script Path Error", f"xEdit 'Edit Scripts' directory not found at: {cwd_path}. Cannot launch xEdit correctly.")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit 'Edit Scripts' directory not found: {cwd_path}")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None

    cwd = os.path.normpath(str(cwd_path))

    debug_logger(MO2_LOG_INFO, f"SkyGen: Calling MO2's startApplication for '{mo2_exec_name_to_use}' with arguments: {xedit_args} and CWD: {cwd}")

    try:
        if temp_script_output_json_path.exists():
            try:
                temp_script_output_json_path.unlink()
                debug_logger(MO2_LOG_DEBUG, f"SkyGen: Deleted old temporary JSON export file: {temp_script_output_json_path}")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not delete old temporary JSON export file {temp_script_output_json_path}: {e}. This might cause issues.")
        if temp_script_log_path.exists():
            try:
                temp_script_log_path.unlink()
                debug_logger(MO2_LOG_DEBUG, f"SkyGen: Deleted old temporary log file: {temp_script_log_path}")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not delete old temporary log file {temp_script_log_path}: {e}. This might cause issues.")

        app_handle = wrapped_organizer.startApplication(mo2_exec_name_to_use, xedit_args, str(cwd))

        if app_handle == 0:
            dialog.showError("xEdit Launch Failed", f"Failed to launch '{mo2_exec_name_to_use}' via MO2. Please ensure xEdit is added to MO2's executables with the display name '{mo2_exec_name_to_use}' (e.g., 'SSEEdit' or 'TES5VREdit') and check MO2 logs for more details.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: MO2 startApplication failed to launch xEdit executable '{mo2_exec_name_to_use}'.")
            return False

        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit launched with handle: {app_handle}. Waiting for process termination and output file: {temp_script_output_json_path}")

        if not process.waitForFinished(600000): # 10 minutes timeout in ms
            process.kill()
            dialog.showError("xEdit Timeout", "xEdit process timed out after 10 minutes. It may be stuck or processing a very large load order.")
            debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: xEdit process timed out.")
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
            return None

        stdout_data = process.readAllStandardOutput()
        stderr_data = process.readAllStandardError()
        stdout_str = stdout_data.data().decode('utf-8', errors='replace')
        stderr_str = stderr_data.data().decode('utf-8', errors='replace')

        if stdout_str:
            debug_logger(MO2_LOG_DEBUG, f"SkyGen: xEdit STDOUT:\n{stdout_str}")
        if stderr_str:
            debug_logger(MO2_LOG_ERROR, f"SkyGen: xEdit STDERR:\n{stderr_str}")

        exit_code = process.exitCode()
        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit process finished with exit code: {exit_code}")

        if exit_code != 0:
            dialog.showError("xEdit Error", f"xEdit finished with errors (Exit Code: {exit_code}). Check MO2 logs and SSEScript_log.txt for details.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit process failed with exit code {exit_code}.")
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
            return None
        
        if not temp_script_output_json_path.is_file() or temp_script_output_json_path.stat().st_size == 0:
            dialog.showError("xEdit Output Error", f"xEdit did not produce the expected temporary output file or it is empty: {temp_script_output_json_path}. Check SSEScript_log.txt for xEdit errors.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit temporary output JSON missing or empty: {temp_script_output_json_path}")
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
            return None

        try:
            shutil.move(str(temp_script_output_json_path), str(final_export_json_path))
            debug_logger(MO2_LOG_INFO, f"SkyGen: Moved xEdit JSON output from '{temp_script_output_json_path}' to '{final_export_json_path}'.")
        except Exception as e:
            dialog.showError("File Move Error", f"Failed to move xEdit output JSON from '{temp_script_output_json_path}' to '{final_export_json_path}': {e}. You may need to move it manually.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to move xEdit JSON output: {e}")
            return None
        
        if temp_script_log_path.is_file() and temp_script_log_path.stat().st_size > 0:
            final_export_log_path = final_output_folder / f"SkyGen_xEdit_Script_Log_{Path(temp_script_log_path).stem.split('_')[-1]}.txt"
            try:
                shutil.move(str(temp_script_log_path), str(final_export_log_path))
                debug_logger(MO2_LOG_INFO, f"SkyGen: Moved xEdit script log from '{temp_script_log_path}' to '{final_export_log_path}'.")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to move xEdit script log from '{temp_script_log_path}' to '{final_export_log_path}': {e}.")
        
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger)

        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit successfully completed, output saved to: {final_export_json_path}")
        return final_export_json_path

    except Exception as e:
        debug_logger(MO2_LOG_CRITICAL, f"SkyGen: CRITICAL: Unexpected error launching or running xEdit: {e}\n{traceback.format_exc()}")
        dialog.showError("xEdit Error", f"An unexpected error occurred while trying to run xEdit: {e}. Check MO2 logs for more details.")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None


def clean_temp_files(script_path: Path, ini_path: Optional[Path], log_callback: Any, output_json_temp_path: Optional[Path] = None, script_log_temp_path: Optional[Path] = None):
    """
    Cleans up the temporary Pascal script, its INI file, and optionally the xEdit temporary output JSON and script log.
    These paths are expected to be *temporary* files within the xEdit/Edit Scripts directory.
    """
    files_to_clean = [script_path]
    if ini_path:
        files_to_clean.append(ini_path)
    if output_json_temp_path:
        files_to_clean.append(output_json_temp_path)
    if script_log_temp_path:
        files_to_clean.append(script_log_temp_path)

    for f_path in files_to_clean:
        if f_path and f_path.exists():
            try:
                f_path.unlink()
                log_callback(MO2_LOG_TRACE, f"SkyGen: DEBUG: Deleted temporary file: {f_path}")
            except Exception as e:
                log_callback(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete temporary file '{f_path}': {e}")


# Custom YAML Dumper to prevent aliases
class NoAliasDumper(yaml.Dumper):
    def ignore_aliases(self, data):
        return True


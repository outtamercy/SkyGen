from pathlib import Path
import mobase
import os
import time
# Removed subprocess import
import json
import yaml
import configparser
import re
import traceback
import shutil # Added shutil for file operations
from collections import defaultdict
from typing import Optional, Any
from datetime import datetime # Added datetime import

# MODIFIED: Changed QStringList to QByteArray for PyQt6 compatibility
try:
    from PyQt6.QtCore import QProcess, QByteArray # QProcess for MO2's startApplication, QByteArray for output
    from PyQt6.QtWidgets import QMessageBox # For dialog_instance.showError
except ImportError:
    # Dummy classes for environments without PyQt6
    class QProcess:
        ProcessState = type('ProcessState', (object,), {'NotRunning': 0, 'Starting': 1, 'Running': 2})
        ExitStatus = type('ExitStatus', (object,), {'NormalExit': 0, 'CrashExit': 1})
        def __init__(self, *args, **kwargs): pass
        def setProgram(self, program): pass
        def setArguments(self, args): pass
        def setWorkingDirectory(self, path): pass
        def start(self): pass
        def waitForFinished(self, timeout): return True # Simulate immediate finish for dummy
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

    class DummySignal: # Required for QProcess.connect mocks
        def connect(self, func): pass


# Define a constant for max poll time
MAX_POLL_TIME = 60 # Maximum seconds to wait for xEdit export to complete (increased from 30)

# Import MO2_LOG_* constants from skygen_constants
from .skygen_constants import MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO, MO2_LOG_DEBUG, MO2_LOG_TRACE


# --- Utility Functions (Global helpers) ---

def make_file_logger(log_path: Path):
    """
    Creates a logger function that appends messages to a specified file with timestamps.
    """
    # Ensure directory exists before trying to open the file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log(mo2_log_level: int, message: str): # Adopt MO2 log level signature
        try:
            # Format message with timestamp and level name
            level_name = {
                5: "CRITICAL", 4: "ERROR", 3: "WARNING",
                2: "INFO", 1: "DEBUG", 0: "TRACE"
            }.get(mo2_log_level, "UNKNOWN")
            full_message = f"[{datetime.now().isoformat()}] [{level_name}] {message}"
            
            with log_path.open("a", encoding="utf-8") as f:
                f.write(full_message + "\n")
        except Exception as e:
            # Fallback to console print if file logging fails
            print(f"[SkyGen] CRITICAL ERROR: Failed to write to SkyGen_Debug.log: {e} - Message: {message}")
    return log


def load_json_data(wrapped_organizer: Any, file_path: Path, description: str, dialog_instance: Any) -> dict | None:
    """
    Loads JSON data from a specified file path.
    Requires wrapped_organizer for logging and dialog_instance for showing UI errors.
    """
    if not file_path or not file_path.is_file():
        wrapped_organizer.log(MO2_LOG_WARNING, f"SkyGen: WARNING: {description} file path is invalid or file not found at: {file_path}.")
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Not Found", f"{description} file not found at the specified path: {file_path}.")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Successfully loaded {description} from: {file_path}")
            return data
    except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e: # Added UnicodeDecodeError
        wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Error loading {description} from {file_path}: {e}")
        if dialog_instance: # Only show error if dialog_instance is provided
            dialog_instance.showError("File Read Error", f"Error loading {description} from {file_path}:\n{e}")
        return None


def get_xedit_exe_path(wrapped_organizer: Any, dialog_instance: Any) -> tuple[Path, str] | None:
    """
    Determines the xEdit executable path and its MO2 registered name.
    Prioritizes official xEdit names used by MO2, with case-insensitive matching.
    """
    # Convert all target names to lowercase for robust comparison
    xedit_names_lower = {"sseedit", "tes5edit", "fo4edit", "fnvedit", "oblivionedit", "xedit"}
    executables = wrapped_organizer.getExecutables() # Dictionary of MO2 executables

    # Prioritize executables whose display name or binary matches common xEdit names
    for exe_name, exe_info in executables.items():
        exe_path = Path(exe_info.binary())
        
        # Log the display name and binary stem for debugging purposes
        # debug_logger = wrapped_organizer.log
        # debug_logger(MO2_LOG_TRACE, f"SkyGen: DEBUG: Checking executable: DisplayName='{exe_info.displayName()}', BinaryStem='{exe_path.stem}'")

        # Check if the display name (lowercased) or the binary name stem (lowercased) matches an xEdit name
        if exe_info.displayName().lower() in xedit_names_lower or exe_path.stem.lower() in xedit_names_lower:
            wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Found xEdit executable: '{exe_info.displayName()}' at '{exe_path}' (MO2 Name: '{exe_name}')")
            return exe_path, exe_name # Return path and the internal MO2 name

    # --- ADD THE FALLBACK LOGIC HERE (ChatGPT's suggestion) ---
    wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: xEdit not found in MO2's registered executables. Attempting Wabbajack-style fallback.")
    
    # Calculate potential fallback path relative to MO2's base directory (common for Wabbajack)
    # organizer.profilePath() is usually <MO2_Base>/profiles/<ProfileName>
    # .parent.parent moves up two levels to <MO2_Base>
    mo2_base_path = Path(wrapped_organizer.profilePath()).parent.parent
    fallback_path = mo2_base_path / "tools" / "SSEEdit" / "SSEEdit.exe"

    if fallback_path.is_file():
        wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Found xEdit via Wabbajack-style fallback: {fallback_path}")
        return fallback_path, "SSEEdit" # Use a generic MO2 name for this fallback detection
    # --- END FALLBACK LOGIC ---

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


# MODIFIED: Replaced entire safe_launch_xedit function with the new, robust version
def safe_launch_xedit(organizer: mobase.IOrganizer, dialog: Any, xedit_path: Path, xedit_mo2_name: str, script_name: str, game_mode_flag: str, game_version: str, script_options: dict, debug_logger: Any) -> Optional[Path]:
    """
    Launches xEdit (SSEEdit/FO4Edit/etc.) via QProcess (MO2's full PyQt6 environment),
    writes the Pascal script and INI file, and captures xEdit's output.
    """
    debug_logger(MO2_LOG_INFO, f"SkyGen: Preparing to launch xEdit ('{xedit_mo2_name}') for script '{script_name}'.")

    # Define temporary paths for script and INI within xEdit's Edit Scripts folder
    xedit_edit_scripts_path = xedit_path.parent / "Edit Scripts"
    temp_script_path = xedit_edit_scripts_path / script_name
    temp_ini_path = xedit_edit_scripts_path / f"{Path(script_name).stem}.ini"
    
    # Define the output JSON path (in MO2's overwrite or a dedicated plugin temp folder)
    output_json_filename = f"SkyGen_xEdit_Export_{int(time.time())}.json"
    
    # Prefer MO2's overwrite, but fall back to a plugin-specific temp path if overwrite not writable
    mo2_overwrite_path = Path(organizer.modsPath()) / "overwrite"
    plugin_temp_path = Path(organizer.pluginDataPath()) / "SkyGen" / "temp"

    output_folder = mo2_overwrite_path if mo2_overwrite_path.is_dir() and os.access(mo2_overwrite_path, os.W_OK) else plugin_temp_path
    output_folder.mkdir(parents=True, exist_ok=True) # Ensure temp folder exists

    export_json_path = output_folder / output_json_filename
    script_options["OutputFilePath"] = str(export_json_path)

    # Define path for xEdit's internal log file for the script
    export_log_path = output_folder / f"SkyGen_xEdit_Script_Log_{int(time.time())}.txt"


    # 1. Write the Pascal script content to the Edit Scripts folder
    try:
        pascal_script_content = write_pas_script_to_xedit() # Get the embedded script content (ensure this function is defined in this file!)
        with open(temp_script_path, 'w', encoding='utf-8') as f:
            f.write(pascal_script_content)
        debug_logger(MO2_LOG_DEBUG, f"SkyGen: Pascal script written to: {temp_script_path}")
    except Exception as e:
        dialog.showError("Script Write Error", f"Failed to write Pascal script to '{temp_script_path}': {e}")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write Pascal script: {e}")
        return None

    # 2. Generate and write the INI file for the script
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
        # Clean up script if INI fails
        clean_temp_files(temp_script_path, None, debug_logger, export_json_path, export_log_path) # Added log path
        return None

    # Determine the target plugin name from script_options (e.g., "Skyrim.esm", "EnhancedLandscapes.esp")
    target_plugin_name = script_options.get("TargetPlugin", "")
    if not target_plugin_name:
        dialog.showError("Script Configuration Error", "Pascal script 'TargetPlugin' option is missing. Cannot proceed.")
        debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: Pascal script TargetPlugin option is missing.")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, export_json_path, export_log_path) # Added log path
        return None


    # Use QProcess to launch xEdit for full control and output capture
    process = QProcess(dialog) # Pass dialog as parent for QProcess
    # --- START REPLACEMENT FOR MO2 EXECUTABLE LOOKUP ---
    tool_entry = None
    for exe in organizer.getExecutables().values():
        if Path(exe.binary()).resolve() == xedit_path.resolve():
            tool_entry = exe
            break

    if tool_entry:
        mo2_exec_name_to_use = tool_entry.displayName()
        debug_logger(MO2_LOG_INFO, f"SkyGen: Found matching MO2 tool entry: '{mo2_exec_name_to_use}' for path '{xedit_path}'.")
    else:
        # Fallback if no matching MO2 tool entry found by path (shouldn't happen if get_xedit_exe_path is robust)
        mo2_exec_name_to_use = xedit_path.stem # Use filename stem as a last resort, but expect VFS issues
        debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: No registered MO2 tool matched exact path '{xedit_path}'. Attempting launch via filename stem '{mo2_exec_name_to_use}'. VFS may not be active.")
    # --- END REPLACEMENT FOR MO2 EXECUTABLE LOOKUP ---

    # Construct xEdit arguments as a native Python list (MO2's PyQt6 supports this)
    xedit_args = [
        # Arguments for the Pascal script
        # Converted to Windows format using os.path.normpath(str())
        f"-D:ExportPath=\"{os.path.normpath(str(export_json_path))}\"",
        f"-D:TargetPlugin=\"{target_plugin_name}\"",
        f"-D:LogPath=\"{os.path.normpath(str(export_log_path))}\"",

        # Path to the Pascal script to execute (absolute path)
        # Converted to Windows format using os.path.normpath(str())
        f"-script:\"{os.path.normpath(str(temp_script_path))}\"", # Ensure this uses temp_script_path

        "-IKnowWhatImDoing",
        "-NoAutoUpdate",
        "-NoAutoBackup",
        "-exit" # This is important for headless operation
    ]

    # Add game mode argument
    game_mode_arg = {
        "SkyrimSE": "-sse",
        "SkyrimVR": "-tes5vr"
    }.get(game_version) # Use the new game_version parameter
    if game_mode_arg:
        xedit_args.insert(0, game_mode_arg)
    else:
        debug_logger(MO2_LOG_INFO, f"SkyGen: No specific game mode argument for xEdit for game version '{game_version}'. Launching without it.")

    # Set the current working directory for xEdit to its "Edit Scripts" folder
    cwd_path = xedit_path.parent / "Edit Scripts"
    
    if not cwd_path.is_dir():
        dialog.showError("xEdit Script Path Error", f"xEdit 'Edit Scripts' directory not found at: {cwd_path}. Cannot launch xEdit correctly.")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit 'Edit Scripts' directory not found: {cwd_path}")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, export_json_path, export_log_path) # Added log path
        return None

    # Ensure cwd is normalized to native path separators and converted to string for startApplication
    cwd = os.path.normpath(str(cwd_path))

    debug_logger(MO2_LOG_INFO, f"SkyGen: Calling MO2's startApplication for '{mo2_exec_name_to_use}' with arguments: {xedit_args} and CWD: {cwd}")

    try:
        # Ensure output files do not exist from a previous failed run (with same timestamp, though unlikely)
        if export_json_path.exists():
            try:
                export_json_path.unlink()
                debug_logger(MO2_LOG_DEBUG, f"SkyGen: Deleted old JSON export file: {export_json_path}")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not delete old JSON export file {export_json_path}: {e}. This might cause issues.")
        if export_log_path.exists():
            try:
                export_log_path.unlink()
                debug_logger(MO2_LOG_DEBUG, f"SkyGen: Deleted old log file: {export_log_path}")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not delete old log file {export_log_path}: {e}. This might cause issues.")

        # Launch xEdit via MO2's built-in application launcher to ensure VFS is correctly applied
        app_handle = organizer.startApplication(mo2_exec_name_to_use, xedit_args, str(cwd))

        if app_handle == 0:
            dialog.showError("xEdit Launch Failed", f"Failed to launch '{mo2_exec_name_to_use}' via MO2. Please ensure xEdit is added to MO2's executables with the display name '{mo2_exec_name_to_use}' (e.g., 'SSEEdit' or 'TES5VREdit') and check MO2 logs for more details.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: MO2 startApplication failed to launch xEdit executable '{mo2_exec_name_to_use}'.")
            return False

        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit launched with handle: {app_handle}. Waiting for process termination and output file: {export_json_path}")

        # Wait for the xEdit process to finish (blocking call, but QProcess handles events)
        if not process.waitForFinished(600000): # 10 minutes timeout in ms
            process.kill()
            dialog.showError("xEdit Timeout", "xEdit process timed out after 10 minutes. It may be stuck or processing a very large load order.")
            debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: xEdit process timed out.")
            # Ensure cleanup even on timeout
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, export_json_path, export_log_path) # Added output_json_path, export_log_path
            return None

        # Get final output (important for debugging xEdit's internal operations)
        # Note: QProcess.readAllStandardOutput/Error return QByteArray, need to decode
        stdout_data = process.readAllStandardOutput()
        stderr_data = process.readAllStandardError()
        stdout_str = stdout_data.data().decode('utf-8', errors='replace')
        stderr_str = stderr_data.data().decode('utf-8', errors='replace')

        if stdout_str:
            debug_logger(MO2_LOG_DEBUG, f"SkyGen: xEdit STDOUT:\n{stdout_str}") # Changed to DEBUG
        if stderr_str:
            debug_logger(MO2_LOG_ERROR, f"SkyGen: xEdit STDERR:\n{stderr_str}")

        exit_code = process.exitCode()
        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit process finished with exit code: {exit_code}")

        if exit_code != 0:
            dialog.showError("xEdit Error", f"xEdit finished with errors (Exit Code: {exit_code}). Check MO2 logs and SSEScript_log.txt for details.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit process failed with exit code {exit_code}.")
            # Ensure cleanup on error
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, export_json_path, export_log_path) # Added log path
            return None
        
        # Finally block ensures cleanup even if errors occur (moved from a separate finally block)
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, export_json_path, export_log_path) # Added log path
        # Verify output JSON file exists and is not empty
        if not export_json_path.is_file() or export_json_path.stat().st_size == 0:
            dialog.showError("xEdit Output Error", f"xEdit did not produce the expected output file or it is empty: {export_json_path}. Check SSEScript_log.txt for xEdit errors.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit output JSON missing or empty: {export_json_path}")
            # Ensure cleanup on missing/empty output
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, export_json_path, export_log_path) # Clean up output JSON too if it's empty/missing, Added log path
            return None
        
        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit successfully completed, output saved to: {export_json_path}")
        return export_json_path

    except Exception as e:
        debug_logger(MO2_LOG_CRITICAL, f"SkyGen: CRITICAL: Unexpected error launching or running xEdit: {e}\n{traceback.format_exc()}")
        dialog.showError("xEdit Error", f"An unexpected error occurred while trying to run xEdit: {e}. Check MO2 logs for more details.")
        return False


def generate_and_write_skypatcher_yaml(
    wrapped_organizer: Any,
    json_data: dict, # The loaded JSON data from xEdit, including "baseObjects"
    target_mod_name: str, # Display name of the target mod (e.g., "DynDOLOD Output")
    output_folder_path: Path,
    record_type: str,
    broad_category_swap_enabled: bool,
    search_keywords: Optional[list[str]] = None, # Changed from str to list[str], made optional
    dialog_instance: Any = None # Optional dialog instance for showing errors
) -> bool:
    """
    Generates SkyPatcher YAML configuration files from xEdit-exported JSON data.
    """
    if search_keywords is None:
        search_keywords = [] # Initialize as empty list if None

    log_callback = wrapped_organizer.log # Get log function from wrapped_organizer
    log_callback(MO2_LOG_INFO, f"SkyGen: Starting YAML generation for category '{record_type}' with target '{target_mod_name}'.")

    base_objects = json_data.get("baseObjects", [])
    if not base_objects:
        log_callback(MO2_LOG_WARNING, f"SkyGen: No base objects found in JSON data for category '{record_type}'. Skipping YAML generation.")
        if dialog_instance:
            dialog_instance.showWarning("No Data", f"No relevant data exported from xEdit for category '{record_type}'. No YAML file will be generated.")
        return False

    yaml_configs_dir = output_folder_path / "SkyPatcher" / "Configs"
    yaml_configs_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists

    # Retrieve internal plugin name for target mod
    # Use the wrapped_organizer to access original organizer methods
    target_mod_internal_name = dialog_instance._get_internal_mod_name_from_display_name(target_mod_name)
    if not target_mod_internal_name:
        log_callback(MO2_LOG_WARNING, f"SkyGen: ERROR: Could not determine internal name for target mod '{target_mod_name}'. Aborting YAML generation.")
        if dialog_instance:
            dialog_instance.showError("Mod Resolution Error", f"Could not determine internal plugin name for target mod '{target_mod_name}'. Please ensure it is active and has a primary plugin.")
        return False
    
    target_plugin_filename = dialog_instance._get_plugin_name_from_mod_name(target_mod_name, target_mod_internal_name)
    if not target_plugin_filename:
        log_callback(MO2_LOG_WARNING, f"SkyGen: ERROR: Could not determine plugin filename for target mod '{target_mod_name}'. Aborting YAML generation.")
        if dialog_instance:
            dialog_instance.showError("Mod Resolution Error", f"Could not determine plugin filename for target mod '{target_mod_name}'. Please ensure it is active and has a primary plugin.")
        return False


    generated_count = 0
    
    # Group by OriginMod for better file organization
    grouped_by_origin_mod = defaultdict(list)
    for obj in base_objects:
        origin_mod = obj.get("OriginMod")
        if origin_mod:
            grouped_by_origin_mod[origin_mod].append(obj)

    # Load all objects from the target mod's exported JSON (already done in _generate_skypatcher_yaml_internal)
    # The `all_exported_target_bases_by_formid` is already prepared and passed implicitly through dialog_instance.

    for origin_mod_filename, objects_from_mod in grouped_by_origin_mod.items():
        # Sanitize origin_mod_filename for use in YAML filename
        sanitized_origin_mod_name = origin_mod_filename.replace('.esp', '').replace('.esm', '').replace('.esl', '')
        
        # Construct the file name for the YAML patch
        # Format: SkyPatcher_[RecordType]_[SourceMod].yaml
        yaml_filename = f"SkyPatcher_{record_type}_{sanitized_origin_mod_name}.yaml"
        yaml_filepath = yaml_configs_dir / yaml_filename

        yaml_content = {
            "name": f"Patch for {record_type} from {sanitized_origin_mod_name}",
            "description": f"Auto-generated SkyPatcher configuration for {record_type} records from {origin_mod_filename} to match {target_mod_name}.",
            "patches": []
        }

        patch_added = False
        for obj in objects_from_mod:
            form_id = obj.get("FormID")
            signature = obj.get("Signature")
            editor_id = obj.get("EditorID", "").strip()
            
            # Skip if FormID or Signature is missing
            if not form_id or not signature:
                log_callback(MO2_LOG_WARNING, f"SkyGen: WARNING: Skipping object due to missing FormID or Signature: {obj}")
                continue

            # Check for keyword match if keywords are specified and broad swap is NOT enabled
            if search_keywords and not broad_category_swap_enabled:
                # search_keywords is already a list of strings
                if not any(kw.lower() in editor_id.lower() for kw in search_keywords):
                    log_callback(MO2_LOG_TRACE, f"SkyGen: DEBUG: Skipping {editor_id} due to keyword mismatch (not broad swap).")
                    continue # Skip if no keyword match

            # If broad_category_swap_enabled, check for keyword match (if keywords are present)
            # This logic is handled by the xEdit script itself; here we just use the data.

            # Determine the target record's FormID based on BroadCategorySwap
            target_form_id_in_target_mod = ""
            if broad_category_swap_enabled:
                # In broad category swap, we try to find a target record with the same EditorID
                # from the original target mod export, regardless of its original signature.
                # This requires iterating through all target bases to find a matching EditorID.
                found_target_by_editor_id = None
                for target_base_obj in dialog_instance.all_exported_target_bases_by_formid.values():
                    if target_base_obj.get("EditorID", "").strip() == editor_id:
                        found_target_by_editor_id = target_base_obj
                        break
                
                if found_target_by_editor_id:
                    target_form_id_in_target_mod = found_target_by_editor_id["FormID"]
                    log_callback(MO2_LOG_TRACE, f"SkyGen: DEBUG: Broad Swap: Matched source '{editor_id}' (FormID: {form_id}) to target '{target_form_id_in_target_mod}' in '{target_plugin_filename}'.")
                else:
                    log_callback(MO2_LOG_TRACE, f"SkyGen: DEBUG: Broad Swap: No matching EditorID '{editor_id}' found in target mod. Skipping '{editor_id}' (FormID: {form_id}).")
                    continue # Skip if no matching EditorID found in target mod
            else:
                # Normal mode: use original FormID
                target_form_id_in_target_mod = form_id


            patch_entry = {
                "source": {
                    "plugin": origin_mod_filename,
                    "formid": f"0x{form_id}" # SkyPatcher expects 0x prefix
                },
                "target": {
                    "plugin": target_plugin_filename,
                    "formid": f"0x{target_form_id_in_target_mod}" # SkyPatcher expects 0x prefix
                }
            }
            yaml_content["patches"].append(patch_entry)
            patch_added = True

        if patch_added:
            try:
                with open(yaml_filepath, 'w', encoding='utf-8') as f:
                    yaml.dump(yaml_content, f, sort_keys=False, default_flow_style=False, indent=2, Dumper=NoAliasDumper)
                log_callback(MO2_LOG_INFO, f"SkyGen: Generated YAML for '{origin_mod_filename}' at: {yaml_filepath}")
                generated_count += 1
            except Exception as e:
                log_callback(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write YAML for '{origin_mod_filename}' to {yaml_filepath}: {e}")
                if dialog_instance:
                    dialog_instance.showError("YAML Write Error", f"Failed to write YAML for '{origin_mod_filename}':\n{e}")
        else:
            log_callback(MO2_LOG_WARNING, f"SkyGen: No patches generated for '{origin_mod_filename}'. Skipping YAML file creation.")

    if generated_count > 0:
        log_callback(MO2_LOG_INFO, f"SkyGen: Successfully generated {generated_count} SkyPatcher YAML file(s).")
        if dialog_instance:
            dialog_instance.showInformation("SkyPatcher YAML Generation Complete", f"Successfully generated {generated_count} SkyPatcher YAML file(s) in:\n{yaml_configs_dir}")
        return True
    else:
        log_callback(MO2_LOG_INFO, "SkyGen: No SkyPatcher YAML files were generated.")
        if dialog_instance:
            dialog_instance.showWarning("No YAML Generated", "No SkyPatcher YAML files were generated. This might be due to no matching records or issues during xEdit export.")
        return False


def generate_bos_ini_files(wrapped_organizer: Any, igpc_data: dict, output_folder_path: Path, dialog_instance: Any) -> bool:
    """
    Generates BOS INI files from IGPC JSON data.
    """
    log_callback = wrapped_organizer.log
    log_callback(MO2_LOG_INFO, "SkyGen: Starting BOS INI generation.")

    if "pluginObjectMapping" not in igpc_data:
        log_callback(MO2_LOG_WARNING, "SkyGen: ERROR: Invalid IGPC JSON format. Missing 'pluginObjectMapping'.")
        if dialog_instance:
            dialog_instance.showError("Invalid IGPC JSON", "The provided IGPC JSON file is missing the expected 'pluginObjectMapping' section.")
        return False

    bos_output_dir = output_folder_path / "BOS"
    bos_output_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists

    generated_count = 0
    for plugin_name, objects in igpc_data["pluginObjectMapping"].items():
        ini_content = ["[Patches]", ""] # Header for the INI file
        
        for obj_data in objects:
            form_id = obj_data.get("formId")
            if form_id:
                # Remove "0x" prefix if present, as BOS doesn't expect it in the patch section
                cleaned_form_id = form_id.replace("0x", "")
                ini_content.append(f"{cleaned_form_id}")
            else:
                log_callback(MO2_LOG_WARNING, f"SkyGen: WARNING: Skipping object in '{plugin_name}' due to missing 'formId': {obj_data}")
        
        if len(ini_content) > 2: # Check if any form IDs were added (beyond the header)
            ini_file_path = bos_output_dir / f"BOS_{plugin_name}.ini"
            try:
                with open(ini_file_path, 'w', encoding='utf-8') as f:
                    f.write("\n".join(ini_content))
                wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Generated BOS INI for '{plugin_name}' at: {ini_file_path}")
                generated_count += 1
            except Exception as e:
                dialog_instance.showError("BOS INI Write Error", f"Failed to write BOS INI for '{plugin_name}': {e}")
                wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write BOS INI for {plugin_name}: {e}")
        else:
            log_callback(MO2_LOG_WARNING, f"SkyGen: No valid object IDs found for '{plugin_name}'. Skipping BOS INI file creation.")

    if generated_count > 0:
        wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Successfully generated {generated_count} BOS INI file(s).")
        if dialog_instance:
            dialog_instance.showInformation("BOS INI Generation Complete", f"Successfully generated {generated_count} BOS INI file(s) in:\n{bos_output_dir}")
        return True
    else:
        wrapped_organizer.log(MO2_LOG_INFO, "SkyGen: No BOS INI files were generated.")
        if dialog_instance:
            dialog_instance.showWarning("No BOS INI Generated", "No BOS INI files were generated. This might be due to empty IGPC data or invalid format.")
        return False


def clean_temp_files(script_path: Path, ini_path: Optional[Path], log_callback: Any, output_json_path: Optional[Path] = None, script_log_path: Optional[Path] = None): # Added script_log_path
    """
    Cleans up the temporary Pascal script, its INI file, and optionally the xEdit output JSON and script log.
    ini_path and script_log_path are now Optional as they might not be created in error scenarios.
    """
    files_to_clean = [script_path]
    if ini_path: # Only add if it's not None
        files_to_clean.append(ini_path)
    if output_json_path:
        files_to_clean.append(output_json_path)
    if script_log_path: # Added script log path
        files_to_clean.append(script_log_path)


    for f_path in files_to_clean:
        if f_path and f_path.exists(): # Added check for f_path not being None
            try:
                f_path.unlink()
                log_callback(MO2_LOG_TRACE, f"SkyGen: DEBUG: Deleted temporary file: {f_path}")
            except Exception as e:
                log_callback(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to delete temporary file '{f_path}': {e}")


# Custom YAML Dumper to prevent aliases
class NoAliasDumper(yaml.Dumper):
    def ignore_aliases(self, data):
        return True


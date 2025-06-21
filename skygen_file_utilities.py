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
    # wrapped_organizer.profilePath() is usually <MO2_Base>/profiles/<ProfileName>
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


def safe_launch_xedit(wrapped_organizer: Any, dialog: Any, xedit_path: Path, xedit_mo2_name: str, script_name: str, game_mode_flag: str, game_version: str, script_options: dict, debug_logger: Any) -> Optional[Path]:
    """
    Launches xEdit (SSEEdit/FO4Edit/etc.) via QProcess (MO2's full PyQt6 environment),
    writes the Pascal script and INI file, and captures xEdit's output.
    The output JSON and log files are temporarily written to xEdit's 'Edit Scripts' folder
    and then moved to their final destination in MO2's overwrite.
    """
    debug_logger(MO2_LOG_INFO, f"SkyGen: Preparing to launch xEdit ('{xedit_mo2_name}') for script '{script_name}'.")

    # Define temporary paths for script and INI within xEdit's Edit Scripts folder
    xedit_edit_scripts_path = xedit_path.parent / "Edit Scripts"
    temp_script_path = xedit_edit_scripts_path / script_name
    temp_ini_path = xedit_edit_scripts_path / f"{Path(script_name).stem}.ini"
    
    # Define the final output JSON path (in MO2's overwrite or a dedicated plugin temp folder)
    # This path is where the file will *end up* after successful processing.
    output_json_filename = f"SkyGen_xEdit_Export_{int(time.time())}.json"
    
    # Prefer MO2's overwrite, but fall back to a plugin-specific temp path if overwrite not writable
    mo2_overwrite_path = Path(wrapped_organizer.modsPath()) / "overwrite"
    plugin_temp_path = Path(wrapped_organizer.pluginDataPath()) / "SkyGen" / "temp"

    final_output_folder = mo2_overwrite_path if mo2_overwrite_path.is_dir() and os.access(mo2_overwrite_path, os.W_OK) else plugin_temp_path
    final_output_folder.mkdir(parents=True, exist_ok=True) # Ensure temp folder exists

    final_export_json_path = final_output_folder / output_json_filename

    # Define the temporary output JSON and log paths *within xEdit's Edit Scripts folder*
    # This is what the Pascal script will directly write to.
    temp_script_output_json_path = xedit_edit_scripts_path / f"temp_{output_json_filename}"
    temp_script_log_path = xedit_edit_scripts_path / f"SkyGen_xEdit_Script_Log_{int(time.time())}.txt"

    # Set script options for the Pascal script to write to the temporary paths
    script_options["OutputFilePath"] = str(temp_script_output_json_path)
    # The Pascal script implicitly writes its log to temp_script_log_path via LogPath parameter from INI

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
        clean_temp_files(temp_script_path, None, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None

    # Determine the target plugin name from script_options (e.g., "Skyrim.esm", "EnhancedLandscapes.esp")
    target_plugin_name = script_options.get("TargetPlugin", "")
    if not target_plugin_name:
        dialog.showError("Script Configuration Error", "Pascal script 'TargetPlugin' option is missing. Cannot proceed.")
        debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: Pascal script TargetPlugin option is missing.")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None


    # Use QProcess to launch xEdit for full control and output capture
    process = QProcess(dialog) # Pass dialog as parent for QProcess
    # --- START REPLACEMENT FOR MO2 EXECUTABLE LOOKUP ---
    tool_entry = None
    # Now using wrapped_organizer to get executables
    for exe in wrapped_organizer.getExecutables().values():
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
        # Pass the *temporary* output paths to xEdit via -D: arguments.
        # The Pascal script will then read these from its INI.
        f"-D:ExportPath=\"{os.path.normpath(str(temp_script_output_json_path))}\"", # Pascal script gets this from INI
        f"-D:TargetPlugin=\"{target_plugin_name}\"", # Pascal script gets this from INI
        f"-D:LogPath=\"{os.path.normpath(str(temp_script_log_path))}\"", # Pascal script gets this from INI

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
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None

    # Ensure cwd is normalized to native path separators and converted to string for startApplication
    cwd = os.path.normpath(str(cwd_path))

    debug_logger(MO2_LOG_INFO, f"SkyGen: Calling MO2's startApplication for '{mo2_exec_name_to_use}' with arguments: {xedit_args} and CWD: {cwd}")

    try:
        # Ensure temporary output files do not exist from a previous failed run (with same timestamp, though unlikely)
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

        # Launch xEdit via MO2's built-in application launcher to ensure VFS is correctly applied
        app_handle = wrapped_organizer.startApplication(mo2_exec_name_to_use, xedit_args, str(cwd))

        if app_handle == 0:
            dialog.showError("xEdit Launch Failed", f"Failed to launch '{mo2_exec_name_to_use}' via MO2. Please ensure xEdit is added to MO2's executables with the display name '{mo2_exec_name_to_use}' (e.g., 'SSEEdit' or 'TES5VREdit') and check MO2 logs for more details.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: MO2 startApplication failed to launch xEdit executable '{mo2_exec_name_to_use}'.")
            return False

        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit launched with handle: {app_handle}. Waiting for process termination and output file: {temp_script_output_json_path}")

        # Wait for the xEdit process to finish (blocking call, but QProcess handles events)
        if not process.waitForFinished(600000): # 10 minutes timeout in ms
            process.kill()
            dialog.showError("xEdit Timeout", "xEdit process timed out after 10 minutes. It may be stuck or processing a very large load order.")
            debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: xEdit process timed out.")
            # Ensure cleanup even on timeout
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
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
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
            return None
        
        # Verify temporary output JSON file exists and is not empty before moving
        if not temp_script_output_json_path.is_file() or temp_script_output_json_path.stat().st_size == 0:
            dialog.showError("xEdit Output Error", f"xEdit did not produce the expected temporary output file or it is empty: {temp_script_output_json_path}. Check SSEScript_log.txt for xEdit errors.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit temporary output JSON missing or empty: {temp_script_output_json_path}")
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
            return None

        # If successful, move temporary files to their final destination
        try:
            shutil.move(str(temp_script_output_json_path), str(final_export_json_path))
            debug_logger(MO2_LOG_INFO, f"SkyGen: Moved xEdit JSON output from '{temp_script_output_json_path}' to '{final_export_json_path}'.")
        except Exception as e:
            dialog.showError("File Move Error", f"Failed to move xEdit output JSON from '{temp_script_output_json_path}' to '{final_export_json_path}': {e}. You may need to move it manually.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to move xEdit JSON output: {e}")
            # Do not clean the temporary file if move failed, so user can manually retrieve it.
            return None
        
        # Move temporary log file if it exists and has content
        if temp_script_log_path.is_file() and temp_script_log_path.stat().st_size > 0:
            # Create a unique name for the final log file based on timestamp
            final_export_log_path = final_output_folder / f"SkyGen_xEdit_Script_Log_{Path(temp_script_log_path).stem.split('_')[-1]}.txt"
            try:
                shutil.move(str(temp_script_log_path), str(final_export_log_path))
                debug_logger(MO2_LOG_INFO, f"SkyGen: Moved xEdit script log from '{temp_script_log_path}' to '{final_export_log_path}'.")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Failed to move xEdit script log from '{temp_script_log_path}' to '{final_export_log_path}': {e}.")
        
        # Clean up temporary script and INI files (the temporary JSON/log are now moved)
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger) # Only script and INI remain in temp location

        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit successfully completed, output saved to: {final_export_json_path}")
        return final_export_json_path

    except Exception as e:
        debug_logger(MO2_LOG_CRITICAL, f"SkyGen: CRITICAL: Unexpected error launching or running xEdit: {e}\n{traceback.format_exc()}")
        dialog.showError("xEdit Error", f"An unexpected error occurred while trying to run xEdit: {e}. Check MO2 logs for more details.")
        # Ensure temporary files are cleaned up on unexpected crash
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path) # Pass all temporary files for cleanup
        return None


def clean_temp_files(script_path: Path, ini_path: Optional[Path], log_callback: Any, output_json_temp_path: Optional[Path] = None, script_log_temp_path: Optional[Path] = None):
    """
    Cleans up the temporary Pascal script, its INI file, and optionally the xEdit temporary output JSON and script log.
    These paths are expected to be *temporary* files within the xEdit/Edit Scripts directory.
    """
    files_to_clean = [script_path]
    if ini_path: # Only add if it's not None
        files_to_clean.append(ini_path)
    if output_json_temp_path: # Renamed parameter for clarity
        files_to_clean.append(output_json_temp_path)
    if script_log_temp_path: # Renamed parameter for clarity
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


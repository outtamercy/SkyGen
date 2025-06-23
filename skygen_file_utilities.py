import json
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Import MO2_LOG_* constants
from .skygen_constants import (
    MO2_LOG_CRITICAL, MO2_LOG_ERROR, MO2_LOG_WARNING, MO2_LOG_INFO,
    MO2_LOG_DEBUG, MO2_LOG_TRACE
)

# Define a constant for maximum polling time (e.g., 5 minutes = 300 seconds)
MAX_POLL_TIME = 300

def load_json_data(wrapped_organizer: Any, file_path: Path, description: str, dialog_instance: Any) -> Optional[dict]:
    """
    Loads JSON data from a specified file path.
    Logs errors and displays a message box if loading fails.
    """
    wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Loading {description} from: {file_path}")
    if not file_path.is_file():
        dialog_instance.showError("File Not Found", f"{description} not found at: {file_path}")
        wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: {description} file not found: {file_path}")
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        wrapped_organizer.log(MO2_LOG_INFO, f"SkyGen: Successfully loaded {description}.")
        return data
    except json.JSONDecodeError as e:
        dialog_instance.showError("JSON Error", f"Failed to parse {description} from '{file_path}': Invalid JSON format.\nError: {e}")
        wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: JSON decoding failed for {file_path}: {e}")
        return None
    except Exception as e:
        dialog_instance.showError("File Read Error", f"Failed to read {description} from '{file_path}': {e}")
        wrapped_organizer.log(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to read {file_path}: {e}")
        return None

def write_pas_script_to_xedit() -> str:
    """
    Generates the Pascal script content for xEdit.
    This script reads options from an INI file and exports plugin data to JSON.
    """
    # This content should match the Pascal script you want xEdit to run.
    # It must be able to read an INI file for its parameters.
    # For now, this is a placeholder. You'll need to fill this with your actual Pascal script.
    # The script should be designed to read an INI with sections like [SkyGenOptions]
    # and parameters like TargetPlugin, TargetCategory, OutputFilePath, Keywords, BroadCategorySwap.
    
    pascal_script = """
unit ExportPluginData;

uses
  SysUtils, Classes, m_INI, m_JSON, m_NFE;

function Initialize: Integer;
begin
  Result := 0; // Success
end;

function Finalize: Integer;
begin
  Result := 0; // Success
end;

function Process(aEditorID: string): Integer;
var
  ConfigFile: TIniFile;
  TargetPlugin: string;
  TargetCategory: string;
  KeywordsStr: string;
  KeywordsList: TStringList;
  BroadCategorySwap: Boolean;
  OutputFilePath: string;
  ReportFile: TextFile;
  i: Integer;
  CurElement: IInterface;
  BaseObjectsArray: TJSONArray;
  RecordData: TJSONObject;
  KeywordFound: Boolean;
  BaseObject: IInterface;
  ReferenceElement: IInterface;
  FormID: string;
  EditorID: string;
  Name: string;
  Path: string;
  FileFormID: string; // Used to identify the originating plugin
  IsOverridden: Boolean; // New: Check if record is overridden
begin
  Result := 0; // Default to success
  KeywordsList := TStringList.Create;
  BaseObjectsArray := TJSONArray.Create;

  try
    // Load configuration from INI file
    ConfigFile := TIniFile.Create(ParamStr(1)); // First parameter is the INI file path
    
    TargetPlugin := ConfigFile.ReadString('SkyGenOptions', 'TargetPlugin', '');
    TargetCategory := ConfigFile.ReadString('SkyGenOptions', 'TargetCategory', '');
    KeywordsStr := ConfigFile.ReadString('SkyGenOptions', 'Keywords', '');
    BroadCategorySwap := ConfigFile.ReadBool('SkyGenOptions', 'BroadCategorySwap', False);
    OutputFilePath := ConfigFile.ReadString('SkyGenOptions', 'OutputFilePath', '');

    if (TargetPlugin = '') or (OutputFilePath = '') then
    begin
      AddMessage('Error: TargetPlugin or OutputFilePath not specified in INI.', True);
      Result := 1; // Indicate error
      Exit;
    end;

    // Prepare keywords
    if KeywordsStr <> '' then
    begin
      KeywordsList.Delimiter := ',';
      KeywordsList.StrictDelimiter := True;
      KeywordsList.DelimitedText := KeywordsStr;
      AddMessage('Keywords loaded: ' + KeywordsList.Text, False);
    end;

    // Open report file (for debugging/logging script output)
    AssignFile(ReportFile, ChangeFileExt(OutputFilePath, '.log'));
    Rewrite(ReportFile);
    Writeln(ReportFile, 'xEdit Script Log for SkyGen Export - ' + DateTimeToStr(Now));
    Writeln(ReportFile, 'Target Plugin: ' + TargetPlugin);
    Writeln(ReportFile, 'Target Category: ' + TargetCategory);
    Writeln(ReportFile, 'Keywords: ' + KeywordsStr);
    Writeln(ReportFile, 'Broad Category Swap: ' + BoolToStr(BroadCategorySwap, True));
    Writeln(ReportFile, 'Output File: ' + OutputFilePath);
    Writeln(ReportFile, '---');

    AddMessage('Processing records...', False);
    
    // Iterate through all records in the specified plugin
    for i := 0 to FileByName(TargetPlugin).Elements.Count - 1 do
    begin
      CurElement := FileByName(TargetPlugin).Elements[i];
      
      // Handle groups (e.g., GRUPs) if necessary, or just focus on top-level records
      if ElementType(CurElement) = etFile then continue; // Skip file element itself
      if ElementType(CurElement) = etMainRecord then
      begin
        // Get the base object if this is an override
        BaseObject := GetLinkTarget(CurElement, 'Record Header\\FormID');
        if BaseObject = nil then
          BaseObject := CurElement; // It's a base record or the override is the first

        FormID := GetFormID(BaseObject);
        EditorID := GetEditorID(BaseObject);
        Name := GetElementEditValues(BaseObject, 'FULL\\Name'); // Assuming FULL is the name field
        if Name = '' then Name := GetElementEditValues(BaseObject, 'Record Header\\CNAM'); // Common name for some record types
        if Name = '' then Name := EditorID; // Fallback to EditorID

        Path := GetElementPath(CurElement);
        FileFormID := GetElementFileFormID(CurElement); // Get the plugin's short form ID

        // Check if this record is overridden by another plugin higher in the load order
        IsOverridden := HasElementOverride(CurElement);
        // If TargetCategory is empty, export all records.
        // Otherwise, filter by TargetCategory and keywords.
        if (TargetCategory = '') or 
           (CompareText(Signature(BaseObject), TargetCategory) = 0) or
           (BroadCategorySwap and StartsStr(TargetCategory, Signature(BaseObject))) then
        begin
          KeywordFound := (KeywordsList.Count = 0); // If no keywords, all are considered found
          if not KeywordFound then
          begin
            for var k := 0 to KeywordsList.Count - 1 do
            begin
              if Pos(Lowercase(KeywordsList[k]), Lowercase(Name)) > 0 then
              begin
                KeywordFound := True;
                Break;
              end;
            end;
          end;

          if KeywordFound then
          begin
            RecordData := TJSONObject.Create;
            RecordData.Add('FormID', FormID);
            RecordData.Add('EditorID', EditorID);
            RecordData.Add('Name', Name);
            RecordData.Add('Path', Path);
            RecordData.Add('FileFormID', FileFormID);
            RecordData.Add('IsOverridden', IsOverridden); // Add IsOverridden flag

            BaseObjectsArray.Add(RecordData);
            Writeln(ReportFile, 'Exported: ' + FormID + ' - ' + Name);
          end;
        end;
      end;
    end;
    
    // Write JSON output file
    if BaseObjectsArray.Count > 0 then
    begin
      var OutputJSON := TJSONObject.Create;
      OutputJSON.Add('baseObjects', BaseObjectsArray);
      WriteStringToFile(OutputFilePath, OutputJSON.Format(True));
      AddMessage('Successfully exported data to ' + OutputFilePath, False);
    end
    else
    begin
      WriteStringToFile(OutputFilePath, '{"baseObjects": []}'); // Write empty JSON array if no data
      AddMessage('No matching records found to export.', False);
    end;

  except
    on E: Exception do
    begin
      AddMessage('An error occurred during processing: ' + E.Message, True);
      Writeln(ReportFile, 'Error: ' + E.Message);
      Result := 1; // Indicate error
    end;
  end;

  // Cleanup
  FreeAndNil(ConfigFile);
  FreeAndNil(KeywordsList);
  FreeAndNil(BaseObjectsArray);
  CloseFile(ReportFile);
end.
"""
    return pascal_script


def clean_temp_files(temp_script_path: Path, temp_ini_path: Optional[Path], debug_logger: Any, temp_script_output_json_path: Optional[Path] = None, temp_script_log_path: Optional[Path] = None):
    """
    Cleans up temporary script and INI files after xEdit execution.
    """
    files_to_delete = [temp_script_path]
    if temp_ini_path:
        files_to_delete.append(temp_ini_path)
    if temp_script_output_json_path and temp_script_output_json_path.exists():
        files_to_delete.append(temp_script_output_json_path)
    if temp_script_log_path and temp_script_log_path.exists():
        files_to_delete.append(temp_script_log_path)

    for f_path in files_to_delete:
        try:
            if f_path.exists():
                f_path.unlink()
                debug_logger(MO2_LOG_DEBUG, f"SkyGen: Cleaned up temporary file: {f_path}")
        except Exception as e:
            debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not delete temporary file '{f_path}': {e}")


def get_xedit_exe_path(wrapped_organizer: Any, dialog: Any) -> Optional[tuple[Path, str]]:
    """
    Determines the path to the xEdit executable (SSEEdit, FO4Edit, etc.)
    and its MO2-registered name.
    """
    debug_logger = wrapped_organizer.log
    debug_logger(MO2_LOG_INFO, "SkyGen: Attempting to determine xEdit executable path.")

    executables = wrapped_organizer.getExecutables()
    xedit_names = ["sseedit", "fo4edit", "tes5edit", "fnvedit", "obedit", "xedit"]

    found_xedit_path = None
    found_xedit_mo2_name = None

    for exec_name, exec_info in executables.items():
        if exec_name.lower() in xedit_names or any(xn in exec_name.lower() for xn in xedit_names):
            exe_path = Path(exec_info.binary())
            if exe_path.is_file():
                found_xedit_path = exe_path
                found_xedit_mo2_name = exec_name
                debug_logger(MO2_LOG_INFO, f"SkyGen: Found xEdit executable: '{found_xedit_mo2_name}' at '{found_xedit_path}'.")
                return found_xedit_path, found_xedit_mo2_name
    
    if dialog:
        dialog.showError("xEdit Not Found", "Could not find any xEdit executable configured in Mod Organizer 2. Please ensure xEdit (SSEEdit/FO4Edit/etc.) is added as an executable in MO2.")
    debug_logger(MO2_LOG_ERROR, "SkyGen: ERROR: No xEdit executable found in MO2's configured executables.")
    return None


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
    
    # Check for m_INI.pas and m_JSON.pas existence
    m_ini_path = xedit_edit_scripts_path / "m_INI.pas"
    m_json_path = xedit_edit_scripts_path / "m_JSON.pas"
    
    if not m_ini_path.is_file():
        dialog.showError("Missing Script Dependency", f"m_INI.pas not found in xEdit's 'Edit Scripts' directory: {m_ini_path}. This file is required for the xEdit script to function. Please ensure it's present.")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Missing m_INI.pas at {m_ini_path}")
        return None

    if not m_json_path.is_file():
        dialog.showError("Missing Script Dependency", f"m_JSON.pas not found in xEdit's 'Edit Scripts' directory: {m_json_path}. This file is required for the xEdit script to function. Please ensure it's present.")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Missing m_JSON.pas at {m_json_path}")
        return None


    output_json_filename = f"SkyGen_xEdit_Export_{int(time.time())}.json"
    
    mo2_overwrite_path = Path(wrapped_organizer.modsPath()) / "overwrite"
    plugin_temp_path = Path(wrapped_organizer.pluginDataPath()) / "SkyGen" / "temp"

    final_output_folder = mo2_overwrite_path if mo2_overwrite_path.is_dir() and os.access(mo2_overwrite_path, os.W_OK) else plugin_temp_path
    final_output_folder.mkdir(parents=True, exist_ok=True)

    final_export_json_path = final_output_folder / output_json_filename

    # Temporary files within xEdit's Edit Scripts directory
    temp_script_output_json_path = xedit_edit_scripts_path / f"temp_{output_json_filename}"
    temp_script_log_path = xedit_edit_scripts_path / f"SkyGen_xEdit_Script_Log_{int(time.time())}.txt"

    # Ensure OutputFilePath is correctly set in script_options for the Pascal script
    script_options["OutputFilePath"] = str(temp_script_output_json_path).replace('\\', '/') # Use forward slashes for Pascal script

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
            f.write(ini_content) # THIS IS THE CORRECTED LINE
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

    mo2_exec_name_to_use = xedit_mo2_name

    xedit_args = [
        f"-script:\"{os.path.normpath(str(temp_script_path))}\"",
        "-q", # Quiet mode
        "-autoload", # Automatically load all plugins
        "-IKnowWhatImDoing",
        "-allowMasterFilesEdit", # Allows editing of master files
        "-NoAutoUpdate", # Prevent xEdit from trying to update
        "-NoAutoBackup", # Prevent xEdit from creating backups
        "-exit" # Exit xEdit after script execution
    ]

    game_mode_arg = {
        "SkyrimSE": "-sse",
        "SkyrimVR": "-tes5vr"
    }.get(game_version)
    if game_mode_arg:
        xedit_args.insert(0, game_mode_arg)
    else:
        debug_logger(MO2_LOG_INFO, f"SkyGen: No specific game mode argument for xEdit for game version '{game_version}'. Launching without it.")

    cwd_path = xedit_path.parent
    
    if not cwd_path.is_dir():
        dialog.showError("xEdit Directory Error", f"xEdit main directory not found at: {cwd_path}. Cannot launch xEdit correctly.")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit main directory not found: {cwd_path}")
        clean_temp_files(temp_script_path, temp_ini_path, debug_logger, temp_script_output_json_path, temp_script_log_path)
        return None

    cwd = os.path.normpath(str(cwd_path))
    debug_logger(MO2_LOG_INFO, f"SkyGen: Calling MO2's startApplication for '{mo2_exec_name_to_use}' with arguments: {xedit_args} and CWD: {cwd}")

    for temp_f_path in [temp_script_output_json_path, temp_script_log_path]:
        if temp_f_path.exists():
            try:
                temp_f_path.unlink()
                debug_logger(MO2_LOG_DEBUG, f"SkyGen: Deleted old temporary file: {temp_f_path}")
            except Exception as e:
                debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not delete old temporary file {temp_f_path}: {e}. This might cause issues.")

    try:
        app_handle = wrapped_organizer.startApplication(mo2_exec_name_to_use, xedit_args, str(cwd))

        if app_handle == 0:
            dialog.showError("xEdit Launch Failed", f"Failed to launch '{mo2_exec_name_to_use}' via MO2. Please ensure xEdit is added to MO2's executables and check MO2 logs for more details.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: MO2 startApplication failed to launch xEdit executable '{mo2_exec_name_to_use}'.")
            clean_temp_files(temp_script_path, temp_ini_path, debug_logger)
            return None

        debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit launched with handle: {app_handle}. Polling for output file: {temp_script_output_json_path}")

        total_wait_time = 0
        poll_interval = 1
        while total_wait_time < MAX_POLL_TIME:
            if temp_script_output_json_path.is_file() and temp_script_output_json_path.stat().st_size > 0:
                debug_logger(MO2_LOG_INFO, f"SkyGen: xEdit output file '{temp_script_output_json_path}' found and not empty after {total_wait_time} seconds.")
                break
            time.sleep(poll_interval)
            total_wait_time += poll_interval
        else:
            dialog.showError("xEdit Timeout", f"xEdit process timed out after {MAX_POLL_TIME // 60} minutes. Expected output file '{temp_script_output_json_path}' was not created or remained empty. Check MO2 and xEdit logs.")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: xEdit process timed out after {MAX_POLL_TIME} seconds. Output file not found or empty.")
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

def generate_and_write_skypatcher_yaml(
    wrapped_organizer: Any,
    json_data: dict,
    target_mod_name: str, # Display name of the target mod
    output_folder_path: Path,
    record_type: str,
    broad_category_swap_enabled: bool,
    search_keywords: list[str],
    dialog_instance: Any
) -> bool:
    """
    Generates a SkyPatcher YAML file from the provided xEdit JSON data.
    """
    debug_logger = wrapped_organizer.log
    debug_logger(MO2_LOG_INFO, f"SkyGen: Starting YAML generation for record type '{record_type}' to target '{target_mod_name}'.")

    yaml_data = {}
    total_records_processed = 0

    # Ensure json_data and 'baseObjects' key exist
    if not json_data or "baseObjects" not in json_data:
        dialog_instance.showWarning("YAML Generation Warning", "No 'baseObjects' found in the xEdit JSON data. No YAML file will be generated for this source.")
        debug_logger(MO2_LOG_WARNING, "SkyGen: No 'baseObjects' found in JSON data for YAML generation.")
        return False

    base_objects = json_data.get("baseObjects", [])
    
    # Get internal name of the target mod
    target_mod_internal_name = dialog_instance._get_internal_mod_name_from_display_name(target_mod_name)
    if not target_mod_internal_name:
        dialog_instance.showError("YAML Generation Error", f"Could not determine internal name for target mod '{target_mod_name}'. Cannot generate YAML.")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: Failed to get internal name for target mod '{target_mod_name}'.")
        return False

    # Get the target mod's full path to determine the patcher folder name
    target_mod_path_full = Path(wrapped_organizer.modPath(target_mod_internal_name))

    # Determine the patcher folder name
    # If the target mod is "overwrite", use its direct path. Otherwise, use its display name.
    if target_mod_path_full == Path(wrapped_organizer.modsPath()) / "overwrite":
        patcher_folder_name = "overwrite"
    else:
        # Use a sanitized version of the display name for the folder
        patcher_folder_name = "".join(c for c in target_mod_name if c.isalnum() or c in (' ', '.', '_', '-')).strip()
        patcher_folder_name = patcher_folder_name.replace(' ', '_')
        if not patcher_folder_name: # Fallback if name becomes empty after sanitization
            patcher_folder_name = "SkyGen_Patcher_Output"


    # Determine the source mod's display name from the JSON data's first object (if available)
    # The xEdit script passes TargetPlugin which is the filename, not display name.
    # We need to get the display name from the filename for better YAML readability.
    source_plugin_filename = json_data.get("baseObjects", [{}])[0].get("File", "Unknown.esp") # Fallback
    source_display_name = ""
    # Iterate through MO2's mods to find the display name that matches the plugin filename
    mod_list = wrapped_organizer.modList()
    for mod_internal_name in mod_list.allMods():
        mod_display = mod_list.displayName(mod_internal_name)
        plugin_found = dialog_instance._get_plugin_name_from_mod_name(mod_display, mod_internal_name)
        if plugin_found and plugin_found.lower() == source_plugin_filename.lower():
            source_display_name = mod_display
            break
    
    if not source_display_name:
        source_display_name = Path(source_plugin_filename).stem # Fallback to filename stem if display name not found
        debug_logger(MO2_LOG_WARNING, f"SkyGen: WARNING: Could not find display name for source plugin '{source_plugin_filename}'. Using stem '{source_display_name}'.")


    yaml_data["SkyPatcher"] = {
        "Name": f"{source_display_name} {record_type} to {target_mod_name} Patcher",
        "Author": "SkyGen",
        "Version": "1.0",
        "Targets": [f"{target_mod_name}"], # Use display name
        "Patches": []
    }

    # Access the pre-exported target bases from the dialog instance
    all_exported_target_bases_by_formid = dialog_instance.all_exported_target_bases_by_formid

    for record in base_objects:
        form_id = record.get("FormID")
        editor_id = record.get("EditorID")
        record_name = record.get("Name")
        record_path = record.get("Path") # This might be the path within xEdit, not file system
        record_file_form_id = record.get("FileFormID")
        
        # Determine original record signature from the path if available
        # Example Path: 'Skyrim.esm\\STAT\\00000000' -> Signature: 'STAT'
        # Or from the xEdit script's exported 'Signature' field if it were added
        current_record_signature = record_path.split('\\')[1] if '\\' in record_path else record_type # Fallback


        # Apply keyword filtering if keywords are provided
        if search_keywords:
            keyword_match = False
            for keyword in search_keywords:
                if keyword.lower() in record_name.lower():
                    keyword_match = True
                    break
            if not keyword_match:
                debug_logger(MO2_LOG_DEBUG, f"Skipping record {form_id} '{record_name}' due to keyword mismatch.")
                continue

        # Check if the record is a base object in the target mod
        target_base_object = all_exported_target_bases_by_formid.get(form_id)
        is_target_mod_base = bool(target_base_object)
        
        # Check if the record is overridden by another plugin (IsOverridden from xEdit script)
        # We only want to patch base objects that are NOT overridden by other plugins
        # or if BroadCategorySwap is enabled, we might process overridden records.
        # For a standard patch, we usually only care about the highest override.
        # The xEdit script exports the *base* object. We need to check if *that FormID* is overridden
        # in the *target plugin's context*.
        # The xEdit script exports base objects. So, if record['IsOverridden'] is true,
        # it means the *exported record* itself (the one with 'FormID' and 'EditorID') is an override
        # in the general load order, but here we want to know if the BASE OBJECT in the TARGET
        # mod is overridden by something *else* in the load order.
        # This requires knowing the full load order, which MO2 handles.
        # For now, let's assume if xEdit exported it from the SOURCE mod, it's valid for patching
        # based on user selection.
        
        # The IsOverridden flag from xEdit refers to whether the *exported record* itself is an override.
        # If BroadCategorySwap is enabled, we proceed regardless of 'IsOverridden' for source.
        # If BroadCategorySwap is NOT enabled, and we want to create a patch
        # where source overrides target, we typically target the *highest* version of the target.
        # If a record in the *source* is overridden by something else *after* the source,
        # that's a different concern.
        
        # For simplicity, we are currently generating patches based on the *source* mod's exported data.
        # The complexity of "is this record the highest override in the full load order?" is
        # beyond the scope of a simple xEdit export and might need a different xEdit script approach
        # or post-processing on the full load order.

        # For this version, if broad_category_swap_enabled is False, we will only consider
        # records from the source that are *not* themselves overrides (i.e., they are base records
        # in the source mod). This is a common pattern for "patching from" original mods.
        
        # However, the xEdit script now exports `IsOverridden` based on whether the *base object*
        # is overridden *in the context of the xEdit load order*. If this is `True` for a source record,
        # it means some other plugin is overriding it. For a SkyPatcher, we generally want to patch
        # from the *highest* version of a record.
        # The current script exports the base record, not necessarily the highest override.

        # Let's simplify: if broad_category_swap_enabled is false, we want to skip records
        # that are already overrides *in the source JSON*. The xEdit script is designed to export
        # the base object. So, if `record.get("IsOverridden")` is true, it means the record
        # whose FormID was exported IS overridden by something else. If we only want
        # to patch from *unique* or base records from the source, we'd check this flag.
        
        # For SkyPatcher, if we want to "patch from A to B", we export what's in A.
        # The `IsOverridden` flag in the JSON indicates if the *original base record* has
        # an override *anywhere* in the loaded plugins within xEdit.
        # For SkyPatcher, we are taking records from the source mod. If the source mod's
        # record is itself an override of something *else*, then usually we want to patch
        # based on that override.

        # The `IsOverridden` from the xEdit export means that the *base form ID* exported
        # from the source mod *is overridden somewhere in the load order*.
        # For a standard patch, we want to patch FROM the *effective* record in the source.
        # This means we should *not* filter by `IsOverridden` for source records.
        # If `IsOverridden` is true for a source record, it just means something higher
        # up is overriding it, which is fine, we're taking the base object.

        # The goal for SkyPatcher is generally to find a record in the SOURCE, and if a *matching*
        # record exists in the TARGET (by FormID), then swap values.
        # The current `baseObjects` from xEdit are the original base records.
        # We need to verify if these base records exist in the target.

        # For SkyPatcher, if broad_category_swap_enabled is FALSE, we are expecting
        # the `record_type` (category) to match.
        # If broad_category_swap_enabled is TRUE, we are doing a blanket swap
        # based on FormID, regardless of category.

        # Patch logic
        patch_entry = {}
        if broad_category_swap_enabled:
            # If broad category swap is enabled, the source's category might be different
            # from the target's, but we still want to patch based on FormID.
            patch_entry = {
                "source": {
                    "FormID": form_id,
                    "File": source_plugin_filename # Use the actual plugin filename from xEdit
                },
                "destination": {
                    "Type": record_type, # The record type from the UI
                    "Category": record_type,
                    "Replace": True # Always replace for broad category swap
                }
            }
            # The Name in the destination is not strictly needed for broad swap, but can be helpful for context
            if record_name:
                patch_entry["destination"]["Name"] = record_name
            total_records_processed += 1
        else:
            # Standard patching: category must match
            # The xEdit script already filters by TargetCategory.
            # So, if we reach here, `current_record_signature` should match `record_type`
            # or `record.get("Signature")` if we added it to the xEdit export.
            
            # Here, we assume the exported `record_type` matches `category` for non-broad swap.
            patch_entry = {
                "source": {
                    "FormID": form_id,
                    "File": source_plugin_filename
                },
                "destination": {
                    "Type": record_type, # This must match the category
                    "Category": record_type,
                    "Replace": True
                }
            }
            if record_name:
                patch_entry["destination"]["Name"] = record_name
            total_records_processed += 1
        
        yaml_data["SkyPatcher"]["Patches"].append(patch_entry)


    if total_records_processed == 0:
        dialog_instance.showInformation("YAML Generation Info", f"No matching records found for '{record_type}' with the given keywords. No YAML file generated for '{source_display_name}'.")
        debug_logger(MO2_LOG_INFO, f"SkyGen: No records processed for YAML generation for '{source_display_name}'.")
        return False

    # Construct the output file path
    # Example: SkyGen_Enhanced_Landscapes_STAT_to_DynDOLOD_Output.yaml
    yaml_filename = f"SkyGen_{source_display_name.replace(' ', '_')}_{record_type}_to_{target_mod_name.replace(' ', '_')}.yaml"
    
    # Create the patcher-specific subfolder within the output folder
    final_output_yaml_path = output_folder_path / "SkyPatcher" / patcher_folder_name / yaml_filename
    
    try:
        final_output_yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_output_yaml_path, 'w', encoding='utf-8') as f:
            # Use a YAML library to dump the data. PyYAML is a common choice.
            # Since we don't have PyYAML directly, we'll use a simple JSON-like dump for now
            # and note that real YAML serialization would be needed.
            # For demonstration, we'll use a basic JSON dump as a placeholder for YAML.
            # In a real MO2 plugin, you might bundle PyYAML or use a more basic string format.
            json.dump(yaml_data, f, indent=2, ensure_ascii=False) # Placeholder for YAML
        
        dialog_instance.showInformation("YAML Generation Complete", f"Successfully generated YAML for '{source_display_name}' to '{target_mod_name}' for category '{record_type}'.\nSaved to: {final_output_yaml_path}")
        debug_logger(MO2_LOG_INFO, f"SkyGen: Successfully generated YAML for '{source_display_name}'. Output: {final_output_yaml_path}")
        return True
    except Exception as e:
        dialog_instance.showError("YAML Write Error", f"Failed to write YAML file to '{final_output_yaml_path}': {e}")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write YAML file: {e}")
        return False


def generate_bos_ini_files(
    wrapped_organizer: Any,
    igpc_data: dict,
    output_folder_path: Path,
    dialog_instance: Any
) -> bool:
    """
    Generates BOS INI files from the provided IGPC JSON data.
    """
    debug_logger = wrapped_organizer.log
    debug_logger(MO2_LOG_INFO, "SkyGen: Starting BOS INI generation.")

    if not igpc_data or "mods" not in igpc_data:
        dialog_instance.showWarning("BOS INI Generation Warning", "IGPC JSON data is empty or missing 'mods' key. No BOS INI files will be generated.")
        debug_logger(MO2_LOG_WARNING, "SkyGen: IGPC JSON data is empty or malformed for BOS INI generation.")
        return False

    success_count = 0
    fail_count = 0

    # Ensure BOS folder exists within the output folder
    bos_output_base_path = output_folder_path / "BOS_INI_Output"
    try:
        bos_output_base_path.mkdir(parents=True, exist_ok=True)
        debug_logger(MO2_LOG_INFO, f"SkyGen: Created BOS INI output directory: {bos_output_base_path}")
    except Exception as e:
        dialog_instance.showError("Directory Creation Error", f"Failed to create BOS INI output directory: {bos_output_base_path}\n{e}")
        debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to create BOS INI output directory {bos_output_base_path}: {e}")
        return False

    for mod_entry in igpc_data["mods"]:
        mod_name = mod_entry.get("modName")
        plugin_name = mod_entry.get("pluginName")
        
        if not mod_name or not plugin_name:
            debug_logger(MO2_LOG_WARNING, f"SkyGen: Skipping BOS INI entry due to missing modName or pluginName: {mod_entry}")
            continue

        bos_ini_content = f"; {mod_name} - {plugin_name} BOS INI\n\n"
        
        object_rules = mod_entry.get("objectRules", [])
        if object_rules:
            bos_ini_content += "[Object Rules]\n"
            for rule in object_rules:
                if "formID" in rule and "modelPath" in rule:
                    bos_ini_content += f"{rule['formID']},{rule['modelPath']}\n"
            bos_ini_content += "\n" # Add a newline for separation

        # Add other sections if they exist in the IGPC format
        # Example: [Texture Rules], [Mesh Rules], etc.
        # This part assumes a specific structure for IGPC JSON.
        # You would expand this based on the actual IGPC JSON structure.
        
        # Example for a hypothetical 'textureRules'
        # if mod_entry.get("textureRules"):
        #     bos_ini_content += "[Texture Rules]\n"
        #     for rule in mod_entry["textureRules"]:
        #         bos_ini_content += f"{rule['textureID']},{rule['newTexture']}\n"
        #     bos_ini_content += "\n"

        # Sanitize mod name for filename (replace invalid characters)
        sanitized_mod_name = "".join(c for c in mod_name if c.isalnum() or c in (' ', '_', '-')).strip()
        sanitized_mod_name = sanitized_mod_name.replace(' ', '_')
        if not sanitized_mod_name:
            sanitized_mod_name = f"UnnamedMod_{int(time.time())}" # Fallback
            debug_logger(MO2_LOG_WARNING, f"SkyGen: Sanitized mod name for '{mod_name}' resulted in empty string, using fallback: {sanitized_mod_name}")

        ini_filename = f"BOS_{sanitized_mod_name}.ini"
        final_ini_path = bos_output_base_path / ini_filename

        try:
            with open(final_ini_path, 'w', encoding='utf-8') as f:
                f.write(bos_ini_content)
            debug_logger(MO2_LOG_INFO, f"SkyGen: Successfully generated BOS INI for '{mod_name}'. Output: {final_ini_path}")
            success_count += 1
        except Exception as e:
            dialog_instance.showError("INI Write Error", f"Failed to write BOS INI for '{mod_name}' to '{final_ini_path}': {e}")
            debug_logger(MO2_LOG_ERROR, f"SkyGen: ERROR: Failed to write BOS INI for '{mod_name}': {e}")
            fail_count += 1
    
    if success_count > 0:
        dialog_instance.showInformation("BOS INI Generation Complete", f"Successfully generated {success_count} BOS INI file(s).\nFailed to generate {fail_count} file(s).")
    else:
        dialog_instance.showWarning("BOS INI Generation Complete", f"No BOS INI files were generated. Failed to generate {fail_count} file(s).")
    
    debug_logger(MO2_LOG_INFO, f"SkyGen: BOS INI generation complete. Successes: {success_count}, Failures: {fail_count}.")
    return success_count > 0


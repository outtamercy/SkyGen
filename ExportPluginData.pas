unit ExportPluginData;

uses
  SysUtils, Classes, Dialogs, StrUtils, SyncObjs, Windows, IOUtils,
  xSimUtils, xEditTypes, xEditLib, xEditJSON; // Added xEditJSON for TJSONObject

type
  // Define a custom log procedure type for flexibility
  TLogProcedure = procedure(const Msg: string);

var
  // Global reference to the log procedure
  _Log: TLogProcedure;
  DebugLogFile: TextFile;
  IsLogInitialized: Boolean = False;
  GlobalException: Exception = nil; // To capture unhandled exceptions

// Helper function to check if a directory exists and create it if needed
function EnsureDirectoryExists(const Path: string): Boolean;
var
  DirPath: string;
begin
  Result := True;
  DirPath := ExtractFilePath(Path);
  
  // If no directory part, assume current directory which exists
  if DirPath = '' then Exit;
  
  // Check if directory exists, create if it doesn't
  if not DirectoryExists(DirPath) then begin
    try
      ForceDirectories(DirPath);
    except
      on E: Exception do begin
        _Log('❌ ERROR: Failed to create directory "' + DirPath + '". Error: ' + E.Message);
        Result := False;
      end;
    end;
  end;
end;

// Default log procedure that writes to xEdit's console (AddMessage)
procedure DefaultLog(const Msg: string);
begin
  AddMessage('[ExportPluginData] ' + Msg);
end;

// Debug log procedure that writes to a file
procedure DebugFileLog(const Msg: string);
begin
  if IsLogInitialized then begin
    try
      Writeln(DebugLogFile, Msg);
      Flush(DebugLogFile);
    except
      on E: Exception do begin
        // If writing to log fails after initialization, disable logging and report to console
        IsLogInitialized := False;
        AddMessage('[ExportPluginData] WARNING: Failed to write to debug log. Further file logging disabled. Error: ' + E.Message);
        // Fallback to console for this message
        AddMessage('[ExportPluginData] ' + Msg); 
      end;
    end;
  end else begin
    // If debug log not initialized, just use default console log
    DefaultLog(Msg);
  end;
end;

// This procedure will be called once when the script starts
procedure InitializeDebugLog(const LogFilePath: string);
begin
  // Set default log procedure to console
  _Log := DefaultLog; 

  try
    // First ensure the directory exists
    if not EnsureDirectoryExists(LogFilePath) then begin
      IsLogInitialized := False;
      _Log('CRITICAL: Failed to create directory for debug log at "' + LogFilePath + '".');
      _Log('CRITICAL: No debug log will be written. Please check path and permissions.');
      Exit; // Cannot proceed with file logging
    end;
    
    AssignFile(DebugLogFile, LogFilePath);
    if FileExists(LogFilePath) then
      Append(DebugLogFile)
    else
      Rewrite(DebugLogFile); // Create new file if it doesn't exist

    // If successful, switch the global log procedure to file logging
    IsLogInitialized := True;
    _Log := DebugFileLog; 
    
    _Log('--- ExportPluginData Debug Log Start: ' + DateTimeToStr(Now) + ' ---');
    _Log('Log file path: ' + LogFilePath);
    _Log('Current working directory: ' + GetCurrentDir);
  except
    on E: EInOutError do begin
      IsLogInitialized := False;
      _Log := DefaultLog; // Fallback to console for critical error
      _Log('CRITICAL: Failed to initialize debug log at "' + LogFilePath + '". I/O Error: ' + E.Message);
      _Log('CRITICAL: No debug log will be written. Please check path and permissions. Last OS Error: ' + IntToStr(GetLastError));
    end;
    on E: Exception do begin
      IsLogInitialized := False;
      _Log := DefaultLog; // Fallback to console for critical error
      _Log('CRITICAL: Failed to initialize debug log at "' + LogFilePath + '". General Error: ' + E.Message);
      _Log('CRITICAL: No debug log will be written. Please check path and permissions. Last OS Error: ' + IntToStr(GetLastError));
    end;
  end;
end;

// This procedure will be called after the script finishes
procedure FinalizeDebugLog;
begin
  if IsLogInitialized then begin
    try
      _Log('--- ExportPluginData Debug Log End: ' + DateTimeToStr(Now) + ' ---');
      CloseFile(DebugLogFile);
    except
      on E: Exception do begin
        AddMessage('[ExportPluginData] WARNING: Failed to finalize debug log. Error: ' + E.Message);
      end;
    end;
  end;
end;

// Function to safely get a command line argument value
function GetCmdLineArg(const ParamName: string): string;
var
  i: Integer;
begin
  Result := '';
  for i := 1 to ParamCount do begin
    if StartsText(ParamName, ParamStr(i)) then begin
      Result := Copy(ParamStr(i), Length(ParamName) + 1, MaxInt);
      Exit;
    end;
  end;
end;

// This is the main script execution point
function Process(EditorID, FormID: string; SaveFile: Boolean; var Message: string): Integer;
var
  OutputPath: string;
  DebugLogPath: string;
  FileStream: TFileStream;
  OutputJSON: TJSONObject;
  PluginName: string;
  BaseRecordsArray: TJSONArray; // Example for a structured output
  i: Integer;
begin
  Result := 1; // Default to error
  GlobalException := nil; // Reset global exception

  // Initialize debug log based on command line argument
  DebugLogPath := GetCmdLineArg('-debuglog:');
  if DebugLogPath = '' then
    DebugLogPath := 'ExportPluginData_Debug.log'; // Default log file in xEdit directory if not specified
  
  InitializeDebugLog(ExpandFileName(DebugLogPath));
  _Log('Script Process function started.');
  _Log('Parsed Debug Log Path: ' + DebugLogPath);
  _Log('Expanded Debug Log Path: ' + ExpandFileName(DebugLogPath));
  
  // Debug: Log all command line parameters
  _Log('Total command line parameters: ' + IntToStr(ParamCount));
  for i := 1 to ParamCount do begin
    _Log('Param[' + IntToStr(i) + ']: ' + ParamStr(i));
  end;

  // Get output path from command line argument
  OutputPath := GetCmdLineArg('-o:');
  if OutputPath = '' then begin
    _Log('❌ ERROR: Output path (-o:) not specified. Script cannot proceed.');
    Result := 1; // Indicate error
    Exit;
  end;
  OutputPath := ExpandFileName(OutputPath); // Convert to absolute path
  _Log('Parsed Output Path: ' + GetCmdLineArg('-o:'));
  _Log('Expanded Output Path: ' + OutputPath);

  // Extract Plugin Name from command line argument or use a default
  PluginName := GetCmdLineArg('-plugin:');
  if PluginName = '' then begin
    PluginName := 'Unknown_Plugin'; // Default if not specified
    _Log('WARNING: Plugin name not specified via -plugin: argument. Using default: ' + PluginName);
  end else begin
    _Log('Processing Plugin: ' + PluginName);
  end;
  
  // --- Start generating JSON data ---
  OutputJSON := TJSONObject.Create;
  try
    OutputJSON.AddPair('pluginName', PluginName);
    OutputJSON.AddPair('editorID', EditorID);
    OutputJSON.AddPair('formID', FormID);
    OutputJSON.AddPair('scriptExecutionTime', DateTimeToStr(Now));

    // Example of adding structured data (e.g., base objects from a plugin)
    BaseRecordsArray := TJSONArray.Create;
    try
      // In a real scenario, you would populate this array by iterating through xEdit records
      // For demonstration, let's add some mock data
      for i := 1 to 3 do begin
        BaseRecordsArray.Add(TJSONObject.Create.AddPair('id', 'MockRecord' + IntToStr(i)).AddPair('type', 'MISC'));
      end;
      OutputJSON.AddPair('sourceModBaseObjects', BaseRecordsArray);
      BaseRecordsArray := nil; // Transfer ownership to OutputJSON
    except
      on E: Exception do begin
        _Log('WARNING: Failed to generate BaseRecordsArray. Error: ' + E.Message);
        if Assigned(BaseRecordsArray) then begin
          BaseRecordsArray.Free; 
          BaseRecordsArray := nil;
        end;
      end;
    end;

    _Log('Attempting to create final output file at: "' + OutputPath + '"');
    try
      // First ensure the directory exists for the output file
      if not EnsureDirectoryExists(OutputPath) then begin
        _Log('❌ FATAL: Failed to create directory for output file at "' + OutputPath + '". Last OS Error: ' + IntToStr(GetLastError));
        raise Exception.Create('Failed to create directory for output file');
      end;
      
      FileStream := TFileStream.Create(OutputPath, fmCreate);
      try
        OutputJSON.SaveToStream(FileStream);
      finally
        FileStream.Free; // Ensure stream is freed even if SaveToStream fails
      end;
      _Log('✅ Export complete. Records saved to: "' + OutputPath + '"');
      Result := 0; // Success
    except
      on E: EInOutError do begin
        _Log('❌ FATAL: EInOutError when creating or writing to output file "' + OutputPath + '". Error: ' + E.Message + '. Last OS Error: ' + IntToStr(GetLastError));
        raise; // Re-raise the exception to be caught by the outer block for cleanup
      end;
      on E: Exception do begin
        _Log('❌ FATAL: Failed to create or write to output file: ' + E.Message + '. Last OS Error: ' + IntToStr(GetLastError));
        raise; // Re-raise the exception
      end;
    end;
  finally
    OutputJSON.Free; // Ensure JSON object is freed
  end;

  _Log('Script Process function finished. Result Code: ' + IntToStr(Result)); 
  FinalizeDebugLog();
  
  // Set the message variable for xEdit's console output (if Process returns 0)
  if Result = 0 then
    Message := 'Successfully exported plugin data.'
  else if GlobalException <> nil then
    Message := 'Script encountered an unhandled error: ' + GlobalException.Message
  else
    Message := 'Script finished with errors. Check log for details.';

  Exit; // Ensure we exit cleanly
end;

// Global exception handler for any unhandled exceptions in the script
function SafeProcess(EditorID, FormID: string; SaveFile: Boolean; var Message: string): Integer;
begin
  try
    Result := Process(EditorID, FormID, SaveFile, Message);
  except
    on E: Exception do begin
      GlobalException := E; // Store the exception
      Result := 99; // Indicate general script error
      AddMessage('[ExportPluginData] UNHANDLED EXCEPTION in SafeProcess: ' + E.Message);
      AddMessage('[ExportPluginData] Stack Trace (if available): ' + E.StackTrace); // xEdit might not provide this
      Message := 'Script encountered an unexpected error: ' + E.Message;
    end;
  end;
end;

end.

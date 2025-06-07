unit ExportPluginData;

uses
  SysUtils, Classes, Dialogs, StrUtils, SyncObjs, Windows, IOUtils,
  xSimUtils, xEditTypes, xEditLib, xEditJSON;

type
  TLogProcedure = procedure(const Msg: string);

var
  _Log: TLogProcedure;
  DebugLogFile: TextFile;
  IsLogInitialized: Boolean = False;
  GlobalException: Exception = nil;

function EnsureDirectoryExists(const Path: string): Boolean;
var
  DirPath: string;
begin
  Result := True;
  DirPath := ExtractFilePath(Path);
  
  if DirPath = '' then Exit;
  
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

procedure DefaultLog(const Msg: string);
begin
  AddMessage('[ExportPluginData] ' + Msg);
end;

procedure DebugFileLog(const Msg: string);
begin
  if IsLogInitialized then begin
    try
      Writeln(DebugLogFile, Msg);
      Flush(DebugLogFile);
    except
      on E: Exception do begin
        IsLogInitialized := False;
        AddMessage('[ExportPluginData] WARNING: Failed to write to debug log. Further file logging disabled. Error: ' + E.Message);
        AddMessage('[ExportPluginData] ' + Msg); 
      end;
    end;
  end else begin
    DefaultLog(Msg);
  end;
end;

procedure InitializeDebugLog(const LogFilePath: string);
begin
  _Log := DefaultLog; 

  try
    if not EnsureDirectoryExists(LogFilePath) then begin
      IsLogInitialized := False;
      _Log('CRITICAL: Failed to create directory for debug log at "' + LogFilePath + '".');
      _Log('CRITICAL: No debug log will be written. Please check path and permissions.');
      Exit;
    end;
    
    AssignFile(DebugLogFile, LogFilePath);
    if FileExists(LogFilePath) then
      Append(DebugLogFile)
    else
      Rewrite(DebugLogFile);

    IsLogInitialized := True;
    _Log := DebugFileLog; 
    
    _Log('--- ExportPluginData Debug Log Start: ' + DateTimeToStr(Now) + ' ---');
    _Log('Log file path: ' + LogFilePath);
    _Log('Current working directory: ' + GetCurrentDir);
  except
    on E: EInOutError do begin
      IsLogInitialized := False;
      _Log := DefaultLog;
      _Log('CRITICAL: Failed to initialize debug log at "' + LogFilePath + '". I/O Error: ' + E.Message);
      _Log('CRITICAL: No debug log will be written. Please check path and permissions. Last OS Error: ' + IntToStr(GetLastError));
    end;
    on E: Exception do begin
      IsLogInitialized := False;
      _Log := DefaultLog;
      _Log('CRITICAL: Failed to initialize debug log at "' + LogFilePath + '". General Error: ' + E.Message);
      _Log('CRITICAL: No debug log will be written. Please check path and permissions. Last OS Error: ' + IntToStr(GetLastError));
    end;
  end;
end;

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

function Process(EditorID, FormID: string; SaveFile: Boolean; var Message: string): Integer;
var
  OutputPath: string;
  DebugLogPath: string;
  FileStream: TFileStream;
  OutputJSON: TJSONObject;
  PluginName: string;
  BaseRecordsArray: TJSONArray;
  i: Integer;
begin
  Result := 1;
  GlobalException := nil;

  DebugLogPath := GetCmdLineArg('-debuglog:');
  if DebugLogPath = '' then
    DebugLogPath := 'ExportPluginData_Debug.log';
  
  InitializeDebugLog(ExpandFileName(DebugLogPath));
  _Log('Script Process function started.');
  _Log('Parsed Debug Log Path: ' + DebugLogPath);
  _Log('Expanded Debug Log Path: ' + ExpandFileName(DebugLogPath));
  
  // Debug: Log all command line parameters
  _Log('Total command line parameters: ' + IntToStr(ParamCount));
  for i := 1 to ParamCount do begin
    _Log('Param[' + IntToStr(i) + ']: ' + ParamStr(i));
  end;

  OutputPath := GetCmdLineArg('-o:');
  if OutputPath = '' then begin
    _Log('❌ ERROR: Output path (-o:) not specified. Script cannot proceed.');
    Result := 1;
    Exit;
  end;
  OutputPath := ExpandFileName(OutputPath);
  _Log('Parsed Output Path: ' + GetCmdLineArg('-o:'));
  _Log('Expanded Output Path: ' + OutputPath);

  PluginName := GetCmdLineArg('-plugin:');
  if PluginName = '' then begin
    PluginName := 'Unknown_Plugin';
    _Log('WARNING: Plugin name not specified via -plugin: argument. Using default: ' + PluginName);
  end else begin
    _Log('Processing Plugin: ' + PluginName);
  end;
  
  OutputJSON := TJSONObject.Create;
  try
    OutputJSON.AddPair('pluginName', PluginName);
    OutputJSON.AddPair('editorID', EditorID);
    OutputJSON.AddPair('formID', FormID);
    OutputJSON.AddPair('scriptExecutionTime', DateTimeToStr(Now));

    BaseRecordsArray := TJSONArray.Create;
    try
      for i := 1 to 3 do begin
        BaseRecordsArray.Add(TJSONObject.Create.AddPair('id', 'MockRecord' + IntToStr(i)).AddPair('type', 'MISC'));
      end;
      OutputJSON.AddPair('sourceModBaseObjects', BaseRecordsArray);
      BaseRecordsArray := nil;
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
      if not EnsureDirectoryExists(OutputPath) then begin
        _Log('❌ FATAL: Failed to create directory for output file at "' + OutputPath + '". Last OS Error: ' + IntToStr(GetLastError));
        raise Exception.Create('Failed to create directory for output file');
      end;
      
      FileStream := TFileStream.Create(OutputPath, fmCreate);
      try
        OutputJSON.SaveToStream(FileStream);
      finally
        FileStream.Free;
      end;
      _Log('✅ Export complete. Records saved to: "' + OutputPath + '"');
      Result := 0;
    except
      on E: EInOutError do begin
        _Log('❌ FATAL: EInOutError when creating or writing to output file "' + OutputPath + '". Error: ' + E.Message + '. Last OS Error: ' + IntToStr(GetLastError));
        raise;
      end;
      on E: Exception do begin
        _Log('❌ FATAL: Failed to create or write to output file: ' + E.Message + '. Last OS Error: ' + IntToStr(GetLastError));
        raise;
      end;
    end;
  finally
    OutputJSON.Free;
  end;

  _Log('Script Process function finished. Result Code: ' + IntToStr(Result)); 
  FinalizeDebugLog();
  
  if Result = 0 then
    Message := 'Successfully exported plugin data.'
  else if GlobalException <> nil then
    Message := 'Script encountered an unhandled error: ' + GlobalException.Message
  else
    Message := 'Script finished with errors. Check log for details.';

  Exit;
end;

function SafeProcess(EditorID, FormID: string; SaveFile: Boolean; var Message: string): Integer;
begin
  try
    Result := Process(EditorID, FormID, SaveFile, Message);
  except
    on E: Exception do begin
      GlobalException := E;
      Result := 99;
      AddMessage('[ExportPluginData] UNHANDLED EXCEPTION in SafeProcess: ' + E.Message);
      AddMessage('[ExportPluginData] Stack Trace (if available): ' + E.StackTrace);
      Message := 'Script encountered an unexpected error: ' + E.Message;
    end;
  end;
end;

end.

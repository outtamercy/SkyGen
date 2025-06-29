unit ExportPluginData;

uses xEditAPI, Classes, SysUtils;

var
  outputPath, outputDir, debugLogFileName: string;
  i: Integer;
  logFile: TextFile;

function Initialize: Integer;
begin
  outputPath := '';
  debugLogFileName := 'ExportPluginData_Debug.log';

  for i := 1 to ParamCount do begin
    if Pos('-o:', ParamStr(i)) = 1 then begin
      outputPath := Copy(ParamStr(i), 4, Length(ParamStr(i)));
    end;
  end;

  AddMessage('DEBUG: Raw outputPath = "' + outputPath + '"');

  outputDir := ExtractFilePath(outputPath);
  AddMessage('DEBUG: outputDir (extracted): "' + outputDir + '"');

  if outputDir = '' then begin
    AddMessage('ERROR: outputDir is empty!');
    Result := 1;
    Exit;
  end;

  if not DirectoryExists(outputDir) then begin
    AddMessage('DEBUG: Directory does not exist, attempting to create: "' + outputDir + '"');
    ForceDirectories(outputDir);
    if not DirectoryExists(outputDir) then begin
        AddMessage('ERROR: Failed to create directory: "' + outputDir + '"');
        Result := 1;
        Exit;
    end;
  end;

  try
    AssignFile(logFile, outputDir + debugLogFileName);
    Rewrite(logFile);
    WriteLn(logFile, 'SkyGen export started.');
    CloseFile(logFile);
  except
    on E: Exception do begin
      AddMessage('Failed to write debug log: ' + E.Message);
    end;
  end;

  Result := 0;
end;

end.
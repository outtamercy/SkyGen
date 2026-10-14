@echo off
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%~dp0..") do set "BASE_DIR=%%~fI"
for %%I in ("%~dp0..\..\..") do set "MO2_ROOT=%%~fI"

:: Verify bundled Python exists
set "BUNDLED_PYTHON=!BASE_DIR!\Start_here_before_install\python\python.exe"
if not exist "!BUNDLED_PYTHON!" (
    echo ERROR: Bundled Python not found at !BUNDLED_PYTHON!
    if !IS_SILENT! equ 0 pause
    exit /b 1
)

:: Detect mode
if exist "%MO2_ROOT%\ModOrganizer.ini" (
    echo [MO2 Mode Detected]
    call :ReadProfileFromIni "%MO2_ROOT%\ModOrganizer.ini"
    call :ReadGamePathFromIni "%MO2_ROOT%\ModOrganizer.ini"
    set "MODS_PATH=%MO2_ROOT%\mods"
) else (
    echo [Standalone Mode]
    set "PROFILE_NAME=Default"
    
    :: Registry lookup for Skyrim
    for /f "tokens=2,*" %%A in (
        'reg query "HKLM\SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim Special Edition" /v "Installed Path" 2^>nul'
    ) do set "SKYRIM_BASE=%%B"
    
    if "!SKYRIM_BASE!"=="" (
        echo ERROR: Cannot find Skyrim Special Edition registry entry.
        echo Install via Steam or run through MO2.
        if !IS_SILENT! equ 0 pause
        exit /b 1
    )
    
    set "SKYRIM_DATA=!SKYRIM_BASE!\Data"
    set "MODS_PATH="
)

:: Build output path
set "OUTPUT=!BASE_DIR!\data\skygen_manifest_!PROFILE_NAME!.ini"

:: Ensure output directory exists
if not exist "!BASE_DIR!\data" mkdir "!BASE_DIR!\data"

echo.
echo ============================================
echo  FrankenSnoop
echo ============================================
echo Profile: !PROFILE_NAME!
echo Output:  !OUTPUT!
if defined MODS_PATH echo Mods:    !MODS_PATH!
echo.

:: Build args
if defined MODS_PATH (
    set "PY_ARGS=--source "!SKYRIM_DATA!" --output "!OUTPUT!" --profile "!PROFILE_NAME!" --mods-path "!MODS_PATH!" --profile-dir "!MO2_ROOT!\profiles\!PROFILE_NAME!""
) else (
    set "PY_ARGS=--source "!SKYRIM_DATA!" --output "!OUTPUT!" --profile "!PROFILE_NAME!""
)

:: Execute
"!BUNDLED_PYTHON!" "!SCRIPT_DIR!frankensnoop.py" !PY_ARGS!
set "IS_SILENT=0"
for %%A in (%*) do if "%%A"=="--silent" set "IS_SILENT=1"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Scan failed.
    if !IS_SILENT! equ 0 pause
    exit /b 1
)

echo.
echo ==============================
echo    Manifest Created!
echo ==============================
echo Location: !OUTPUT!
echo.
if !IS_SILENT! equ 0 pause
goto :EOF

:ReadProfileFromIni
set "PROFILE_NAME="
for /f "usebackq tokens=1,* delims==" %%A in ("%~1") do (
    if "%%A"=="selected_profile" (
        set "VAL=%%B"
        set "VAL=!VAL:@ByteArray(=!"
        set "VAL=!VAL:)=!"
        set "VAL=!VAL:"=!"
        for /f "tokens=* delims= " %%a in ("!VAL!") do set "PROFILE_NAME=%%a"
    )
)
if "!PROFILE_NAME!"=="" set "PROFILE_NAME=Default"
goto :EOF

:ReadGamePathFromIni
set "SKYRIM_DATA="
for /f "usebackq tokens=1,* delims==" %%A in ("%~1") do (
    if "%%A"=="gamePath" (
        set "VAL=%%B"
        set "VAL=!VAL:@ByteArray(=!"
        set "VAL=!VAL:)=!"
        set "VAL=!VAL:"=!"
        set "VAL=!VAL:\\=\!"
        for /f "tokens=* delims= " %%a in ("!VAL!") do set "SKYRIM_BASE=%%a"
        set "SKYRIM_DATA=!SKYRIM_BASE!\Data"
    )
)
goto :EOF
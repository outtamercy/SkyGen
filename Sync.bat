@echo off
set GIT=%~dp0
set LIVE=H:\Truth Special Edition\plugins\SkyGen

echo === DIAGNOSTIC ===
echo GIT  = %GIT%
echo LIVE = %LIVE%
echo.

echo Checking LIVE folders:
if exist "%LIVE%\src" (echo [OK] src) else (echo [MISSING] src)
if exist "%LIVE%\ui" (echo [OK] ui) else (echo [MISSING] ui)
if exist "%LIVE%\utils" (echo [OK] utils) else (echo [MISSING] utils)
if exist "%LIVE%\__init__.py" (echo [OK] __init__.py) else (echo [MISSING] __init__.py)
echo.

echo 1. Git - MO2 (test from repo)
echo 2. MO2 - Git (save live edits)
echo.
set /p choice="Pick: "

if "%choice%"=="1" (
    echo Copying Git - MO2...
    xcopy /Y /E /I "%GIT%src\*" "%LIVE%\src\"
    xcopy /Y /E /I "%GIT%ui\*" "%LIVE%\ui\"
    xcopy /Y /E /I "%GIT%utils\*" "%LIVE%\utils\"
    xcopy /Y /E /I "%GIT%extractors\*" "%LIVE%\extractors\"
    xcopy /Y /E /I "%GIT%core\*" "%LIVE%\core\"
    xcopy /Y /E /I "%GIT%storage\*" "%LIVE%\storage\"
    xcopy /Y "%GIT%__init__.py" "%LIVE%"
    xcopy /Y "%GIT%keyword\keywords.ini" "%LIVE%\keyword\"
) else (
    echo Copying MO2 - Git...
    xcopy /Y /E /I "%LIVE%\src\*" "%GIT%src\"
    xcopy /Y /E /I "%LIVE%\ui\*" "%GIT%ui\"
    xcopy /Y /E /I "%LIVE%\utils\*" "%GIT%utils\"
    xcopy /Y /E /I "%LIVE%\extractors\*" "%GIT%extractors\"
    xcopy /Y /E /I "%LIVE%\core\*" "%GIT%core\"
    xcopy /Y /E /I "%LIVE%\storage\*" "%GIT%storage\"
    xcopy /Y "%LIVE%\__init__.py" "%GIT%"
    xcopy /Y "%LIVE%\keyword\keywords.ini" "%GIT%keyword\"
)
pause
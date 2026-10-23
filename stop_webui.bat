@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Imaging Scientist WebUI Stopper

echo Stopping imaging_scientist WebUI and backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-webui.ps1" -RepoRoot "%~dp0."
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Stop operation completed. Press any key to close this window.
) else (
    echo Stop operation encountered an error. Press any key to close this window.
)
pause >nul
endlocal & exit /b %EXIT_CODE%

@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Imaging Scientist WebUI Launcher
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-webui-production.ps1" -RepoRoot "%~dp0." -Workdir "E:\data" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
    echo WebUI is ready. Keep this window open to review startup status, or press any key to close it.
    echo The WebUI and backend continue running after this launcher window closes.
    pause >nul
) else (
    echo.
    echo Startup failed. Read the error above and the logs under:
    echo   %~dp0.local-home\logs
    echo.
    pause
)
endlocal & exit /b %EXIT_CODE%

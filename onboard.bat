@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "WITAISCIENTIST_CONFIG_PATH=%CD%\user-config\config.yaml"

if not exist ".venv\Scripts\python.exe" (
    echo Python environment was not found. Run: uv sync --frozen
    exit /b 1
)

".venv\Scripts\python.exe" -m imaging_scientist onboard
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Setup failed. Read the error above and try again after resolving it.
    echo.
    pause
)
endlocal & exit /b %EXIT_CODE%

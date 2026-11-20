@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python 3.10 or newer was not found.
        echo Install Python from https://www.python.org/downloads/
        echo During setup, enable "Add Python to PATH".
        pause
        exit /b 1
    )
    set "PYTHON=python"
) else (
    set "PYTHON=py -3"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the local Python environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo Could not create the Python environment.
        pause
        exit /b 1
    )
)

echo Checking required packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Package installation failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo Starting the transcript scraper...
".venv\Scripts\python.exe" app.py
pause

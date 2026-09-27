@echo off
cd /d "%~dp0"
pythonw app.py
if errorlevel 1 (
    echo.
    echo The app closed with an error. If this is the first run, try
    echo double-clicking setup.bat first.
    pause
)

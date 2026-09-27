@echo off
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on your PATH.
    echo Install it from https://www.python.org/downloads/ ^(check "Add python.exe to PATH"
    echo during install^), then run this file again.
    pause
    exit /b 1
)

echo Installing Korean OCR Subtitle Extractor dependencies...
echo (One-time step. The first real OCR run also downloads a small Korean
echo  model file, ~50MB, which needs an internet connection.)
echo.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done. Run "run.bat" to launch the app.
pause

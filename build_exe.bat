@echo off
REM Build a portable single-file DSigner.exe into dist\
REM Requires the venv with requirements installed (see README).

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-Process DSigner -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo DSigner.exe is currently running. Close it before building.
    exit /b 1
)

if not exist "venv\Scripts\pyinstaller.exe" (
    echo Installing PyInstaller...
    venv\Scripts\pip.exe install pyinstaller
)

venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --name DSigner main.py
if errorlevel 1 (
    echo.
    echo Build FAILED - check the PyInstaller output above.
    exit /b 1
)

if exist "dist\DSigner.exe" (
    echo.
    echo Build complete: dist\DSigner.exe
) else (
    echo.
    echo Build FAILED - check the output above.
    exit /b 1
)

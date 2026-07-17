@echo off
REM Build a portable single-file timestamped DSigner exe into dist\
REM Requires the venv with requirements installed (see README).

cd /d "%~dp0"

for /f %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "BUILD_TIMESTAMP=%%I"
for /f "tokens=2 delims== " %%I in ('findstr /B "APP_VERSION" core\app_info.py') do set "APP_VERSION=%%~I"
if "%APP_VERSION%"=="" set "APP_VERSION=0.0.0"
set "EXE_NAME=DSigner_v%APP_VERSION%_%BUILD_TIMESTAMP%"

if not exist "venv\Scripts\pyinstaller.exe" (
    echo Installing PyInstaller...
    venv\Scripts\pip.exe install pyinstaller
)

venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --name "%EXE_NAME%" --icon "assets\logo.ico" --add-data "assets;assets" main.py
if errorlevel 1 (
    echo.
    echo Build FAILED - check the PyInstaller output above.
    exit /b 1
)

if exist "dist\%EXE_NAME%.exe" (
    echo.
    echo Build complete: dist\%EXE_NAME%.exe
) else (
    echo.
    echo Build FAILED - check the output above.
    exit /b 1
)

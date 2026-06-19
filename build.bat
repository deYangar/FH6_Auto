@echo off
chcp 65001 >nul
cd /d "%~dp0"

set APP_NAME=FH6Auto
set MAIN_FILE=main.py

echo.
echo ==============================
echo   FH6Auto Local Build
echo ==============================
echo.

python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.8+ required
    pause
    exit /b 1
)

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    python -m pip install pyinstaller
)

echo [INFO] Current version:
python -c "import json;print(json.load(open('version.json'))['version'])"

echo [INFO] Clean old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%APP_NAME%.spec" del /f /q "%APP_NAME%.spec"

echo [INFO] Check modules...
python -c "import config,constants,input_handler,vision,recovery,race_logic,buy_logic,cj_logic,anti_cheat,focus_hook_manager" 2>nul
if errorlevel 1 (
    echo [ERROR] Module import failed. Installing deps...
    python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo [INFO] Building with PyInstaller...
python -m PyInstaller -n "%APP_NAME%" -F -w --uac-admin "%MAIN_FILE%" --icon=assets/icon.ico --add-data "images;images" --add-data "assets;assets"

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [OK] Build complete: dist\%APP_NAME%.exe
echo.
pause

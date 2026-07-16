@echo off
chcp 65001 >nul
cd /d "%~dp0"

set APP_NAME=FH6Auto
set MAIN_FILE=main.py
set BUILD_TARGET=%1
if "%BUILD_TARGET%"=="" set BUILD_TARGET=steam

echo.
echo ==============================
echo   FH6Auto Build [%BUILD_TARGET%]
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
python -c "import json;print(json.load(open('version.json'))['version'])" 2>nul

echo [INFO] Check modules...
python -c "import config,constants,input_handler,vision,recovery,race_logic,buy_logic,cj_logic,sell_logic,anti_cheat,focus_hook_manager" 2>nul
if errorlevel 1 (
    echo [ERROR] Module import failed. Installing deps...
    python -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM ===== Build function =====
goto :build_%BUILD_TARGET%

:build_steam
echo [INFO] Building Steam version (FH6Auto.exe)...
set EXE_NAME=FH6Auto
goto :do_build

:build_xbox
echo [INFO] Building Xbox version (FH6Auto_xbox.exe)...
set EXE_NAME=FH6Auto_xbox
REM Swap in xbox files
if exist input_handler.py copy /y input_handler.py input_handler_steam_bak.py >nul
if exist race_logic.py copy /y race_logic.py race_logic_steam_bak.py >nul
copy /y input_handler_xbox.py input_handler.py >nul
copy /y race_logic_xbox.py race_logic.py >nul
echo [INFO] Xbox files swapped in.
goto :do_build

:build_all
echo [INFO] Building both Steam and Xbox versions...
call "%~f0" steam
if errorlevel 1 (
    echo [ERROR] Steam build failed, aborting.
    exit /b 1
)
call "%~f0" xbox
goto :eof

:do_build
echo [INFO] Clean old builds...
if exist build rmdir /s /q build
if exist "%EXE_NAME%.spec" del /f /q "%EXE_NAME%.spec"

echo [INFO] Building with PyInstaller...
python -m PyInstaller -n "%EXE_NAME%" -F -w --uac-admin --noupx "%MAIN_FILE%" --icon=assets/icon.ico --add-data "images;images" --add-data "assets;assets" --add-data "onnx_models;onnx_models" --hidden-import yaml --hidden-import onnxruntime --noconfirm

if errorlevel 1 (
    echo [ERROR] Build failed!
    if "%BUILD_TARGET%"=="xbox" call :restore_steam
    pause
    exit /b 1
)

REM Restore steam files if xbox build
if "%BUILD_TARGET%"=="xbox" call :restore_steam

echo.
echo [OK] Build complete: dist\%EXE_NAME%.exe
echo.
if "%BUILD_TARGET%"=="all" goto :eof
pause
goto :eof

:restore_steam
if exist input_handler_steam_bak.py (
    copy /y input_handler_steam_bak.py input_handler.py >nul
    del /f /q input_handler_steam_bak.py
)
if exist race_logic_steam_bak.py (
    copy /y race_logic_steam_bak.py race_logic.py >nul
    del /f /q race_logic_steam_bak.py
)
echo [INFO] Steam files restored.
goto :eof

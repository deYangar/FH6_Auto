@echo off
chcp 65001 >nul
cd /d "%~dp0"

set APP_NAME=FH6Auto
set MAIN_FILE=main.py
set BUILD_TARGET=%1
if "%BUILD_TARGET%"=="" set BUILD_TARGET=steam
set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE=.venv\Scripts\python.exe

echo.
echo ==============================
echo   FH6Auto Build [%BUILD_TARGET%]
echo ==============================
echo.

"%PYTHON_EXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.8+ required
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    "%PYTHON_EXE%" -m pip install pyinstaller
)

echo [INFO] Current version:
"%PYTHON_EXE%" -c "from config import CURRENT_VERSION; print(CURRENT_VERSION)"

echo [INFO] Check modules...
"%PYTHON_EXE%" -c "import config,constants,input_handler,vision,recovery,race_logic,buy_logic,cj_logic,sell_logic,anti_cheat,focus_hook_manager" 2>nul
if errorlevel 1 (
    echo [ERROR] Module import failed. Installing deps...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
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
echo [INFO] Xbox build will default to --platform xbox via runtime hook.
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

REM Xbox build 通过 runtime hook 自动设置 FH6_PLATFORM=xbox
set "RUNTIME_HOOK="
if "%BUILD_TARGET%"=="xbox" set "RUNTIME_HOOK=--runtime-hook runtime_hook_xbox.py"

echo [INFO] Building with PyInstaller (platform=%BUILD_TARGET%)...
"%PYTHON_EXE%" -m PyInstaller -n "%EXE_NAME%" -F -w --uac-admin --noupx "%MAIN_FILE%" %RUNTIME_HOOK% --icon=assets/icon.ico --add-data "images;images" --add-data "assets;assets" --add-data "onnx_models;onnx_models" --hidden-import yaml --hidden-import onnxruntime --hidden-import input_handler --hidden-import input_handler_xbox --hidden-import race_logic --hidden-import race_logic_xbox --noconfirm

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [OK] Build complete: dist\%EXE_NAME%.exe
echo.
if "%BUILD_TARGET%"=="all" goto :eof
pause
goto :eof

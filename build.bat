@echo off
chcp 65001 >nul
cd /d "%~dp0"

set APP_NAME=FH6Auto
set MAIN_FILE=main.py

REM UPX 压缩路径
set PATH=C:\upx\upx-4.2.4-win64;%PATH%

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
python -c "from config import CURRENT_VERSION; print(CURRENT_VERSION)"

echo [INFO] Clean old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [INFO] Check modules...
python -c "import config,constants,input_handler,vision,recovery,race_logic,buy_logic,cj_logic,sell_logic,anti_cheat,focus_hook_manager" 2>nul
if errorlevel 1 (
    echo [ERROR] Module import failed. Installing deps...
    python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo [INFO] Building with PyInstaller (UPX enabled)...
python -m PyInstaller "%APP_NAME%.spec" --noconfirm

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [OK] Build complete: dist\%APP_NAME%.exe
echo.
pause

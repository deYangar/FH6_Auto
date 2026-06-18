@echo off
chcp 65001 >nul 2>&1
echo === Game Window Tester Build Script ===
echo.

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [Install] PyInstaller...
    pip install pyinstaller
)

REM Check dependencies
pip show pywin32 >nul 2>&1
if errorlevel 1 (
    echo [Install] pywin32...
    pip install pywin32
)

pip show Pillow >nul 2>&1
if errorlevel 1 (
    echo [Install] Pillow...
    pip install Pillow
)

pip show numpy >nul 2>&1
if errorlevel 1 (
    echo [Install] numpy...
    pip install numpy
)

echo.
echo [Build] Compiling to exe...
pyinstaller --onefile --windowed --name "GameWindowTester" --clean game_window_tester.py

echo.
if exist dist\GameWindowTester.exe (
    echo [OK] Build successful!
    echo      Output: dist\GameWindowTester.exe
) else (
    echo [FAIL] Build failed, check errors above
)

pause

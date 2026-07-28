@echo off
setlocal
cd /d "%~dp0"
title FH6 YOLO - 标注工作台

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [i] 环境未安装，先自动运行 setup ...
    call "%~dp0setup.bat"
)
if not exist "%VENV_PY%" (
    echo [X] 环境仍缺失，工作台无法启动。
    pause
    exit /b 1
)

:: 用法: 标注工作台.bat [--port 5678] [--host 127.0.0.1]
echo ==========================================
echo   FH6 YOLO 标注工作台（截图 + 标注 + 模型打标）
echo   浏览器会自动打开，停止服务: 关闭本窗口或 Ctrl+C
echo ==========================================
echo.
"%VENV_PY%" "%~dp0label_server.py" %*

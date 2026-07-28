@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: 双击检测：纯变量替换，不用管道、不起子进程，
:: 避开 cmd 管道重读 bug；延迟展开避免 CMDCMDLINE 里的 && 被二次解析
set "_INTERACTIVE=0"
set "_CL=!CMDCMDLINE!"
if not "!_CL:%~f0=!"=="!_CL!" set "_INTERACTIVE=1"

title FH6 YOLO - 导出 ONNX

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [i] 环境未安装，先自动运行 setup ...
    call "%~dp0setup.bat"
)
if not exist "%VENV_PY%" (
    echo [X] 环境仍缺失，导出终止。
    if "%_INTERACTIVE%"=="1" pause
    exit /b 1
)

:: 用法: export.bat [best.pt路径]
:: 不给参数时自动选择 models\runs 下最新的 best.pt
"%VENV_PY%" "%~dp0export_onnx.py" %*
set "RC=%ERRORLEVEL%"

if "%_INTERACTIVE%"=="1" pause
exit /b %RC%

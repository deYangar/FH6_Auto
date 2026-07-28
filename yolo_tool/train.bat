@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: 双击检测：纯变量替换，不用管道、不起子进程，
:: 避开 cmd 管道重读 bug；延迟展开避免 CMDCMDLINE 里的 && 被二次解析
set "_INTERACTIVE=0"
set "_CL=!CMDCMDLINE!"
if not "!_CL:%~f0=!"=="!_CL!" set "_INTERACTIVE=1"

title FH6 YOLO - 训练

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

:: 没有环境就自动装
if not exist "%VENV_PY%" (
    echo [i] 环境未安装，先自动运行 setup ...
    call "%~dp0setup.bat"
)
if not exist "%VENV_PY%" (
    echo [X] 环境仍缺失，训练终止。
    if "%_INTERACTIVE%"=="1" pause
    exit /b 1
)

:: 用法: train.bat [model] [epochs] [imgsz] [batch] [--device auto^|0^|cpu] [--no-export]
:: 默认: yolo26s.pt 100 640 自动(GPU=16/CPU=8)
:: train.py 会自动重建数据集并刷新 dataset.yaml，训完自动导出 ONNX（产物 models\best.pt / best.onnx）
"%VENV_PY%" "%~dp0train.py" %*
set "RC=%ERRORLEVEL%"

if "%_INTERACTIVE%"=="1" pause
exit /b %RC%

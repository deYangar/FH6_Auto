@echo off
setlocal
cd /d "%~dp0"
title FH6 YOLO - 一键训练

echo ==========================================
echo   FH6 YOLO 一键训练（s 模型）
echo   流程: 环境检查 -^> 构建数据集 -^> 训练 -^> 导出 ONNX
echo   可选参数: [epochs] [imgsz] [batch]，例如 一键训练.bat 50 640 16
echo ==========================================

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo.
    echo [i] 环境缺失，自动安装中 ...
    call "%~dp0setup.bat"
)
if not exist "%VENV_PY%" (
    echo.
    echo [X] 环境仍缺失，训练终止。
    pause
    exit /b 1
)

:: 有 models\best.pt 就续训，没有就从零开始
set "MODEL=yolo26s.pt"
if exist "%~dp0models\best.pt" set "MODEL=models\best.pt"
if not exist "%~dp0%MODEL%" (
    echo.
    echo [X] 找不到 %MODEL% - 连 yolo26s.pt 都没有，请检查安装包完整性
    pause
    exit /b 1
)
if "%MODEL%"=="models\best.pt" (
    echo.
    echo [i] 检测到 models\best.pt，将基于上次结果续训（自动降 lr 防震荡）
    echo     从零重练请用: train.bat yolo26s.pt 100
) else (
    echo.
    echo [i] 未发现历史权重，将从零开始训练 yolo26s.pt
)

call "%~dp0train.bat" %MODEL% %*
set "RC=%ERRORLEVEL%"

echo.
echo ==========================================
if "%RC%"=="0" (
    echo   训练完成！产物: models\best.pt 和 models\best.onnx
) else (
    echo   训练失败，错误码 %RC%。请检查上方报错信息。
)
echo ==========================================
pause
exit /b %RC%

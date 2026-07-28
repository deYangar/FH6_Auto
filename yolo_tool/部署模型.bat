@echo off
setlocal
cd /d "%~dp0"
title 部署 YOLO 模型到主项目

set "SRC=%~dp0dist\FH6_YOLO_Training_Kit\models\best.onnx"
set "DST=%~dp0..\onnx_models\yolo_best.onnx"

if not exist "%SRC%" (
    echo [X] 没找到训练好的模型: %SRC%
    echo     先双击「一键训练.bat」训练一轮。
    pause
    exit /b 1
)

if not exist "%~dp0..\onnx_models" mkdir "%~dp0..\onnx_models"
copy /Y "%SRC%" "%DST%" >nul
echo [OK] 已部署: %DST%
echo     主项目 config.json 设 "use_yolo": true 即可启用。
pause

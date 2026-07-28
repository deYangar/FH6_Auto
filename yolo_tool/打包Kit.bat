@echo off
setlocal
cd /d "%~dp0"
title FH6 YOLO - 打包 Training Kit

set "DST=%~dp0dist\FH6_YOLO_Training_Kit"

echo ==========================================
echo   打包 FH6_YOLO_Training_Kit
echo   源:   %~dp0
echo   目标: %DST%
echo ==========================================
echo.

if not exist "%DST%" mkdir "%DST%"

:: 顶层脚本与文档（排除打包脚本自身）
robocopy "%~dp0." "%DST%" *.bat *.py *.md *.pt /XF 打包Kit.bat /R:1 /W:1 /NJH /NJS /NDL
:: 数据与资源目录（/PURGE 保证目标和源头一致）
robocopy "%~dp0raw" "%DST%\raw" /E /PURGE /R:1 /W:1 /NJH /NJS /NDL
robocopy "%~dp0config" "%DST%\config" /E /PURGE /R:1 /W:1 /NJH /NJS /NDL
robocopy "%~dp0templates" "%DST%\templates" /E /PURGE /R:1 /W:1 /NJH /NJS /NDL

echo.
echo ==========================================
echo   [OK] 打包完成: %DST%
echo   分发说明: 整个文件夹拷到训练机即可。
echo   目标文件夹里的 .venv / models / data 是训练机本地产物，
echo   本脚本不会动它们；首次在新机器运行会自动装环境。
echo ==========================================
pause

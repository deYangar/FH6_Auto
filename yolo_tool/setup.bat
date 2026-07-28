@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: 双击检测：纯变量替换，不用管道、不起子进程，
:: 避开 cmd 管道重读 bug；延迟展开避免 CMDCMDLINE 里的 && 被二次解析
set "_INTERACTIVE=0"
set "_CL=!CMDCMDLINE!"
if not "!_CL:%~f0=!"=="!_CL!" set "_INTERACTIVE=1"

title FH6 YOLO - 环境安装

echo ==========================================
echo   FH6 YOLO 训练环境安装
echo   目录: %~dp0
echo ==========================================

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

:: 已有 .venv 先验证可用性。
:: 从别的机器整体拷贝过来的 venv 写死了旧 Python 路径，必须重建。
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; sys.exit(0)" >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo [i] 检测到已有 .venv 环境，跳过创建。
        echo     想彻底重装请先删除 .venv 文件夹。
        goto install_deps
    )
    echo.
    echo [i] 现有 .venv 不可用 - 通常是整个文件夹从别的电脑拷过来导致的，
    echo     正在自动重建 ...
    rmdir /s /q "%~dp0.venv"
)

:: ---------- 1. 查找 Python 3.10~3.13 ----------
echo.
echo [1/4] 查找 Python 3.10~3.13 ...
call :find_python
if not defined PYEXE (
    echo.
    echo [X] 未找到 Python 3.10~3.13。
    echo     请到 https://www.python.org/downloads/ 安装 Python 3.12，
    echo     安装时务必勾选 "Add python.exe to PATH"。
    echo     Python 3.14 太新，PyTorch 还不支持。
    goto fail
)
echo       使用: %PYEXE%

:: ---------- 2. 创建虚拟环境 ----------
echo.
echo [2/4] 创建虚拟环境 .venv ...
"%PYEXE%" -m venv "%~dp0.venv"
if errorlevel 1 (
    echo [X] 虚拟环境创建失败
    goto fail
)
"%VENV_PY%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1

:install_deps
:: ---------- 3. PyTorch - 自动识别 N 卡 ----------
echo.
echo [3/4] 检测显卡并安装 PyTorch ...
set "HAS_NVIDIA=0"
powershell -NoProfile -Command "if ((Get-CimInstance Win32_VideoController).Name -match 'NVIDIA') { exit 0 } else { exit 1 }" && set "HAS_NVIDIA=1"
if "%HAS_NVIDIA%"=="1" echo       检测到 NVIDIA 显卡 -^> 安装 CUDA 版 PyTorch
if not "%HAS_NVIDIA%"=="1" echo       未检测到 NVIDIA 显卡 -^> 安装 CPU 版 PyTorch
if "%HAS_NVIDIA%"=="1" goto torch_cuda

:torch_cpu
"%VENV_PY%" -m pip install --upgrade torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple && goto torch_ok
echo [X] PyTorch 安装失败，请检查网络
goto fail

:: CUDA 版策略：cu130 -^> cu128 -^> cu126，官方源优先，清华镜像兜底。
:: RTX 50 系是 Blackwell 架构 sm_120，cu126 里没有它的 kernel，必须 cu128 起步。
:: 每一档装完都真实跑一次 CUDA kernel 验证，装上了但跑不了就自动换下一档。
:: N 卡机器绝不静默回退 CPU 版，装不上就大声报错。
:torch_cuda
echo       [1] 尝试官方 cu130 - RTX 40/50 系，需驱动 580+ ...
"%VENV_PY%" -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu130 && "%VENV_PY%" -c "import torch; torch.zeros(1, device='cuda')" && goto torch_ok
echo       [2] cu130 不可用，尝试官方 cu128 - RTX 40/50 系，需驱动 570+ ...
"%VENV_PY%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128 && "%VENV_PY%" -c "import torch; torch.zeros(1, device='cuda')" && goto torch_ok
echo       [3] cu128 不可用，尝试官方 cu126 - RTX 20/30/40 系 ...
"%VENV_PY%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126 && "%VENV_PY%" -c "import torch; torch.zeros(1, device='cuda')" && goto torch_ok
echo       [4] 官方源全失败，尝试清华镜像 cu126 ...
"%VENV_PY%" -m pip install --force-reinstall torch torchvision --index-url https://mirrors.tuna.tsinghua.edu.cn/pytorch-wheels/cu126 && "%VENV_PY%" -c "import torch; torch.zeros(1, device='cuda')" && goto torch_ok
echo [X] PyTorch CUDA 版全部失败，或显卡/驱动不受支持。
echo     RTX 50 系显卡需要最新 NVIDIA 驱动，更新后重跑。
echo     CUDA 版约 3GB，需要稳定网络。
goto fail

:torch_ok
:: ---------- 4. 其余依赖 ----------
echo.
echo [4/4] 安装 ultralytics / flask / onnx / onnxruntime / pywin32 ...
"%VENV_PY%" -m pip install ultralytics flask onnx onnxruntime pywin32 -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [X] 依赖安装失败
    goto fail
)

:: ---------- 验证 ----------
echo.
echo ==========================================
echo   环境验证
echo ==========================================
"%VENV_PY%" -c "import torch; print('[OK] torch', torch.__version__, '| CUDA 可用:', torch.cuda.is_available())"
"%VENV_PY%" -c "import torch; print('     显卡:', torch.cuda.get_device_name(0)) if torch.cuda.is_available() else print('     显卡: 无，将使用 CPU 训练')"
"%VENV_PY%" -c "import ultralytics; print('[OK] ultralytics', ultralytics.__version__)"
"%VENV_PY%" -c "import flask, onnx, onnxruntime; print('[OK] flask / onnx / onnxruntime')"
"%VENV_PY%" -c "import win32gui; print('[OK] pywin32 截图模块')"
if "%HAS_NVIDIA%"=="1" "%VENV_PY%" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" || echo [!] 警告: 检测到 N 卡但 CUDA 不可用 - 请更新到最新 NVIDIA 驱动。

echo.
echo ==========================================
echo   [OK] 环境安装完成！
echo   下一步: 双击运行 一键训练.bat
echo ==========================================
if "%_INTERACTIVE%"=="1" pause
exit /b 0

:fail
echo.
echo [X] 安装失败，请检查上面的错误信息。
if "%_INTERACTIVE%"=="1" pause
exit /b 1

:: ---------- 子过程：查找合适的 Python ----------
:: 顺序: py 启动器 -^> PATH 里的 python -^> 常见安装目录 -^> conda 的 python
:find_python
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PYEXE (
        for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
    )
)
if not defined PYEXE (
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable if (3, 10) <= sys.version_info[:2] < (3, 14) else '')" 2^>nul') do set "PYEXE=%%P"
)
if not defined PYEXE (
    for %%D in (312 313 311 310) do (
        if not defined PYEXE (
            if exist "%LOCALAPPDATA%\Programs\Python\Python%%D\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%D\python.exe"
            if exist "%ProgramFiles%\Python%%D\python.exe" set "PYEXE=%ProgramFiles%\Python%%D\python.exe"
            if exist "C:\Python%%D\python.exe" set "PYEXE=C:\Python%%D\python.exe"
        )
    )
)
if not defined PYEXE (
    for %%C in ("%USERPROFILE%\miniconda3\python.exe" "%USERPROFILE%\anaconda3\python.exe" "%ProgramData%\miniconda3\python.exe" "%ProgramData%\anaconda3\python.exe") do (
        if not defined PYEXE if exist %%C (
            for /f "delims=" %%P in ('%%C -c "import sys; print(sys.executable if (3, 10) <= sys.version_info[:2] < (3, 14) else '')" 2^>nul') do set "PYEXE=%%P"
        )
    )
)
exit /b 0

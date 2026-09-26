@echo off
title Poka-Yoke - install torch (GPU) + ultralytics
cd /d "%~dp0"
chcp 65001 >nul
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || goto :nopy
echo Using: %PY%
%PY% --version
echo.

echo [1/4] NVIDIA driver / GPU
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>nul
if errorlevel 1 goto :nodriver
set "CU=cu126"
nvidia-smi --query-gpu=name --format=csv,noheader | findstr /i /c:"RTX 50" /c:"RTX PRO" /c:"Blackwell" >nul && set "CU=cu128"
echo     using PyTorch build: %CU%
echo.

echo [2/4] removing any CPU-only torch ...
%PY% -m pip uninstall -y torch torchvision torchaudio >nul 2>nul
echo.

echo [3/4] installing torch + torchvision (%CU%, about 3 GB, 5-15 min) ...
%PY% -m pip install torch torchvision --index-url https://download.pytorch.org/whl/%CU% || goto :fail
echo.

echo [4/4] installing ultralytics + checking the GPU from Python ...
%PY% -m pip install ultralytics || goto :fail
%PY% -c "import torch; ok=torch.cuda.is_available(); print('  torch', torch.__version__, '| CUDA', torch.version.cuda, '| GPU:', torch.cuda.get_device_name(0) if ok else 'NOT AVAILABLE')"
echo.
echo === Done. Now run run_train_obb.cmd
goto :end

:nodriver
echo === nvidia-smi not found: the NVIDIA driver is not installed (or this PC has no NVIDIA GPU).
echo     Install the latest driver from https://www.nvidia.com/Download/index.aspx , reboot, then run this again.
goto :end
:fail
echo.
echo === install failed. Copy the message above and send it to Claude.
goto :end
:nopy
echo === Python not found.
:end
echo.
pause

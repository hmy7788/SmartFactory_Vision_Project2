@echo off
title Poka-Yoke - laptop setup (CPU, one time)
cd /d "%~dp0"
chcp 65001 >nul
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || goto :nopy
echo Using: %PY%
%PY% --version
echo.
echo [1/2] installing packages (ultralytics + CPU torch, opencv, fastapi, uvicorn) - about 5-10 min, ~1 GB ...
%PY% -m pip install --upgrade pip
%PY% -m pip install ultralytics opencv-python numpy fastapi "uvicorn[standard]" || goto :fail
echo.
echo [2/2] checking ...
%PY% -c "import torch, ultralytics, cv2, fastapi, uvicorn; print('  torch', torch.__version__, '| ultralytics', ultralytics.__version__, '| opencv', cv2.__version__, '| OK')" || goto :fail
if exist model\yolo_obb_parts.pt (echo   weights: model\yolo_obb_parts.pt  OK) else (echo   !! model\yolo_obb_parts.pt is missing - copy it into the model folder)
echo.
echo === Done. Now double-click run_demo.cmd
goto :end
:nopy
echo === Python is not installed.
echo     1) https://www.python.org/downloads/  -> download Python 3.12
echo     2) On the FIRST install screen, tick  "Add python.exe to PATH"  then Install Now
echo     3) Close this window and run setup_laptop.cmd again
goto :end
:fail
echo.
echo === install failed. Copy the message above and send it to Claude.
:end
echo.
pause

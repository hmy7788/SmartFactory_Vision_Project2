@echo off
title Poka-Yoke - DEMO (built-in webcam + YOLO-OBB, port 8000)
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || goto :nopy
if not exist model\yolo_obb_parts.pt goto :nopt

echo [1/3] checking the weights ...
%PY% -m scripts.check_weights model\yolo_obb_parts.pt || goto :fail
echo.
echo [2/3] cameras on this laptop:
%PY% -m scripts.list_cameras
set "CAM=0"
set /p CAM="Camera number to use (built-in webcam is usually 0) [0]: "
echo.
echo [3/3] starting.  Browser: http://localhost:8000    Stop: Ctrl+C in this window
start "" http://localhost:8000
rem OBB model gives angles itself - no --refine-angles. imgsz 480 = faster on CPU.
%PY% -m web.server --source camera --camera %CAM% --camera-size 1280x720 --weights model\yolo_obb_parts.pt --imgsz 480
goto :end
:nopt
echo === model\yolo_obb_parts.pt is missing. Copy the weights into the model folder.
goto :end
:nopy
echo === Python not found. Run setup_laptop.cmd first (it explains how to install Python).
goto :end
:fail
echo.
echo === Something failed above. Send the message to Claude.
:end
echo.
pause

@echo off
title Poka-Yoke UI - run with any detection model
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
rem Usage
rem   double-click            : pick a .pt from the model folder, pick a camera, browser opens
rem   drag a .pt onto this    : run the UI with that model (webcam)
rem   drag a .pt + a video    : run the UI on the recorded video instead of the webcam
rem   more options            : run_ui.cmd model\my.pt --imgsz 480 --port 8001   (see scripts\run_ui.py)
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || goto :nopy
%PY% -c "import ultralytics, cv2, fastapi, uvicorn" >nul 2>nul || goto :install
:run
%PY% -m scripts.run_ui %*
goto :end
:install
echo === First run: installing ultralytics + CPU torch, opencv, fastapi, uvicorn (5-10 min, about 1 GB) ...
%PY% -m pip install ultralytics opencv-python numpy fastapi "uvicorn[standard]" || goto :fail
goto :run
:nopy
echo === Python is not installed.
echo     https://www.python.org/downloads/  -> Python 3.12, tick "Add python.exe to PATH" on the first screen
goto :end
:fail
echo.
echo === install failed - see the message above.
:end
echo.
pause

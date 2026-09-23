@echo off
title Poka-Yoke - LIVE (camera + model, port 8000)
cd /d "%~dp0"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || set "PY=%USERPROFILE%\anaconda3\python.exe"
%PY% --version >nul 2>nul || set "PY=%USERPROFILE%\miniforge3\python.exe"
%PY% --version >nul 2>nul || goto :nopy
echo Using: %PY%
%PY% --version
echo.

rem --- find the weights: first .pt in model\ ; if none, take ..\best.pt (vision2\best.pt) ---
if not exist model mkdir model
set "W="
for %%F in (model\*.pt) do if not defined W set "W=%%F"
if not defined W if exist "..\best.pt" (
  echo Copying ..\best.pt to model\best.pt
  copy /y "..\best.pt" "model\best.pt" >nul
  set "W=model\best.pt"
)
if not defined W goto :nopt
echo Weights: %W%
echo.

echo [1/3] checking the weights (task, class names, one test image) ...
%PY% -m scripts.check_weights "%W%" || goto :badpt
echo.

echo [2/3] cameras:
%PY% -m scripts.list_cameras
set "CAM=0"
set /p CAM="Camera number to use [0]: "
echo.

set "TILT="
set /p TILT="Tilt mode (estimate angles from the image, for parts placed askew)? y/N: "
set "EXTRA="
if /i "%TILT%"=="y" set "EXTRA=--refine-angles"

echo [3/3] starting.  Browser: http://localhost:8000   Stop: Ctrl+C here
echo      If run_ui.cmd (demo) is still open, close it first - same port.
start "" http://localhost:8000
rem imgsz 480: CPU inference ~2x faster than 640 (RT-DETR-l is heavy). Video streams at camera speed regardless.
%PY% -m web.server --source camera --camera %CAM% --camera-size 1280x720 --weights "%W%" --imgsz 480 %EXTRA%
goto :end

:nopt
echo === No .pt file in the model\ folder. Copy the weights there (any name, e.g. model\best.pt) and run again.
goto :end
:badpt
echo.
echo === The weights did not pass the check above. Fix it (or send the message to Claude), then run again.
goto :end
:nopy
echo === Python not found. Open Anaconda Prompt in this folder and run:  python -m web.server --source camera
:end
echo.
pause

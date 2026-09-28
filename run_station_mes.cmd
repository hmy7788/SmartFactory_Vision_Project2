@echo off
title Poka-Yoke - STATION + MES (MQTT)  port 8000
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
rem  Station screen linked to the MES: the MES work order decides recipe and quantity, [Complete] reports each product.
rem  Needs first: mes\run_broker.cmd (Mosquitto, port 1883) and mes\run_mes_light.cmd (MES, port 8080) - or run_mes_demo.cmd for all three
rem  Usage: double-click = pick a .pt from model\ and a camera.  Drag a .pt (and/or a video) onto this file to use those.
rem         RT-DETR is the default model type. For a YOLO-OBB weight add:  --model-type yolo-obb
set "BROKER=localhost:1883"
set "STATION=VIS-01"
rem --- python: the GPU venv from the YOLO comparison if it has CUDA (RT-DETR is ~10x faster there), else the normal one
set "PY=python"
set "GPUPY=%USERPROFILE%\venv_yolo26\Scripts\python.exe"
if not exist "%GPUPY%" goto :cpu
"%GPUPY%" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>nul
if errorlevel 1 goto :cpu
set "PY=%GPUPY%"
echo Using the GPU python: %PY%
goto :deps
:cpu
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || goto :nopy
echo Using: %PY% (CPU)
:deps
"%PY%" -c "import ultralytics, cv2, fastapi, uvicorn, paho.mqtt" >nul 2>nul
if not errorlevel 1 goto :run
echo installing packages (first time only) ...
"%PY%" -m pip install ultralytics opencv-python fastapi "uvicorn[standard]" "paho-mqtt>=2.0"
if errorlevel 1 goto :fail
:run
echo Broker: %BROKER%   Station: %STATION%   topics factory/%STATION%/...
"%PY%" -m scripts.run_ui %* --mes-broker %BROKER% --station %STATION%
goto :end
:nopy
echo === Python not found.
goto :end
:fail
echo === install failed - see the message above.
:end
echo.
pause

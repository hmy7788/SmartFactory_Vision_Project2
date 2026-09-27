@echo off
title Poka-Yoke - STATION + MES (MQTT)  port 8000
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || goto :nopy
rem  Usage: drag a video onto this file, or double-click and drag the video into the window when asked.
rem  Needs: Mosquitto on this PC (port 1883) and the MES (smartfactory-mes\run_mes.cmd) running.
set "BROKER=localhost:1883"
set "STATION=VIS-01"
%PY% -c "import paho.mqtt" 2>nul
if errorlevel 1 goto :install
:installed
if not exist model\yolo_obb_parts.pt goto :nopt
set "VID=%~1"
if not "%VID%"=="" goto :havevid
echo.
echo Drag the ORIGINAL video file into this window and press Enter.
echo Just press Enter to use the webcam instead.
set /p VID="Video: "
:havevid
set "VID=%VID:"=%"
echo Broker:  %BROKER%   Station: %STATION%   topics factory/%STATION%/...
echo Browser: http://localhost:8000     Stop: Ctrl+C
start "" http://localhost:8000
if "%VID%"=="" goto :webcam
if not exist "%VID%" goto :novid
echo Video:   %VID%
%PY% -m web.server --video "%VID%" --weights model\yolo_obb_parts.pt --imgsz 480 --mes-broker %BROKER% --station %STATION%
goto :end
:webcam
%PY% -m web.server --source camera --camera 0 --weights model\yolo_obb_parts.pt --imgsz 480 --mes-broker %BROKER% --station %STATION%
goto :end
:install
echo installing paho-mqtt ...
%PY% -m pip install "paho-mqtt>=2.0"
if errorlevel 1 goto :fail
goto :installed
:novid
echo === Video not found: %VID%
goto :end
:nopt
echo === model\yolo_obb_parts.pt is missing.
goto :end
:nopy
echo === Python not found.
goto :end
:fail
echo === install failed. Send the message above to Claude.
:end
echo.
pause

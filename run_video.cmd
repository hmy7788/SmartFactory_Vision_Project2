@echo off
title Poka-Yoke - assembly VIDEO in the web UI (port 8000)
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
rem  Usage: drag a video file (mp4/avi/mov) onto this file, or:  run_video.cmd C:\path\video.mp4
set "VID=%~1"
if "%VID%"=="" set /p VID="Video file path (you can drag the file into this window): "
set "VID=%VID:"=%"
if not exist "%VID%" goto :novid
set "W=model\yolo_obb_parts.pt"
if not exist "%W%" goto :nopt
echo Video:   %VID%
echo Weights: %W%
echo Browser: http://localhost:8000   (pick the recipe that matches the video in the top bar)   Stop: Ctrl+C
start "" http://localhost:8000
%PY% -m web.server --video "%VID%" --weights "%W%" --imgsz 480
goto :end
:novid
echo === Video not found: %VID%
goto :end
:nopt
echo === %W% is missing.
:end
echo.
pause

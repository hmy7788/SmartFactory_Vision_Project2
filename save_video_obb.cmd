@echo off
title Poka-Yoke - draw YOLO-OBB boxes on a video (saves mp4)
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
rem  Usage: drag a video file onto this file. Output: runs\obb_infer\<name>_obb.mp4
set "VID=%~1"
if "%VID%"=="" set /p VID="Video file path (you can drag the file into this window): "
set "VID=%VID:"=%"
if not exist "%VID%" goto :novid
%PY% -m src.detection.realtime_inference --source "%VID%" --save --no-window || goto :fail
echo.
echo === Done. Opening the output folder ...
start "" "runs\obb_infer"
goto :end
:novid
echo === Video not found: %VID%
goto :end
:fail
echo === Something failed above. Send the message to Claude.
:end
echo.
pause

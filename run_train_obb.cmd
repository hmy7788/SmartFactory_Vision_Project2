@echo off
title Poka-Yoke - train YOLO-OBB (parts detector)
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=python"
%PY% --version >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul || set "PY=%USERPROFILE%\anaconda3\python.exe"
%PY% --version >nul 2>nul || set "PY=%USERPROFILE%\miniforge3\python.exe"
%PY% --version >nul 2>nul || goto :nopy
echo Using: %PY%
%PY% --version
echo.

rem ---- arguments:  run_train_obb.cmd [labels_dir] [images_dir] [epochs] ----
set "LABELS=%~1"
set "IMAGES=%~2"
set "EPOCHS=%~3"
if "%EPOCHS%"=="" set "EPOCHS=100"
if "%LABELS%"=="" for /d %%D in ("..\labels-*") do if "%LABELS%"=="" set "LABELS=%%~fD"
if "%LABELS%"=="" for /d %%D in ("..\labels") do if "%LABELS%"=="" set "LABELS=%%~fD"
if "%LABELS%"=="" goto :nolabels
if "%IMAGES%"=="" if exist "..\aabb\images\train" set "IMAGES=..\aabb\images"
if "%IMAGES%"=="" if exist "..\images\train" set "IMAGES=..\images"
echo Labels: %LABELS%
if not "%IMAGES%"=="" (echo Images: %IMAGES%) else (echo Images: will be searched next to this folder)
echo Epochs: %EPOCHS%
echo.

echo [1/4] torch / ultralytics present?
%PY% -c "import torch; print('  torch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none (CPU)')" || goto :notorch
%PY% -c "import ultralytics; print('  ultralytics', ultralytics.__version__)" 2>nul
if errorlevel 1 (
  echo   ultralytics not found - installing ...
  %PY% -m pip install ultralytics || goto :fail
)
echo.

echo [2/4] building the dataset folder (data\dataset_obb) ...
if "%IMAGES%"=="" (
  %PY% -m src.detection.prepare_obb_dataset --labels "%LABELS%" || goto :fail
) else (
  %PY% -m src.detection.prepare_obb_dataset --labels "%LABELS%" --images "%IMAGES%" || goto :fail
)
echo.

echo [3/4] training YOLO-OBB (%EPOCHS% epochs; GPU ~10-20 min, CPU: hours)
echo       log: reports\detection_obb\train_log.txt   run dir: runs\obb\yolo_obb_parts\
%PY% -m src.detection.train_yolo_obb --epochs %EPOCHS% || goto :fail
echo.

echo [4/4] done. (test evaluation + CPU speed ran at the end of training)
echo === weights: model\yolo_obb_parts.pt
echo     report:  reports\detection_obb\report.md  (tables for the slides), metrics.json, test_val_batch0_pred.jpg
echo     live:    run_ui.cmd  (web UI - reads model\yolo_obb_parts.pt)   or   python -m src.detection.realtime_inference
goto :end

:nolabels
echo === OBB label folder not found. Put the Drive folder (labels-...) next to this folder, or pass it:
echo     run_train_obb.cmd C:\path\to\labels C:\path\to\images 100
goto :end
:notorch
echo === torch is missing. Install the CUDA build first:  https://pytorch.org/get-started/locally/
echo     (e.g.  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 )
goto :end
:fail
echo.
echo === Something failed above. Copy the message (or reports\detection_obb\train_log.txt) and send it to Claude.
goto :end
:nopy
echo === Python not found. Open Anaconda Prompt in this folder and run:  python -m src.detection.train_yolo_obb
:end
echo.
pause

@echo off
title Poka-Yoke - train YOLO-OBB (batch 8, dataset already built)
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
rem  4GB GPU (GTX 1650 etc): batch 8 fits in video memory. Dataset folder data\dataset_obb must exist (run_train_obb.cmd made it).
python -m src.detection.train_yolo_obb --batch 8 %*
echo.
echo === finished. report: reports\detection_obb\report.md
pause

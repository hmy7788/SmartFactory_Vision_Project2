@echo off
title Poka-Yoke - train the assembly classifier (ResNet-18)
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

rem --- where the photos are: ..\aabb (images\train, images\test with model_a_001.png ...) ---
set "DATA=..\aabb"
if not "%~1"=="" set "DATA=%~1"
if not exist "%DATA%\images\train" goto :nodata
echo Data: %DATA%
echo.

echo [1/4] torch / torchvision present?
%PY% -c "import torch, torchvision; print('  torch', torch.__version__, '| torchvision', torchvision.__version__, '| cuda' if torch.cuda.is_available() else '| cpu')" || goto :notorch
echo.

echo [2/4] smoke test on fake data (about 20-40 s) ...
%PY% -m src.classification.train --smoke || goto :fail
echo.

echo [3/4] training ResNet-18 on the real photos (CPU: about 5-10 min, GPU: under 1 min)
echo       log: reports\classification\train_log.txt
%PY% -m src.classification.train --data "%DATA%" --out model\classifier_resnet18.pt --report-dir reports\classification || goto :fail
echo.

echo [4/4] evaluation on the test photos + Grad-CAM pictures
%PY% -m src.classification.evaluate --weights model\classifier_resnet18.pt --data "%DATA%" --report-dir reports\classification --gradcam 6 || goto :fail
echo.
echo === Done.  weights: model\classifier_resnet18.pt
echo            report:  reports\classification\  (report.md, confusion.png, gradcam\*.jpg, train_log.txt)
goto :end

:nodata
echo === Photos not found: %DATA%\images\train
echo     Expected the aabb folder next to this folder (vision2\aabb), or pass the path:  run_train_classifier.cmd C:\path\to\aabb
goto :end
:notorch
echo === torch is missing. Double-click install.cmd first.
goto :end
:fail
echo.
echo === Something failed above. The log is in reports\classification\train_log.txt - send the message to Claude.
goto :end
:nopy
echo === Python not found. Open Anaconda Prompt in this folder and run:  python -m src.classification.train --data ..\aabb
:end
echo.
pause

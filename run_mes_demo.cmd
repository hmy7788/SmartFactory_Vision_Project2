@echo off
title AEGIS demo - MQTT broker + MES + station
cd /d "%~dp0"
chcp 65001 >nul
rem  One click for the MES demo: MQTT broker (1883) + MES server (8080, its own window) + this station (8000).
rem  Needs: Java 17+ (Temurin 21), Mosquitto (Windows installer), Python with requirements.txt,
rem         and the RT-DETR weights in model\best.pt (not in git - see model\README.md).
rem  A broker / MES that is already running is kept (its work order queue stays).
netstat -ano | findstr /r /c:":1883 .*LISTENING" >nul || start "MQTT broker" "%~dp0mes\run_broker.cmd"
netstat -ano | findstr /r /c:":8080 .*LISTENING" >nul || start "MES server" "%~dp0mes\run_mes_light.cmd"
echo MES console : http://localhost:8080   (the first run builds the MES jar - a minute or two)
echo Station     : http://127.0.0.1:8000   (opens when the model is loaded)
echo.
if exist "model\best.pt" (call run_station_mes.cmd model\best.pt) else (call run_station_mes.cmd)

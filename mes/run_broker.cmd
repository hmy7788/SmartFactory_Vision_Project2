@echo off
title MQTT broker - Mosquitto port 1883
cd /d "%~dp0"
chcp 65001 >nul
netstat -ano | findstr /r /c:":1883 .*LISTENING" >nul
if not errorlevel 1 goto :running
set "MQ=C:\Program Files\mosquitto\mosquitto.exe"
if not exist "%MQ%" goto :nomq
if not exist mosquitto\data mkdir mosquitto\data
echo Broker: localhost:1883   config: mosquitto\mosquitto.conf   Stop: Ctrl+C
"%MQ%" -c mosquitto\mosquitto.conf -v
goto :end
:running
echo === Port 1883 is already in use: a broker is already running, probably the Mosquitto Windows service.
echo     Nothing to do - go on with run_mes.cmd
goto :end
:nomq
echo === Mosquitto is not installed.
echo     https://mosquitto.org/download/  - Windows 64-bit installer, then run this again.
echo     With Docker instead:  docker compose up -d
:end
echo.
pause

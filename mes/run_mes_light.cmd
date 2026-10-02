@echo off
title MES server - light mode, port 8080
cd /d "%~dp0"
chcp 65001 >nul
rem  run_mes.cmd (gradlew bootRun) keeps TWO Java processes: Gradle + the server.
rem  This one builds a jar once, stops Gradle, and runs only the server with a small heap.
powershell -NoProfile -Command "if ('%~dp0' -match '[^\x00-\x7F]') { exit 1 }" >nul 2>nul
if "%errorlevel%"=="1" goto :badpath
rem  A Windows account name with non-English letters puts the Gradle cache (%USERPROFILE%\.gradle) on a
rem  non-English path too, and Gradle fails there just like with the project path - use an English one.
if defined GRADLE_USER_HOME goto :gradlehome_ok
powershell -NoProfile -Command "if ($env:USERPROFILE -match '[^\x00-\x7F]') { exit 1 }" >nul 2>nul
if errorlevel 1 set "GRADLE_USER_HOME=%SystemDrive%\gradle_home"
:gradlehome_ok
java -version >nul 2>nul
if errorlevel 1 goto :nojava
set "JAR=build\libs\smartfactory-mes-0.1.0.jar"
if exist "%JAR%" goto :run
echo Building the jar once - a minute or two ...
call gradlew.bat bootJar --no-daemon -q
if errorlevel 1 goto :fail
:run
call gradlew.bat --stop >nul 2>nul
echo MES console: http://localhost:8080     Stop: Ctrl+C
echo After changing the code, delete build\libs or run: gradlew bootJar
start "" http://localhost:8080
java -Xms64m -Xmx384m -XX:+UseSerialGC -jar "%JAR%"
goto :end
:nojava
echo === Java 17+ not found. Install Temurin 21 from https://adoptium.net
goto :end
:fail
echo === build failed - see the message above
goto :end
:badpath
echo === This folder path has non-English characters. Clone/move the project to an English-only path.
:end
echo.
pause

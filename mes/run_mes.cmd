@echo off
title MES server - Spring Boot port 8080
cd /d "%~dp0"
chcp 65001 >nul
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
java -version 2>&1 | findstr /r /c:"version \"2[5-9]" >nul
if not errorlevel 1 echo === WARNING: Java 25 or newer found. This build needs JDK 17-24 - install Temurin 21.
echo MES console: http://localhost:8080      DB: http://localhost:8080/h2-console  JDBC URL jdbc:h2:file:./data/mes2  user sa
echo First run downloads Gradle and libraries - a few minutes.   Stop: Ctrl+C
start "" http://localhost:8080
call gradlew.bat bootRun
goto :end
:nojava
echo === Java - JDK 17 or newer - not found. Install Temurin 21 from https://adoptium.net
goto :end
:badpath
echo === This folder path has non-English characters:
echo     %~dp0
echo     Gradle cannot run the tests from such a path on Windows - ClassNotFoundException.
echo     Clone/move the project to an English-only path, for example C:\dev\SmartFactory_Vision_Project2
goto :end
:end
echo.
pause

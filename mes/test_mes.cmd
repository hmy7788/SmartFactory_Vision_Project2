@echo off
title MES tests
cd /d "%~dp0"
chcp 65001 >nul
powershell -NoProfile -Command "if ('%~dp0' -match '[^\x00-\x7F]') { exit 1 }" >nul 2>nul
if "%errorlevel%"=="1" goto :badpath
java -version >nul 2>nul
if errorlevel 1 goto :nojava
call gradlew.bat test
if errorlevel 1 goto :failed
echo.
echo === all tests passed
goto :end
:failed
echo.
echo === some tests failed - see above or build\reports\tests\test\index.html
goto :end
:nojava
echo === Java 17+ not found
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

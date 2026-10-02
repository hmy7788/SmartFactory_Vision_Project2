@echo off
title MES tests
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

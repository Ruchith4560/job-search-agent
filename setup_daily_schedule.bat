@echo off
title Configure Daily Scheduled Job Application Agent
cls
echo =================================================================
echo   Configure Automatic Daily Schedule for Job Application Agent
echo =================================================================
echo.
echo This script registers a daily Windows Scheduled Task that will
echo automatically launch your Job Application Agent every morning.
echo.
set /p SCHEDULE_TIME="Enter daily run time in 24-hr HH:MM format (default 06:00 IST): "
if "%SCHEDULE_TIME%"=="" set SCHEDULE_TIME=06:00

echo.
echo Registering Windows Scheduled Task 'JobApplicationAgent' for %SCHEDULE_TIME% daily...
schtasks /create /tn "JobApplicationAgent" /tr "\"%~dp0run_daily.bat\"" /sc daily /st %SCHEDULE_TIME% /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo =================================================================
    echo [SUCCESS] Scheduled Task 'JobApplicationAgent' registered!
    echo It will automatically run every day at %SCHEDULE_TIME%.
    echo.
    echo You can test it now by running: schtasks /run /tn "JobApplicationAgent"
    echo Or remove it anytime with:      schtasks /delete /tn "JobApplicationAgent" /f
    echo =================================================================
) else (
    echo.
    echo [NOTE] If registration requires administrator privileges,
    echo right-click this script and choose 'Run as administrator'.
)

echo.
pause

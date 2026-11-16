@echo off
title Configure Automatic Daily Schedule - AI Job Search Agent
cls
echo =================================================================
echo   Register Daily Automated Schedule (06:00 AM IST)
echo =================================================================
echo.
cd /d "%~dp0"

powershell -ExecutionPolicy Bypass -File "%~dp0register_schedule.ps1"

echo.
pause

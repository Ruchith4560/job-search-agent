@echo off
title AI Resume & Job Application Agent - Daily Run
cls
echo =================================================================
echo   AI Resume & Job Application Agent - Daily Auto-Apply Routine
echo   (Fetches, Scores, Tailors, Sends Email Digest, and Prepares Confirmations)
echo =================================================================
cd /d "%~dp0"

if not exist "data\output" mkdir "data\output"
set LOG_FILE=data\output\daily_run.log

echo [%DATE% %TIME%] Starting daily job search agent... >> "%LOG_FILE%"

if "%1"=="--scheduled" (
    .\.venv\Scripts\python.exe main.py daily --non-interactive >> "%LOG_FILE%" 2>&1
    echo [%DATE% %TIME%] Scheduled run finished with exit code %ERRORLEVEL%. >> "%LOG_FILE%"
) else (
    .\.venv\Scripts\python.exe main.py daily
    echo.
    pause
)

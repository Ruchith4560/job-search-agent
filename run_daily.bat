@echo off
title AI Resume & Job Application Agent - Automated Daily Run
cls
echo =================================================================
echo   AI Resume & Job Application Agent - Daily Auto-Apply Routine
echo   (Fetches, Scores, Tailors, Pre-fills, and Asks for Confirmation)
echo =================================================================
cd /d "%~dp0"

.\.venv\Scripts\python.exe main.py daily

echo.
pause

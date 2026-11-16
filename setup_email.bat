@echo off
title Configure Free Email Delivery - AI Job Search Agent
cls
echo =================================================================
echo   Configure Free Gmail Delivery for Daily Job Application Agent
echo =================================================================
echo.
echo NOTE: Sending emails via your personal Gmail is 100%% FREE OF COST.
echo No paid API, credit card, or subscription is needed.
echo.
cd /d "%~dp0"
.\.venv\Scripts\python.exe main.py setup-email

echo.
pause

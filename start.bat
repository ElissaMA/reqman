@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   ReqMan定检准备系统 V3.4.5
echo ================================================
python src\reqman\app.py
pause

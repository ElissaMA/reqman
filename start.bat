@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   定检需求单管理系统 V3.2.5
echo ================================================
python src\reqman\app.py
pause

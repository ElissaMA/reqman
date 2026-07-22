@echo off
cd /d "%~dp0"

echo ================================================
echo   Reqman V3 - Inspection Demand System
echo   Architecture: Factory + Blueprint + Service
echo ================================================

set PYTHONPATH=src
py src\reqman\app.py
pause

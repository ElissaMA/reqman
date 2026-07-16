@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================
echo   定检需求单管理系统 V3
echo   架构: 工厂模式 + 蓝图 + 服务层
echo ================================================

set PYTHONPATH=src
python src\reqman\app.py
pause

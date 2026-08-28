@echo off
rem 本批处理必须保存为 ANSI(GBK) 编码 + CRLF 换行，勿改为 UTF-8 —— 否则中文乱码且 cmd 解析错位
cd /d "%~dp0"
echo ================================================
echo   ReqMan定检准备系统 V3.4.5
echo ================================================
python src\reqman\app.py
pause

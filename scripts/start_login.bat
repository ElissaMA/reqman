@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0
set UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
set UV_PYTHON_INSTALL_MIRROR=https://mirrors.aliyun.com/python-release/
set PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright/
if not exist .runtime\venv\Scripts\python.exe (
    echo [首次使用] 正在自动安装运行环境，请稍候...
    where uv >nul 2>nul || (python -m pip install -q uv || py -m pip install -q uv)
    uv python install 3.11 || echo [警告] Python 安装失败
    uv venv .runtime\venv
    uv pip install --python .runtime\venv\Scripts\python.exe httpx playwright
    .runtime\venv\Scripts\python -m playwright install chromium
)
.runtime\venv\Scripts\python amro_login.py
if errorlevel 1 ( echo [登录未完成] 请查看上方错误信息 && pause )

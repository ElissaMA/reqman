@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set NO_PROXY=*
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
set UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone/
set PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright/
if not exist .runtime\.installed (
    echo [首次使用] 正在自动安装运行环境，请稍候...
    where python >nul 2>nul || (where py >nul 2>nul || goto :nopython)
    where uv >nul 2>nul || (python -m pip install -q uv || py -m pip install -q uv)
    if errorlevel 1 goto :fail
    uv python install 3.11
    if errorlevel 1 goto :fail
    uv venv .runtime\venv
    if errorlevel 1 goto :fail
    uv pip install --python .runtime\venv\Scripts\python.exe httpx playwright
    if errorlevel 1 goto :fail
    .runtime\venv\Scripts\python -m playwright install chromium
    if errorlevel 1 goto :fail
    echo done > .runtime\.installed
    echo [安装完成] 运行环境就绪
)
.runtime\venv\Scripts\python amro_login.py
if errorlevel 1 (
    echo [登录未完成] 请查看上方错误信息，本窗口可安全关闭
    goto :done
)
echo [已完成登录] 本窗口可安全关闭
goto :done

:nopython
echo [未检测到 Python] 请先安装 Python 3.11 后重新运行
pause
exit /b 1

:fail
echo [安装失败] 请检查网络连接后重新运行，或手动安装运行环境
pause
exit /b 1

:done
pause

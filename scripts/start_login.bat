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
rem venv 有效性校验（防拷贝 .runtime 后 trampoline 失效）
if not exist .runtime\venv\Scripts\python.exe goto :install
.runtime\venv\Scripts\python --version >nul 2>&1
if errorlevel 1 (
    echo [环境异常] 检测到损坏的运行环境，正在重建...
    rmdir /s /q .runtime
    goto :install
)
goto :run

:install
echo [首次使用] 正在自动安装运行环境，请稍候...
python --version >nul 2>&1 || (py --version >nul 2>&1 || goto :nopython)
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV where uv >nul 2>nul && set "UV=uv"
if not defined UV (
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 goto :fail
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
"%UV%" python install 3.11
if errorlevel 1 goto :fail
"%UV%" venv .runtime\venv
if errorlevel 1 goto :fail
"%UV%" pip install --python .runtime\venv\Scripts\python.exe httpx playwright
if errorlevel 1 goto :fail
.runtime\venv\Scripts\python -m playwright install chromium
if errorlevel 1 goto :fail
echo [安装完成] 运行环境就绪

:run
.runtime\venv\Scripts\python amro_login.py
if errorlevel 1 (
    echo [登录未完成] 请查看上方错误信息，本窗口可安全关闭
    goto :done
)
echo [已完成登录] 本窗口可安全关闭
goto :done

:nopython
echo [未检测到可用 Python] 本机未安装可用的 Python（Microsoft Store 存根不可用），请安装 Python 3.11 后重新运行
pause
exit /b 1

:fail
echo [安装失败] 可能是网络问题，请检查网络连接后重新运行，或手动安装运行环境
pause
exit /b 1

:done
pause

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
set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
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
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV where uv >nul 2>nul && set "UV=uv"
if not defined UV (
    echo [下载 uv] 使用 uv.agentsmirror.com 镜像源下载 uv（最快最稳）...
    powershell -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://uv.agentsmirror.com/github/astral-sh/uv/releases/download/0.12.5/uv-x86_64-pc-windows-msvc.zip' -OutFile '%TEMP%\uv.zip'; Expand-Archive -Path '%TEMP%\uv.zip' -DestinationPath '%USERPROFILE%\.local' -Force"
    if errorlevel 1 (
        echo [备用源] 镜像源不可达，改用官方安装脚本下载 uv...
        powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
        if errorlevel 1 goto :fail
    )
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
"%UV%" --version >nul 2>&1
if errorlevel 1 goto :fail
"%UV%" python install 3.11
if errorlevel 1 goto :fail
"%UV%" venv .runtime\venv
if errorlevel 1 goto :fail
"%UV%" pip install --python .runtime\venv\Scripts\python.exe httpx playwright
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


:fail
echo [安装失败] 可能是网络问题，请检查网络连接后重新运行，或手动安装运行环境
pause
exit /b 1

:done
pause

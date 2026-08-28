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
rem 定位 uv：本机已装 → PATH → 下载解压定位
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV where uv >nul 2>nul && set "UV=uv"
if not defined UV (
    echo [下载 uv] 正在从镜像源下载 uv...
    powershell -ExecutionPolicy Bypass -Command "$tmp=Join-Path $env:TEMP 'uv_install'; if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}; New-Item -ItemType Directory -Path $tmp | Out-Null; Invoke-WebRequest -Uri 'https://uv.agentsmirror.com/github/astral-sh/uv/releases/download/0.12.5/uv-x86_64-pc-windows-msvc.zip' -OutFile (Join-Path $tmp 'uv.zip'); Expand-Archive -Path (Join-Path $tmp 'uv.zip') -DestinationPath $tmp -Force; $exe=Get-ChildItem -Path $tmp -Recurse -Filter uv.exe | Select-Object -First 1; if(-not $exe){exit 1}; New-Item -ItemType Directory -Path '%USERPROFILE%\.local\bin' -Force | Out-Null; Copy-Item $exe.FullName '%USERPROFILE%\.local\bin\uv.exe' -Force"
    if errorlevel 1 (
        echo [备用源] 镜像源不可达，改用 GitHub 官方下载 uv...
        powershell -ExecutionPolicy Bypass -Command "$tmp=Join-Path $env:TEMP 'uv_install2'; if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}; New-Item -ItemType Directory -Path $tmp | Out-Null; Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/download/0.12.5/uv-x86_64-pc-windows-msvc.zip' -OutFile (Join-Path $tmp 'uv.zip'); Expand-Archive -Path (Join-Path $tmp 'uv.zip') -DestinationPath $tmp -Force; $exe=Get-ChildItem -Path $tmp -Recurse -Filter uv.exe | Select-Object -First 1; if(-not $exe){exit 1}; New-Item -ItemType Directory -Path '%USERPROFILE%\.local\bin' -Force | Out-Null; Copy-Item $exe.FullName '%USERPROFILE%\.local\bin\uv.exe' -Force"
        if errorlevel 1 goto :fail
    )
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
"%UV%" --version >nul 2>&1
if errorlevel 1 goto :fail
rem 安装 Python 3.11（裸机无 Python 也可建 venv）
"%UV%" python install 3.11
if errorlevel 1 goto :fail
rem 创建 venv（seed 失败回退最小 venv）
"%UV%" venv .runtime\venv --seed
if errorlevel 1 (
    echo [提示] seed 失败，改用最小 venv...
    "%UV%" venv .runtime\venv
    if errorlevel 1 goto :fail
)
rem 安装依赖（镜像 2 级：aliyun → tuna）
"%UV%" pip install --python .runtime\venv\Scripts\python.exe httpx playwright
if errorlevel 1 (
    echo [备用源] 阿里云镜像不可达，改用清华镜像...
    set "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple/"
    "%UV%" pip install --python .runtime\venv\Scripts\python.exe httpx playwright
    if errorlevel 1 goto :fail
)
rem 校验 playwright 可导入，失败重装兜底
.runtime\venv\Scripts\python -c "import playwright"
if errorlevel 1 (
    echo [提示] playwright 校验失败，正在重装...
    "%UV%" pip install --python .runtime\venv\Scripts\python.exe --force-reinstall playwright
    if errorlevel 1 goto :fail
)
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

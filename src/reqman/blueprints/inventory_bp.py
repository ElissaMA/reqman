"""库存查询蓝图 — 页面 / 登录状态 / 配置包 / 检查 / 上传 / 查询"""
import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, render_template, request, send_file

from ..config import AMRO_LOGIN_VERSION, AMRO_PUBLIC_URL, OUTPUT_DIR
from ..utils.error_handlers import ValidationError
from ..utils.response import api_error, api_success

inventory_bp = Blueprint("inventory", __name__, template_folder="../templates")

logger = logging.getLogger(__name__)

# 输出暂存文件命名模式（清理/识别仅匹配此模式，不误删其他文件）
OUTPUT_PATTERN = "*_库存已填_*.xlsx"

# 统一文案集（P1–P12）— 三端集中定义，前端与脚本引用此基准
MESSAGES = {
    "P1": "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。",
    "P2": "已打开登录页面，请在浏览器中完成川航 AMRO 登录（账号/密码/验证码），登录后请保持页面不动。",
    "P3": "✅ 登录成功，本页面即将就绪。",
    "P4": "❌ 系统未登录AMRO：请先点击「检查配置」选择脚本位置，或「新建配置」下载登录脚本，解压后双击运行完成登录",
    "P5": "✅ 登录有效，剩余约 {minutes} 分钟",
    "P6": "⚠️ 登录有效期内若在其他浏览器/设备登录川航 AMRO，当前登录将被挤掉失效，需重新运行登录脚本",
    "P7": "❌ 查询登录已过期：请重新运行登录脚本",
    "P8": "登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试",
    "P9": "查询完成。",
    "P10": "下载配置包（ZIP）后请解压，双击其中 start_login.bat 完成登录",
    "P11": "未检测到有效配置：请选择正确的 amro_login.py 或配置包（ZIP）文件；若配置缺失或版本过旧，请点击「新建配置」重新下载",
    "P12": "✅ 配置正常：版本与当前系统匹配，可运行登录脚本完成登录",
}


def _service():
    return current_app.extensions["inventory_service"]


@inventory_bp.route("/inventory")
def index():
    return render_template("inventory/index.html", messages=MESSAGES, login_version=AMRO_LOGIN_VERSION)


@inventory_bp.route("/inventory/session", methods=["GET"])
def session_status():
    svc = _service()
    status = svc.get_login_status()
    data = {"ready": status["ready"], "remaining_seconds": status["remaining_seconds"]}
    if status["ready"]:
        minutes = max(status["remaining_seconds"] // 60, 1)
        data["message"] = MESSAGES["P5"].format(minutes=minutes)
    elif svc.session_store.load():
        data["message"] = MESSAGES["P7"]
    else:
        data["message"] = MESSAGES["P4"]
    return api_success(data=data)


@inventory_bp.route("/inventory/setup-package", methods=["GET"])
def setup_package():
    """动态生成登录脚本配置包 ZIP（注入配置的公网地址，未配置回退当前访问地址）。"""
    server_url = AMRO_PUBLIC_URL or request.host_url.rstrip("/")
    py_source = _login_py_template(server_url)
    bat_source = _login_bat_template(server_url)
    readme_source = (
        "川航 AMRO 登录脚本配置包\n"
        "=======================\n"
        "1. 将本文件夹解压到任意位置\n"
        "2. 双击 start_login.bat\n"
        "3. 按提示关闭已登录的川航 AMRO 页面，点击确认后完成登录\n"
        "登录成功后脚本将自动上传凭证，本系统页面即可开始查询。\n"
        "首次运行约 1-2 分钟自动安装运行环境，使用系统自带 Chrome/Edge 浏览器，无需下载浏览器。\n"
        "注意：请勿将 .runtime 文件夹拷贝到其他机器，每台机器首次运行脚本会自动安装运行环境。\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("amro_login.py", py_source)
        zf.writestr("start_login.bat", bat_source)
        zf.writestr("README.txt", readme_source)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="amro_login_setup.zip",
                     mimetype="application/zip")


@inventory_bp.route("/inventory/check-config", methods=["POST"])
def check_config():
    """检查配置：上传 amro_login.py 或 ZIP，校验版本与地址。"""
    f = request.files.get("file")
    if f is None or not f.filename:
        raise ValidationError(MESSAGES["P11"])
    content = f.read()
    is_zip = f.filename.lower().endswith(".zip")
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                py_src = zf.read("amro_login.py").decode("utf-8")
        except (zipfile.BadZipFile, KeyError):
            raise ValidationError(MESSAGES["P11"])
    else:
        if not f.filename.endswith(".py"):
            raise ValidationError(MESSAGES["P11"])
        try:
            py_src = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError(MESSAGES["P11"])
    # 校验版本
    if f"LOGIN_VERSION = \"{AMRO_LOGIN_VERSION}\"" not in py_src and \
       f"LOGIN_VERSION='{AMRO_LOGIN_VERSION}'" not in py_src:
        raise ValidationError(MESSAGES["P11"])
    return api_success(message=MESSAGES["P12"])


@inventory_bp.route("/inventory/login/upload", methods=["POST"])
def login_upload():
    """登录凭证上传（登录脚本自动调用）。"""
    raw = (request.form.get("cookies") or "").strip()
    if not raw:
        raise ValidationError("缺少登录凭证")
    try:
        cookies = json.loads(raw)
    except json.JSONDecodeError:
        raise ValidationError("登录凭证格式错误")
    if not isinstance(cookies, list):
        raise ValidationError("登录凭证格式错误")
    _service().save_login(cookies)
    return api_success(message=MESSAGES["P3"])


@inventory_bp.route("/inventory/query", methods=["POST"])
def query():
    """执行库存查询：清理旧暂存 → 输出到 output/ → 返回统计与文件名（手动下载）。"""
    svc = _service()
    if not svc.check_login():
        return api_error(MESSAGES["P8"], error_code="LOGIN_EXPIRED", status_code=400)
    f = request.files.get("file")
    if f is None or not f.filename or not f.filename.endswith(".xlsx"):
        raise ValidationError("请选择正确的需求单 Excel 文件（.xlsx）")

    # 上传新文件前清理旧的库存已填暂存（仅匹配 *_库存已填_*.xlsx，不误删其他）
    for old in OUTPUT_DIR.glob(OUTPUT_PATTERN):
        try:
            old.unlink()
        except OSError:
            logger.warning("清理旧暂存失败: %s", old)

    output_stem = Path(os.path.basename(f.filename)).stem
    tmpdir = tempfile.mkdtemp(prefix="inventory_upload_")
    try:
        demand_path = Path(tmpdir) / "inventory_input.xlsx"
        f.save(demand_path)
        try:
            _dest, filename, result = svc.run_query(demand_path, output_stem=output_stem)
        except RuntimeError:
            return api_error(MESSAGES["P8"], error_code="LOGIN_EXPIRED", status_code=400)
        except ValueError as e:
            raise ValidationError(str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    data = {
        "total": result.total,
        "success": result.success,
        "fail": result.fail,
        "shortage": result.shortage,
        "warning": result.warning,
        "filename": filename,
    }
    return api_success(data=data, message=MESSAGES["P9"])


@inventory_bp.route("/inventory/latest-output", methods=["GET"])
def latest_output():
    """返回 output/ 最近暂存的库存已填副本信息（页面加载恢复）。"""
    files = sorted(
        OUTPUT_DIR.glob(OUTPUT_PATTERN),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    if not files:
        return api_success(data={"exists": False})
    latest = files[0]
    return api_success(data={"exists": True, "filename": latest.name, "mtime": latest.stat().st_mtime})


@inventory_bp.route("/inventory/download", methods=["GET"])
def download():
    """下载 output/ 内暂存的库存已填副本（防路径穿越）。"""
    file = request.args.get("file", "")
    if not file or os.path.basename(file) != file:
        raise ValidationError("文件名不合法")
    if OUTPUT_PATTERN[0] == "*" and not file.endswith(".xlsx"):
        raise ValidationError("文件名不合法")
    target = OUTPUT_DIR / file
    if not target.is_file() or not (OUTPUT_DIR.resolve() in target.resolve().parents):
        raise ValidationError("文件不存在")
    return send_file(target, as_attachment=True, download_name=target.name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _login_py_template(server_url: str) -> str:
    return (
        f'"""川航 AMRO 登录脚本 — 自动提取登录凭证并上传到需求单系统"""\n'
        "import asyncio, json, os, sys, tkinter as tk\n"
        "from tkinter import messagebox\n"
        f'SERVER_URL = "{server_url}"\n'
        f'UPLOAD_URL = "{server_url}/inventory/login/upload"\n'
        f'LOGIN_VERSION = "{AMRO_LOGIN_VERSION}"\n'
        'MSG_P1 = "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。"\n'
        'MSG_P2 = "已打开登录页面，请在浏览器中完成川航 AMRO 登录（账号/密码/验证码），登录后请保持页面不动。"\n'
        'MSG_P3 = "✅ 登录成功，本页面即将就绪。"\n'
        '\n'
        'def confirm():\n'
        '    root = tk.Tk(); root.withdraw()\n'
        '    ok = messagebox.askokcancel("提示", MSG_P1)\n'
        '    root.destroy()\n'
        '    return ok\n'
        '\n'
        'def _edge_candidates():\n'
        '    """显式 Edge 路径探测（ProgramFiles 与 x86 变体）。"""\n'
        '    return [\n'
        '        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),\n'
        '        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),\n'
        '    ]\n'
        '\n'
        'async def _launch_browser(p):\n'
        '    """浏览器三级回退：Chrome → Edge → 显式 Edge 路径。"""\n'
        '    for kwargs in ({"channel": "chrome"}, {"channel": "msedge"}):\n'
        '        try:\n'
        '            return await p.chromium.launch(headless=False, **kwargs)\n'
        '        except Exception:\n'
        '            pass\n'
        '    for path in _edge_candidates():\n'
        '        if os.path.exists(path):\n'
        '            try:\n'
        '                return await p.chromium.launch(headless=False, executable_path=path)\n'
        '            except Exception:\n'
        '                pass\n'
        '    print("未检测到 Chrome/Edge，请安装浏览器后重试")\n'
        '    return None\n'
        '\n'
        'async def main():\n'
        '    from playwright.async_api import async_playwright\n'
        '    import httpx\n'
        '    if not confirm():\n'
        '        return\n'
        '    async with async_playwright() as p:\n'
        '        browser = await _launch_browser(p)\n'
        '        if browser is None:\n'
        '            return\n'
        '        ctx = await browser.new_context()\n'
        '        page = await ctx.new_page()\n'
        '        print(MSG_P2)\n'
        '        await page.goto("https://me.sichuanair.com/views/home.shtml", wait_until="domcontentloaded")\n'
        '        deadline = asyncio.get_event_loop().time() + 300\n'
        '        while asyncio.get_event_loop().time() < deadline:\n'
        '            cookies = await ctx.cookies()\n'
        '            names = {c["name"] for c in cookies}\n'
        '            if "JSESSIONID" in names:\n'
        '                try:\n'
        '                    async with httpx.AsyncClient(verify=True, timeout=15, trust_env=False) as client:\n'
        '                        resp = await client.post(UPLOAD_URL, data={"cookies": json.dumps(cookies, ensure_ascii=False)})\n'
        '                        resp.raise_for_status()\n'
        '                except Exception:\n'
        '                    print(f"无法连接需求单系统（{UPLOAD_URL}），请检查网络后重新运行登录脚本")\n'
        '                    await browser.close()\n'
        '                    return\n'
        '                print(MSG_P3)\n'
        '                print("✅ 登录成功，请回到网页开始查询")\n'
        '                await browser.close()\n'
        '                return\n'
        '            await asyncio.sleep(2)\n'
        '        await browser.close()\n'
        '        raise TimeoutError("登录超时")\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    asyncio.run(main())\n'
    )


def _login_bat_template(server_url: str) -> str:
    return (
        "\ufeff@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "setlocal\r\n"
        'cd /d "%~dp0"\r\n'
        "set NO_PROXY=*\r\n"
        "set HTTP_PROXY=\r\n"
        "set HTTPS_PROXY=\r\n"
        "set ALL_PROXY=\r\n"
        "set UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/\r\n"
        "set UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone/\r\n"
        "set PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright/\r\n"
        "set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1\r\n"
        "rem venv 有效性校验（防拷贝 .runtime 后 trampoline 失效）\r\n"
        "if not exist .runtime\\venv\\Scripts\\python.exe goto :install\r\n"
        ".runtime\\venv\\Scripts\\python --version >nul 2>&1\r\n"
        "if errorlevel 1 (\r\n"
        "    echo [环境异常] 检测到损坏的运行环境，正在重建...\r\n"
        "    rmdir /s /q .runtime\r\n"
        "    goto :install\r\n"
        ")\r\n"
        "goto :run\r\n"
        "\r\n"
        ":install\r\n"
        "echo [首次使用] 正在自动安装运行环境，请稍候...\r\n"
        "rem 定位 uv：本机已装 → PATH → 下载解压定位\r\n"
        'if exist "%USERPROFILE%\\.local\\bin\\uv.exe" set "UV=%USERPROFILE%\\.local\\bin\\uv.exe"\r\n'
        "if not defined UV where uv >nul 2>nul && set \"UV=uv\"\r\n"
        "if not defined UV (\r\n"
        "    echo [下载 uv] 正在从镜像源下载 uv...\r\n"
        '    powershell -ExecutionPolicy Bypass -Command "$tmp=Join-Path $env:TEMP \'uv_install\'; if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}; New-Item -ItemType Directory -Path $tmp | Out-Null; Invoke-WebRequest -Uri \'https://uv.agentsmirror.com/github/astral-sh/uv/releases/download/0.12.5/uv-x86_64-pc-windows-msvc.zip\' -OutFile (Join-Path $tmp \'uv.zip\'); Expand-Archive -Path (Join-Path $tmp \'uv.zip\') -DestinationPath $tmp -Force; $exe=Get-ChildItem -Path $tmp -Recurse -Filter uv.exe | Select-Object -First 1; if(-not $exe){exit 1}; New-Item -ItemType Directory -Path \'%USERPROFILE%\\.local\\bin\' -Force | Out-Null; Copy-Item $exe.FullName \'%USERPROFILE%\\.local\\bin\\uv.exe\' -Force"\r\n'
        "    if errorlevel 1 (\r\n"
        "        echo [备用源] 镜像源不可达，改用 GitHub 官方下载 uv...\r\n"
        '        powershell -ExecutionPolicy Bypass -Command "$tmp=Join-Path $env:TEMP \'uv_install2\'; if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}; New-Item -ItemType Directory -Path $tmp | Out-Null; Invoke-WebRequest -Uri \'https://github.com/astral-sh/uv/releases/download/0.12.5/uv-x86_64-pc-windows-msvc.zip\' -OutFile (Join-Path $tmp \'uv.zip\'); Expand-Archive -Path (Join-Path $tmp \'uv.zip\') -DestinationPath $tmp -Force; $exe=Get-ChildItem -Path $tmp -Recurse -Filter uv.exe | Select-Object -First 1; if(-not $exe){exit 1}; New-Item -ItemType Directory -Path \'%USERPROFILE%\\.local\\bin\' -Force | Out-Null; Copy-Item $exe.FullName \'%USERPROFILE%\\.local\\bin\\uv.exe\' -Force"\r\n'
        "        if errorlevel 1 goto :fail\r\n"
        "    )\r\n"
        '    set "UV=%USERPROFILE%\\.local\\bin\\uv.exe"\r\n'
        ")\r\n"
        '"%UV%" --version >nul 2>&1\r\n'
        "if errorlevel 1 goto :fail\r\n"
        "rem 安装 Python 3.11（裸机无 Python 也可建 venv）\r\n"
        '"%UV%" python install 3.11\r\n'
        "if errorlevel 1 goto :fail\r\n"
        "rem 创建 venv（seed 失败回退最小 venv）\r\n"
        '"%UV%" venv .runtime\\venv --seed\r\n'
        "if errorlevel 1 (\r\n"
        "    echo [提示] seed 失败，改用最小 venv...\r\n"
        '    "%UV%" venv .runtime\\venv\r\n'
        "    if errorlevel 1 goto :fail\r\n"
        ")\r\n"
        "rem 安装依赖（镜像 2 级：aliyun → tuna）\r\n"
        '"%UV%" pip install --python .runtime\\venv\\Scripts\\python.exe httpx playwright\r\n'
        "if errorlevel 1 (\r\n"
        "    echo [备用源] 阿里云镜像不可达，改用清华镜像...\r\n"
        '    set "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple/"\r\n'
        '    "%UV%" pip install --python .runtime\\venv\\Scripts\\python.exe httpx playwright\r\n'
        "    if errorlevel 1 goto :fail\r\n"
        ")\r\n"
        "rem 校验 playwright 可导入，失败重装兜底\r\n"
        '.runtime\\venv\\Scripts\\python -c "import playwright"\r\n'
        "if errorlevel 1 (\r\n"
        "    echo [提示] playwright 校验失败，正在重装...\r\n"
        '    "%UV%" pip install --python .runtime\\venv\\Scripts\\python.exe --force-reinstall playwright\r\n'
        "    if errorlevel 1 goto :fail\r\n"
        ")\r\n"
        "echo [安装完成] 运行环境就绪\r\n"
        "\r\n"
        ":run\r\n"
        ".runtime\\venv\\Scripts\\python amro_login.py\r\n"
        "if errorlevel 1 (\r\n"
        "    echo [登录未完成] 请查看上方错误信息，本窗口可安全关闭\r\n"
        "    goto :done\r\n"
        ")\r\n"
        "echo [已完成登录] 本窗口可安全关闭\r\n"
        "goto :done\r\n"
        "\r\n"
        "\r\n"
        ":fail\r\n"
        "echo [安装失败] 可能是网络问题，请检查网络连接后重新运行，或手动安装运行环境\r\n"
        "pause\r\n"
        "exit /b 1\r\n"
        "\r\n"
        ":done\r\n"
        "pause\r\n"
    )

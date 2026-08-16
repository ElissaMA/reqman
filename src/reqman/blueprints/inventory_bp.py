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
        "import asyncio, json, sys, tkinter as tk\n"
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
        'async def main():\n'
        '    from playwright.async_api import async_playwright\n'
        '    import httpx\n'
        '    if not confirm():\n'
        '        return\n'
        '    async with async_playwright() as p:\n'
        '        browser = await p.chromium.launch(headless=False)\n'
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
        '                root = tk.Tk(); root.withdraw()\n'
        '                messagebox.showinfo("登录成功", "✅ 登录成功，本页面即将就绪。\\n请回到网页开始查询")\n'
        '                root.destroy()\n'
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
    is_local = "127.0.0.1" in server_url or "localhost" in server_url

    header = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "setlocal\r\n"
        "cd /d %~dp0\r\n"
    )
    if not is_local:
        # 服务器模式：自举最小化（安装与运行均在最小化窗口，防误关）
        header += (
            'if not "%1"=="min" (\r\n'
            '    start "" /min cmd /c ""%~f0" min"\r\n'
            "    exit /b\r\n"
            ")\r\n"
        )

    setup = (
        "set UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/\r\n"
        "set UV_PYTHON_INSTALL_MIRROR=https://mirrors.aliyun.com/python-release/\r\n"
        "set PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright/\r\n"
        "if not exist .runtime\\venv\\Scripts\\python.exe (\r\n"
        "    echo [首次使用] 正在自动安装运行环境，请稍候...\r\n"
        "    where uv >nul 2>nul || (python -m pip install -q uv || py -m pip install -q uv)\r\n"
        "    uv python install 3.11 || echo [警告] Python 安装失败\r\n"
        "    uv venv .runtime\\venv\r\n"
        "    uv pip install --python .runtime\\venv\\Scripts\\python.exe httpx playwright\r\n"
        "    .runtime\\venv\\Scripts\\python -m playwright install chromium\r\n"
        ")\r\n"
    )

    if is_local:
        run = (
            ".runtime\\venv\\Scripts\\python amro_login.py\r\n"
            "if errorlevel 1 ( echo [登录未完成] 请查看上方错误信息 && pause )\r\n"
        )
    else:
        run = 'start "" /min cmd /c ""%~dp0.runtime\\venv\\Scripts\\python.exe" amro_login.py"\r\n'

    return header + setup + run

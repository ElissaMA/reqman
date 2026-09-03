"""库存查询蓝图 — 页面 / 登录状态 / 配置包 / 检查 / 上传 / 查询"""
import io
import json
import logging
import os
import uuid
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file

from ..config import AMRO_LOGIN_VERSION, AMRO_PUBLIC_URL, OUTPUT_DIR
from ..services import amro_sync
from ..utils.error_handlers import ValidationError, is_ajax
from ..utils.response import api_error, api_success

inventory_bp = Blueprint("inventory", __name__, template_folder="../templates")

logger = logging.getLogger(__name__)

# 输出暂存文件命名模式（清理/识别仅匹配此模式，不误删其他文件）
OUTPUT_PATTERN = "*_库存已填_*.xlsx"


def _latest_output_filename() -> str:
    """OUTPUT_DIR 中最新的一份库存已填副本文件名（无则空串）。"""
    files = sorted(
        OUTPUT_DIR.glob(OUTPUT_PATTERN),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    return files[0].name if files else ""


def _reconcile_inventory_download(last_query: dict) -> dict:
    """校正 inventory_query 摘要的下载链接：库存输出在每次新查询时会被清理，
    若持久化的静态文件名已不存在，则回退到当前仍存在的实时最新文件；都无则不渲染下载。"""
    if not last_query:
        return last_query
    out = dict(last_query)
    dl = out.get("download_url", "") or ""
    fname = dl.split("file=", 1)[1] if "file=" in dl else ""
    if fname and (OUTPUT_DIR / fname).is_file():
        return out  # 静态文件仍在，保持原链接
    latest = _latest_output_filename()
    out["download_url"] = f"/inventory/download?file={latest}" if latest else ""
    return out

# 统一文案集（P1–P12）— 三端集中定义，前端与脚本引用此基准
MESSAGES = {
    "P1": "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。",
    "P2": "已打开登录页面，请先在浏览器中接收并输入手机验证码，再输入账号密码完成川航 AMRO 登录；登录成功后保持页面，点击页面「✅ 完成登录」按钮或回到此窗口按回车。",
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
    store = current_app.extensions["store"]
    return render_template(
        "inventory/index.html",
        messages=MESSAGES,
        login_version=AMRO_LOGIN_VERSION,
        warnings=store.get_inventory_warnings(),
        amro_status=amro_sync.get_query_status("inventory_query"),
        amro_last_query=_reconcile_inventory_download(
            amro_sync.get_last_query_result("inventory_query")),
    )


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
    protocol_source = _protocol_bat_template()
    readme_source = (
        "川航 AMRO 登录脚本配置包\n"
        "=======================\n"
        "1. 将本文件夹解压到【任意位置】（无需放到桌面）\n"
        "2. 双击 register_protocol.bat —— 注册一键登录协议并立即启动登录（一次性，推荐）\n"
        "   注册后可直接点击系统表头的「⚡一键登录」唤起登录；未注册也可随时双击 start_login.bat 登录\n"
        "3. 按提示关闭已登录的川航 AMRO 页面，点击确认后浏览器打开登录页；先在浏览器中接收并输入手机验证码，再完成账号登录；登录后点击页面「✅ 完成登录」按钮或回到此窗口按回车，脚本即上传凭证\n"
        "登录成功后脚本将自动上传凭证，本系统页面即可开始查询。\n"
        "首次运行约 1-2 分钟自动安装运行环境，使用系统自带 Chrome/Edge 浏览器，无需下载浏览器。\n"
        "注意：请勿将 .runtime 文件夹拷贝到其他机器，每台机器首次运行脚本会自动安装运行环境。\n"
        "每台机器首次使用需执行一次 register_protocol.bat（协议注册为本机操作，无法从服务器推送）。\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("amro_login.py", py_source)
        zf.writestr("start_login.bat", bat_source)
        zf.writestr("register_protocol.bat", protocol_source)
        zf.writestr("README.txt", readme_source)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="amro_login_setup.zip",
                     mimetype="application/zip")


def _protocol_bat_template() -> str:
    """一次性注册 ReqManLogin:// 协议（%~dp0 自定位，解压任意位置有效）+ 注册后立即启动登录。"""
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "rem 一次性注册 ReqManLogin:// 一键登录协议（指向本目录 start_login.bat，解压任意位置均可）\r\n"
        "reg add \"HKCU\\Software\\Classes\\ReqManLogin\" /ve /d \"URL:ReqManLogin Protocol\" /f\r\n"
        "reg add \"HKCU\\Software\\Classes\\ReqManLogin\" /v \"URL Protocol\" /f\r\n"
        "reg add \"HKCU\\Software\\Classes\\ReqManLogin\\shell\\open\\command\" /ve /d \"\\\"%~dp0start_login.bat\\\" \\\"%%1\\\"\" /f\r\n"
        "echo.\r\n"
        "echo 已注册一键登录协议，指向: %~dp0start_login.bat\r\n"
        "echo 如杀毒软件拦截，请允许本次操作\r\n"
        "echo.\r\n"
        "echo 注册完成，正在启动登录脚本...\r\n"
        "call \"%~dp0start_login.bat\"\r\n"
        "pause\r\n"
    )


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
    """执行库存查询：启动后台线程（长任务移出请求线程，前端轮询状态）。"""
    svc = _service()
    if not amro_sync.require_amro_session():
        return api_error(MESSAGES["P8"], error_code="LOGIN_EXPIRED", status_code=401)
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
    # 持久化暂存上传文件：后台 job 在守护线程中读取，请求结束不得删除
    staged_path = OUTPUT_DIR / f".staging_{uuid.uuid4().hex}.xlsx"
    f.save(staged_path)

    # 取出预警库件号与阈值，随查询一并查询并回写缓存库存
    store = current_app.extensions["store"]
    ws = store.get_inventory_warnings()
    threshold_map = {
        w["part_number"]: float(w["threshold"])
        for w in ws if w.get("threshold") is not None
    }
    warning_pns = [w["part_number"] for w in ws]

    if not amro_sync.start_inventory_query(
        svc, staged_path, output_stem,
        warning_thresholds=threshold_map,
        warning_pns=warning_pns, store=store,
    ):
        # 已有查询在跑：清理本次暂存并返回 409
        try:
            staged_path.unlink(missing_ok=True)
        except OSError:
            pass
        return api_error(amro_sync.query_busy_message()
                         or "已有查询任务进行中，请等待完成后再查询", status_code=409)
    return api_success(data={"started": True})


@inventory_bp.route("/inventory/query-status")
def query_status():
    """库存查询进度/简要结果（全局内存态，前端轮询/恢复加载）。"""
    return jsonify({"success": True, "data": amro_sync.get_query_status("inventory_query")})


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


@inventory_bp.route("/inventory-warning/new", methods=["GET", "POST"])
def inventory_warning_new():
    """新增库存预警条目（弹窗表单 + AJAX）。"""
    if request.method == "POST":
        part_number = (request.form.get("part_number") or "").strip().upper()
        if not part_number:
            if is_ajax():
                return api_error("件号不能为空")
            flash("件号不能为空", "error")
            return redirect("/inventory-warning/new")
        threshold_raw = (request.form.get("threshold") or "").strip()
        try:
            threshold = float(threshold_raw)
        except (ValueError, TypeError):
            if is_ajax():
                return api_error("警戒线须为数字")
            flash("警戒线须为数字", "error")
            return redirect("/inventory-warning/new")
        if threshold < 0:
            if is_ajax():
                return api_error("警戒线须为非负数字")
            flash("警戒线须为非负数字", "error")
            return redirect("/inventory-warning/new")
        store = current_app.extensions["store"]
        store.save_inventory_warning({
            "part_number": part_number,
            "name": (request.form.get("name") or "").strip(),
            "threshold": threshold,
            "note": (request.form.get("note") or "").strip(),
        })
        if is_ajax():
            return api_success(message="已添加库存预警")
        flash("已添加库存预警", "success")
        return redirect("/inventory")
    return render_template("inventory/warning_form.html", warning=None, title="新增库存预警")


@inventory_bp.route("/inventory-warning/<part_number>/edit", methods=["GET", "POST"])
def inventory_warning_edit(part_number):
    """编辑库存预警条目（弹窗表单 + AJAX）。"""
    store = current_app.extensions["store"]
    pn = part_number.strip().upper()
    existing = store.get_inventory_warning(pn)
    if request.method == "POST":
        if existing is None:
            if is_ajax():
                return api_error("预警条目不存在", status_code=404)
            flash("预警条目不存在", "error")
            return redirect("/inventory")
        data = {"part_number": pn}
        data["name"] = (request.form.get("name") or "").strip()
        data["note"] = (request.form.get("note") or "").strip()
        threshold_raw = (request.form.get("threshold") or "").strip()
        if threshold_raw:
            try:
                threshold = float(threshold_raw)
            except (ValueError, TypeError):
                if is_ajax():
                    return api_error("警戒线须为数字")
                flash("警戒线须为数字", "error")
                return redirect(f"/inventory-warning/{part_number}/edit")
            if threshold < 0:
                if is_ajax():
                    return api_error("警戒线须为非负数字")
                flash("警戒线须为非负数字", "error")
                return redirect(f"/inventory-warning/{part_number}/edit")
            data["threshold"] = threshold
        store.save_inventory_warning(data)
        if is_ajax():
            return api_success(message="已更新库存预警")
        flash("已更新库存预警", "success")
        return redirect("/inventory")
    if existing is None:
        if is_ajax():
            return api_error("预警条目不存在", status_code=404)
        flash("预警条目不存在", "error")
        return redirect("/inventory")
    return render_template("inventory/warning_form.html", warning=existing, title="编辑库存预警")


@inventory_bp.route("/inventory-warning/<part_number>/delete", methods=["POST"])
def inventory_warning_delete(part_number):
    """删除库存预警条目（AJAX，ListUI.del 调用）。"""
    store = current_app.extensions["store"]
    ok = store.delete_inventory_warning(part_number.strip().upper())
    if ok:
        return api_success(message="已删除库存预警")
    return api_error("预警条目不存在", status_code=404)


def _login_py_template(server_url: str) -> str:
    return (
        f'"""川航 AMRO 登录脚本 — 自动提取登录凭证并上传到ReqMan定检准备系统"""\n'
        "import asyncio, json, os, sys, tkinter as tk\n"
        "from tkinter import messagebox\n"
        f'SERVER_URL = "{server_url}"\n'
        f'UPLOAD_URL = "{server_url}/inventory/login/upload"\n'
        f'LOGIN_VERSION = "{AMRO_LOGIN_VERSION}"\n'
        'MSG_P1 = "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。"\n'
        'MSG_P2 = "已打开登录页面，请先在浏览器中接收并输入手机验证码，再输入账号密码完成川航 AMRO 登录；登录成功后保持页面，点击页面「✅ 完成登录」按钮或回到此窗口按回车。"\n'
        'MSG_P3 = "✅ 登录成功，本页面即将就绪。"\n'
        '_INIT_JS = "() => { if (document.getElementById(\'__reqman_done_btn\')) return; var b = document.createElement(\'button\'); b.id = \'__reqman_done_btn\'; b.textContent = \'✅ 完成登录\'; b.style.cssText = \'position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:10px 16px;background:#198754;color:#fff;border:none;border-radius:8px;font-size:15px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3)\'; b.onclick = function(){ if (window.__reqman_login_done) window.__reqman_login_done(); }; (document.body || document.documentElement).appendChild(b); }"\n'
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
        'async def _wait_confirm(done_event):\n'
        '    loop = asyncio.get_event_loop()\n'
        '    enter_task = loop.run_in_executor(None, input, "\\n>>> 完成手机验证与账号登录后，按回车键获取凭证（或点击页面右下角「✅ 完成登录」）：")\n'
        '    done_task = asyncio.ensure_future(done_event.wait())\n'
        '    try:\n'
        '        await asyncio.wait({enter_task, done_task}, return_when=asyncio.FIRST_COMPLETED)\n'
        '    finally:\n'
        '        if not enter_task.done():\n'
        '            enter_task.cancel()\n'
        '\n'
        'async def main():\n'
        '    from playwright.async_api import async_playwright\n'
        '    import httpx\n'
        '    if not confirm():\n'
        '        return\n'
        '    done = asyncio.Event()\n'
        '    async with async_playwright() as p:\n'
        '        browser = await _launch_browser(p)\n'
        '        if browser is None:\n'
        '            return\n'
        '        ctx = await browser.new_context()\n'
        '        page = await ctx.new_page()\n'
        '        async def _on_done():\n'
        '            done.set()\n'
        '        await page.expose_function("__reqman_login_done", _on_done)\n'
        '        await page.add_init_script(_INIT_JS)\n'
        '        print(MSG_P2)\n'
        '        await page.goto("https://me.sichuanair.com/views/home.shtml", wait_until="domcontentloaded")\n'
        '        await _wait_confirm(done)\n'
        '        cookies = await ctx.cookies()\n'
        '        names = {c["name"] for c in cookies}\n'
        '        if "JSESSIONID" not in names:\n'
        '            print("⚠️ 未检测到 AMRO 登录会话（JSESSIONID），请确认已完成手机验证与账号登录后重新运行登录脚本。")\n'
        '            await browser.close()\n'
        '            return\n'
        '        try:\n'
        '            async with httpx.AsyncClient(verify=True, timeout=15, trust_env=False) as client:\n'
        '                resp = await client.post(UPLOAD_URL, data={"cookies": json.dumps(cookies, ensure_ascii=False)})\n'
        '                resp.raise_for_status()\n'
        '        except Exception:\n'
        '            print(f"无法连接ReqMan定检准备系统（{UPLOAD_URL}），请检查网络后重新运行登录脚本")\n'
        '            await browser.close()\n'
        '            return\n'
        '        print(MSG_P3)\n'
        '        print("✅ 登录成功，请回到网页开始查询")\n'
        '        await browser.close()\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    asyncio.run(main())\n'
    )


def _login_bat_template(server_url: str) -> str:
    return (
        "@echo off\r\n"
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

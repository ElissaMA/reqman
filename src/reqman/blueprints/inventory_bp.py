"""库存查询蓝图 — 页面 / 登录状态 / 配置包 / 检查 / 上传 / 查询"""
import io
import json
import logging
import os
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file

from ..config import AMRO_LOGIN_VERSION, AMRO_PUBLIC_URL, OUTPUT_DIR
from ..services import amro_sync
from ..utils.error_handlers import ValidationError, is_ajax
from ..utils.messages import MESSAGES
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
    若持久化的静态文件名已不存在，则回退到当前仍存在的实时最新文件；都无则不渲染下载。
    下载链接的文件名做 URL 编码（含 + 空格 & 等字符的文件名才能命中），校验时先解码。"""
    if not last_query:
        return last_query
    out = dict(last_query)
    dl = out.get("download_url", "") or ""
    fname = dl.split("file=", 1)[1] if "file=" in dl else ""
    fname = unquote(fname)
    if fname and (OUTPUT_DIR / fname).is_file():
        return out  # 静态文件仍在，保持原链接
    latest = _latest_output_filename()
    out["download_url"] = f"/inventory/download?file={quote(latest)}" if latest else ""
    return out



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
    state = status["state"]
    account = status.get("account") or "未登记"
    data = {
        "ready": status["ready"],
        "state": state,
        "account": status.get("account"),
        "login_at": status.get("login_at"),
        "last_checked_at": status.get("last_checked_at"),
        "login_duration_seconds": status.get("login_duration_seconds", 0),
    }
    if state == "valid":
        data["message"] = MESSAGES["P5"].format(account=account)
    elif state == "probe_error":
        data["message"] = "⚠️ AMRO 状态暂不可用，请稍后重试。"
    elif state == "expired":
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
        "3. 按提示关闭已登录的川航 AMRO 页面，点击确认后浏览器打开登录页；在浏览器中完成手机验证码和账号登录，脚本将自动检查页面、读取账号、探活并上传凭证，无需点击按钮或回车。\n"
        "4. 完成 AMRO 浏览器登录后，脚本自动检查账号与会话、获取 Cookie 并上传；无需点击页面按钮，也无需在窗口内回车。\n"
        "登录成功后脚本自动结束，本系统页面即可开始查询。\n"
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
        "set \"LOGIN_EXIT=%errorlevel%\"\r\n"
        "if not \"%LOGIN_EXIT%\"==\"0\" echo 登录脚本未完成，请查看上方错误信息\r\n"
        "exit /b %LOGIN_EXIT%\r\n"
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
    account = (request.form.get("account") or "").strip()
    if not account or not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", account):
        raise ValidationError("缺少有效登录账号")
    try:
        _service().save_login(cookies, account=account)
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
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
                return api_error("件号不能为空", field="part_number")
            flash("件号不能为空", "error")
            return redirect("/inventory-warning/new")
        threshold_raw = (request.form.get("threshold") or "").strip()
        try:
            threshold = float(threshold_raw)
        except (ValueError, TypeError):
            if is_ajax():
                return api_error("警戒线须为数字", field="threshold")
            flash("警戒线须为数字", "error")
            return redirect("/inventory-warning/new")
        if threshold < 0:
            if is_ajax():
                return api_error("警戒线须为非负数字", field="threshold")
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


@inventory_bp.route("/inventory-warning/<path:part_number>/edit", methods=["GET", "POST"])
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


@inventory_bp.route("/inventory-warning/<path:part_number>/delete", methods=["POST"])
def inventory_warning_delete(part_number):
    """删除库存预警条目（AJAX，ListUI.del 调用）。"""
    store = current_app.extensions["store"]
    ok = store.delete_inventory_warning(part_number.strip().upper())
    if ok:
        return api_success(message="已删除库存预警")
    return api_error("预警条目不存在", status_code=404)


def _login_py_template(server_url: str) -> str:
    """从仓库静态脚本生成配置包版本，仅替换服务地址和版本号。"""
    source_path = Path(__file__).resolve().parents[3] / "scripts" / "amro_login.py"
    source = source_path.read_text(encoding="utf-8")
    source = source.replace(
        'SERVER_URL = "http://127.0.0.1:5001"',
        f'SERVER_URL = "{server_url}"',
    )
    source = source.replace(
        'UPLOAD_URL = "http://127.0.0.1:5001/inventory/login/upload"',
        f'UPLOAD_URL = "{server_url}/inventory/login/upload"',
    )
    source = source.replace(
        'LOGIN_VERSION = "4"',
        f'LOGIN_VERSION = "{AMRO_LOGIN_VERSION}"',
    )
    return source


def _login_bat_template(server_url: str) -> str:
    """读取仓库静态 BAT，保证配置包与固定脚本行为一致。"""
    source_path = Path(__file__).resolve().parents[3] / "scripts" / "start_login.bat"
    return source_path.read_bytes().decode("utf-8")

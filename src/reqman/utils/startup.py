"""启动辅助 — 端口探测/释放、就绪等待、退出备份（纯函数，无应用副作用）。

从 app.py 抽离：app.py 模块级 create_app()/atexit 注册面向生产启动，
测试只需这些无副作用的助手，不应连带触发对真实 data/ 的实例化与备份。
"""
from __future__ import annotations

import gzip
import logging
import os
import platform
import socket
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _decode_windows_output(value):
    """按 Windows 本地代码页解码命令输出，避免 Git Bash UTF-8 环境误解码。"""
    if not isinstance(value, bytes):
        return value or ""
    try:
        return value.decode("mbcs", errors="replace")
    except LookupError:  # 非 Windows 测试环境没有 mbcs 编解码器
        return value.decode("cp936", errors="replace")


def find_pid_by_port(port):
    """跨平台：根据端口查找占用进程的 PID。"""
    system = platform.system()
    try:
        if system == "Windows":
            raw = subprocess.check_output(
                ["netstat", "-ano"], stderr=subprocess.DEVNULL
            )
            output = _decode_windows_output(raw)
            for line in output.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if parts:
                        return parts[-1]
        else:
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-t"],
                capture_output=True, text=True, check=False
            )
            if result.stdout.strip():
                return result.stdout.strip().split("\n")[0]
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        pass
    return None


def kill_process(pid):
    """跨平台：终止指定 PID 的进程。"""
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True, encoding="mbcs",
                errors="replace", check=False
            )
        else:
            result = subprocess.run(
                ["kill", "-9", str(pid)],
                capture_output=True, text=True, check=False
            )
        return result.returncode == 0
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return False


def free_port(port):
    """释放端口并返回最终建议使用的端口。"""
    pid = find_pid_by_port(port)
    if pid:
        print(f"[启动] 端口 {port} 被 PID {pid} 占用，正在释放...")
        kill_process(pid)
        time.sleep(1)
        if find_pid_by_port(port):
            fallback = port + 1
            print(f"[警告] 端口 {port} 释放失败，将尝试备用端口 {fallback}")
            return fallback
        print(f"[启动] 端口 {port} 已释放")
    return port


def wait_and_open(port):
    """等待服务就绪。服务端部署时不自动打开浏览器。"""
    system = platform.system()
    for _ in range(30):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                sock.close()
                url = f"http://127.0.0.1:{port}"
                print(f"[启动] 服务已就绪: {url}")
                # 仅 Windows 桌面环境自动打开浏览器
                if system == "Windows":
                    os.startfile(url)
                return
            sock.close()
        except OSError:
            pass
        time.sleep(0.5)
    print(f"[提示] 服务启动超时，请手动访问 http://127.0.0.1:{port}")


def _backup_on_exit(project_root: Path | None = None):
    """应用关闭时自动备份数据库（核心+运行时文件，路径基于项目根，不依赖启动 CWD）。

    project_root 供测试注入；缺省按模块位置推导项目根。
    """
    try:
        root = project_root or Path(__file__).resolve().parents[3]
        data_dir = root / "data"
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 生成带时间戳的备份文件名
        timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d_%H-%M-%S")

        targets = [data_dir / "reqman_db.json", data_dir / "reqman_db_runtime.json"]
        for db_file in targets:
            if not db_file.exists():
                continue
            backup_file = backup_dir / f"{db_file.stem}_{timestamp}.json.gz"
            backup_file.write_bytes(gzip.compress(db_file.read_bytes()))

        # 清理28天前的备份（覆盖 core 与 runtime 两种命名）
        cutoff = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=28)
        for f in backup_dir.glob("reqman_db*_*_*.json.gz"):
            if f.stat().st_mtime < cutoff.timestamp():
                f.unlink()
    except OSError as e:
        logger.warning("关闭备份失败: %s", e)

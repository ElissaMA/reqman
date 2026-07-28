"""启动入口 — python app.py

改进特性：
- 启动前自动释放 5001 端口（杀掉占用进程）
- 端口被占用时尝试备用端口
- 服务就绪后自动打开浏览器
"""

import os
import sys


def _ensure_venv():
    """确保在虚拟环境中运行，否则自动切换"""
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return  # 已在虚拟环境中

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
    venv_python_unix = os.path.join(project_root, "venv", "bin", "python3")

    if os.path.exists(venv_python):
        print("[启动] 检测到虚拟环境，正在切换...")
        os.execv(venv_python, [venv_python] + sys.argv)
    elif os.path.exists(venv_python_unix):
        print("[启动] 检测到虚拟环境，正在切换...")
        os.execv(venv_python_unix, [venv_python_unix] + sys.argv)
    else:
        print("[警告] 未找到虚拟环境，请先运行: python -m venv venv")

_ensure_venv()

import socket
import subprocess
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from reqman import create_app


def find_pid_by_port(port):
    try:
        output = subprocess.check_output(
            ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
        )
        for line in output.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    return parts[-1]
    except (OSError, subprocess.CalledProcessError):
        pass
    return None


def kill_process(pid):
    try:
        subprocess.run(["taskkill", "-f", "-pid", str(pid)],
                       capture_output=True, text=True, check=False)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def free_port(port):
    pid = find_pid_by_port(port)
    if pid:
        print(f"[启动] 端口 {port} 被 PID {pid} 占用，正在释放...")
        kill_process(pid)
        time.sleep(1)
        if find_pid_by_port(port):
            print(f"[警告] 端口 {port} 释放失败，将尝试备用端口")
            return False
        print(f"[启动] 端口 {port} 已释放")
    return True


def wait_and_open(port):
    for _ in range(30):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                sock.close()
                print(f"[启动] 服务已就绪，正在打开浏览器 http://127.0.0.1:{port}")
                os.startfile(f"http://127.0.0.1:{port}")
                return
            sock.close()
        except OSError:
            pass
        time.sleep(0.5)
    print(f"[提示] 服务启动超时，请手动访问 http://127.0.0.1:{port}")


app = create_app()

if __name__ == "__main__":
    port = 5001

    print("=" * 50)
    print("  定检需求单管理系统 V3")
    print("  架构: 工厂模式 + 蓝图 + 服务层")
    print("=" * 50)

    free_port(port)

    threading.Thread(target=wait_and_open, args=(port,), daemon=True).start()

    try:
        app.run(debug=False, host="127.0.0.1", port=port)
    except OSError as e:
        if "address already in use" in str(e).lower() or "权限" in str(e):
            print(f"[错误] 端口 {port} 仍被占用，尝试使用端口 {port + 1}...")
            port += 1
            try:
                app.run(debug=False, host="127.0.0.1", port=port)
            except OSError as e2:
                print(f"[错误] 无法启动服务: {e2}")
                sys.exit(1)
        else:
            print(f"[错误] 启动失败: {e}")
            sys.exit(1)

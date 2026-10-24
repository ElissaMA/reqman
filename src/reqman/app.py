"""启动入口 — python app.py

改进特性：
- 启动前自动释放 5001 端口（杀掉占用进程）
- 端口被占用时尝试备用端口
- 服务就绪后自动打开浏览器

端口/备份等启动助手在 reqman.utils.startup（无应用副作用，可被测试安全导入）；
本模块保留生产启动副作用（create_app 实例化 + atexit 退出备份），测试勿导入。
"""

import atexit
import os
import sys
import threading


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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from reqman import create_app
from reqman.config import VERSION
from reqman.utils.startup import _backup_on_exit, free_port, wait_and_open

app = create_app()

atexit.register(_backup_on_exit)

if __name__ == "__main__":
    port = 5001

    print("=" * 50)
    print(f"  ReqMan定检准备系统 V{VERSION}")
    print("  架构: 工厂模式 + 蓝图 + 服务层")
    print("=" * 50)

    port = free_port(port)

    # debug 跟随配置（开发模式 FLASK_ENV=development 时开启，模板自动重载）
    debug = app.config.get("DEBUG", False)

    try:
        threading.Thread(target=wait_and_open, args=(port,), daemon=True).start()
        app.run(debug=debug, host="127.0.0.1", port=port)
    except OSError as e:
        address_busy = getattr(e, "errno", None) == 10048
        address_busy = address_busy or "address already in use" in str(e).lower() or "权限" in str(e)
        if address_busy:
            fallback = port + 1
            print(f"[错误] 端口 {port} 仍被占用，尝试使用备用端口 {fallback}...")
            try:
                threading.Thread(target=wait_and_open, args=(fallback,), daemon=True).start()
                app.run(debug=debug, host="127.0.0.1", port=fallback)
            except OSError as e2:
                print(f"[错误] 无法启动服务: {e2}")
                sys.exit(1)
        else:
            print(f"[错误] 启动失败: {e}")
            sys.exit(1)

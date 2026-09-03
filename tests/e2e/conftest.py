"""e2e 有头浏览器测试 conftest（pytest-playwright）。

- 子进程启动 Flask 测试服务器（端口 5123，werkzeug make_server）
- 使用隔离的临时DB副本（core + runtime 双文件），结束校验真实DB未被污染
- chromium 有头模式（headless=False），E2E_HEADLESS=1 可临时切无头

运行：
    venv\\Scripts\\python.exe -m pytest tests/e2e -m e2e -v
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PORT = 5123
BASE = f"http://127.0.0.1:{PORT}"

SERVER_SCRIPT = r"""
import os, sys
os.environ["DB_FILE"] = r"{db_path}"
os.environ["CANCELLED_CARDS_FILE"] = r"{cancelled_path}"
sys.path.insert(0, r"{src}")
from werkzeug.serving import make_server
from reqman import create_app
server = make_server("127.0.0.1", {port}, create_app())
server.serve_forever()
"""


def _sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _wait_server(proc: subprocess.Popen, log_path: pathlib.Path, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "(无日志)"
            raise RuntimeError(f"测试服务器异常退出 code={proc.returncode}\n{log[-2000:]}")
        try:
            with urllib.request.urlopen(BASE + "/card/list", timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"测试服务器启动超时\n日志:\n{log_path.read_text(encoding='utf-8', errors='replace')[-2000:]}")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """有头模式（headless=False），E2E_HEADLESS=1 可切无头。"""
    return {**browser_type_launch_args, "headless": os.getenv("E2E_HEADLESS", "0") == "0"}

@pytest.fixture()
def page(context, request):
    """自定义 page：提高导航/操作超时（慢CDN兜底），避免 flaky goto 超时。

    bootstrap CDN 偶发加载慢会阻塞 load 事件导致默认 30s 导航超时（环境网络问题，非应用缺陷）。
    """
    page = context.new_page()
    page.set_default_navigation_timeout(90000)
    page.set_default_timeout(90000)
    yield page
    page.close()


@pytest.fixture(scope="session")
def flask_server(tmp_path_factory):
    """会话级：隔离DB副本 → 子进程启动Flask服务器(5123) → 结束校验真实DB未污染。"""
    data_dir = tmp_path_factory.mktemp("e2e_db")
    core_src = ROOT / "data" / "reqman_db.json"
    if not core_src.exists():
        pytest.skip("缺少 data/reqman_db.json，无法启动e2e服务器")

    core_tmp = data_dir / "reqman_e2e.json"
    shutil.copy(core_src, core_tmp)
    rt_src = ROOT / "data" / "reqman_db_runtime.json"
    rt_tmp = data_dir / "reqman_e2e_runtime.json"
    if rt_src.exists():
        shutil.copy(rt_src, rt_tmp)
    else:
        rt_tmp.write_text("{}", encoding="utf-8")
    cancelled_tmp = data_dir / "cancelled_cards_e2e.json"   # 作废工卡库同样隔离
    cancelled_tmp.write_text("{}", encoding="utf-8")

    # 记录真实DB基线，用于测试后污染校验
    baseline = {core_src: _sha256(core_src), rt_src: _sha256(rt_src)}

    log_dir = tmp_path_factory.mktemp("e2e_logs")
    log_path = log_dir / "server.log"
    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 会话级日志句柄需保持打开

    script = SERVER_SCRIPT.format(db_path=core_tmp, cancelled_path=cancelled_tmp,
                                  src=SRC, port=PORT)
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(ROOT), stdout=log_f, stderr=subprocess.STDOUT,
    )
    try:
        _wait_server(proc, log_path)
        yield BASE
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_f.close()
        # 隔离校验：真实DB必须与测试前一致
        for p, h in baseline.items():
            if p.exists() and _sha256(p) != h:
                raise RuntimeError(f"e2e测试污染了真实DB: {p}（隔离失败！请 git checkout 恢复）")


@pytest.fixture()
def server_base(flask_server) -> str:
    """测试服务器基地址 http://127.0.0.1:5123"""
    return flask_server

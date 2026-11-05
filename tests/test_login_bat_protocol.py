"""start_login.bat 协议参数解析（真实 cmd 验证，防"参数丢失回退本机地址"回归）。

历史缺陷：括号块内用 %VAR% 读到块解析前的旧值（空），导致 ReqManLogin:// 参数丢失，
脚本回退到配置包内置的 127.0.0.1:5001，报 "All connection attempts failed"。
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BAT = SCRIPTS / "start_login.bat"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 批处理")


def _run_parse(tmp_path: Path, *args: str) -> str:
    """执行与 start_login.bat 相同的参数解析片段，返回 TARGET 行。"""
    probe = tmp_path / "probe.bat"
    probe.write_text(
        "@echo off\n"
        "setlocal enabledelayedexpansion\n"
        'set "SERVER_ARG="\n'
        'if not "%~1"=="" (\n'
        '    set "ARG=%~1"\n'
        '    set "HOST=!ARG:ReqManLogin://=!"\n'
        '    if not "!HOST!"=="!ARG!" set "SERVER_ARG=http://!HOST!"\n'
        ")\n"
        "if defined SERVER_ARG (\n"
        "    echo TARGET=!SERVER_ARG!\n"
        ") else (\n"
        "    echo TARGET=BUILTIN\n"
        ")\n",
        encoding="utf-8",
    )
    cmd = ["cmd", "/c", str(probe), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    return result.stdout.strip()


def test_protocol_argument_parsed(tmp_path):
    """ReqManLogin://host → 解析为 http://host（历史缺陷点）。"""
    assert _run_parse(tmp_path, "ReqManLogin://8.137.15.167") == "TARGET=http://8.137.15.167"


def test_protocol_argument_trailing_slash(tmp_path):
    """带尾斜杠时脚本侧 rstrip 处理，BAT 原样透传即可。"""
    assert _run_parse(tmp_path, "ReqManLogin://8.137.15.167/") == "TARGET=http://8.137.15.167/"


def test_no_argument_falls_back_to_builtin(tmp_path):
    """双击运行无参数 → 用配置包内置地址。"""
    assert _run_parse(tmp_path) == "TARGET=BUILTIN"


def test_bat_uses_delayed_expansion():
    """start_login.bat 必须启用延迟展开，且块内不残留 %ARG% 写法。"""
    source = BAT.read_text(encoding="utf-8")
    assert "setlocal enabledelayedexpansion" in source
    assert "!ARG:ReqManLogin://=!" in source
    assert "%ARG:ReqManLogin://=%" not in source
    assert '--server "!SERVER_ARG!"' in source

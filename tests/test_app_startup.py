"""Windows 启动入口的跨编码与端口兜底测试。"""

import subprocess

from reqman import app as app_module


def test_find_pid_by_port_decodes_windows_bytes(monkeypatch):
    output = "活动连接\n  TCP    127.0.0.1:5001    0.0.0.0:0    LISTENING    12345\n".encode("gbk")
    monkeypatch.setattr(app_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(app_module.subprocess, "check_output", lambda *args, **kwargs: output)

    assert app_module.find_pid_by_port(5001) == "12345"


def test_find_pid_by_port_decode_error_fails_closed(monkeypatch):
    monkeypatch.setattr(app_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        app_module.subprocess,
        "check_output",
        lambda *args, **kwargs: b"not valid output",
    )

    assert app_module.find_pid_by_port(5001) is None


def test_kill_process_uses_windows_encoding(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(app_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    assert app_module.kill_process("12345") is True
    args, kwargs = calls[0]
    assert args[0] == ["taskkill", "/F", "/PID", "12345"]
    assert kwargs["encoding"] == "mbcs"
    assert kwargs["errors"] == "replace"


def test_free_port_returns_fallback_when_release_fails(monkeypatch):
    pids = iter(["12345", "12345"])
    monkeypatch.setattr(app_module, "find_pid_by_port", lambda port: next(pids))
    monkeypatch.setattr(app_module, "kill_process", lambda pid: True)
    monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)

    assert app_module.free_port(5001) == 5002


def test_free_port_returns_original_when_available(monkeypatch):
    pids = iter([None])
    monkeypatch.setattr(app_module, "find_pid_by_port", lambda port: next(pids))

    assert app_module.free_port(5001) == 5001

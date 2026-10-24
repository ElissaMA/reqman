"""Windows 启动助手的跨编码与端口兜底测试。

助手已抽离到 reqman.utils.startup（无应用副作用）——
导入 app.py 会连带 create_app() 实例化真实库和 atexit 退出备份，测试禁止导入。
"""

import subprocess

from reqman.utils import startup as startup_module


def test_find_pid_by_port_decodes_windows_bytes(monkeypatch):
    output = "活动连接\n  TCP    127.0.0.1:5001    0.0.0.0:0    LISTENING    12345\n".encode("gbk")
    monkeypatch.setattr(startup_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(startup_module.subprocess, "check_output", lambda *args, **kwargs: output)

    assert startup_module.find_pid_by_port(5001) == "12345"


def test_find_pid_by_port_decode_error_fails_closed(monkeypatch):
    monkeypatch.setattr(startup_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        startup_module.subprocess,
        "check_output",
        lambda *args, **kwargs: b"not valid output",
    )

    assert startup_module.find_pid_by_port(5001) is None


def test_kill_process_uses_windows_encoding(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(startup_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(startup_module.subprocess, "run", fake_run)

    assert startup_module.kill_process("12345") is True
    args, kwargs = calls[0]
    assert args[0] == ["taskkill", "/F", "/PID", "12345"]
    assert kwargs["encoding"] == "mbcs"
    assert kwargs["errors"] == "replace"


def test_free_port_returns_fallback_when_release_fails(monkeypatch):
    pids = iter(["12345", "12345"])
    monkeypatch.setattr(startup_module, "find_pid_by_port", lambda port: next(pids))
    monkeypatch.setattr(startup_module, "kill_process", lambda pid: True)
    monkeypatch.setattr(startup_module.time, "sleep", lambda seconds: None)

    assert startup_module.free_port(5001) == 5002


def test_free_port_returns_original_when_available(monkeypatch):
    pids = iter([None])
    monkeypatch.setattr(startup_module, "find_pid_by_port", lambda port: next(pids))

    assert startup_module.free_port(5001) == 5001


def test_backup_on_exit_writes_gz_and_ignores_missing(tmp_path):
    """退出备份：只打包存在的文件；无文件时不报错（tmp 根下 data 为空）"""
    import gzip
    import json

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "reqman_db.json").write_text(json.dumps({"cards": {}}), encoding="utf-8")

    startup_module._backup_on_exit(project_root=tmp_path)

    backups = list((data_dir / "backups").glob("reqman_db_*.json.gz"))
    assert len(backups) == 1  # runtime 不存在 → 跳过，仅 core 一份
    assert json.loads(gzip.decompress(backups[0].read_bytes())) == {"cards": {}}

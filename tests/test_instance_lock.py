"""单实例锁测试 — 多进程共写防护（存储正确性依赖单进程）。

进程存活探测用 monkeypatch 替身：acquire 的接管/拒绝逻辑在此验证；
真实跨进程行为由 e2e 子进程服务器隐式覆盖（其 JsonStore 初始化即走本锁）。
"""
import json
import os
from pathlib import Path

import pytest

from reqman.utils import instance_lock


def _holder_pid(db_path: str) -> int:
    return json.loads(Path(db_path + ".lock").read_text(encoding="utf-8"))["pid"]


class TestInstanceLock:
    def test_same_process_refcounts(self, tmp_path):
        """同进程重复 acquire：引用计数不报错，锁内 pid 为当前进程"""
        db = str(tmp_path / "a.json")
        instance_lock.acquire(db)
        instance_lock.acquire(db)
        assert _holder_pid(db) == os.getpid()

    def test_foreign_alive_pid_refuses(self, tmp_path, monkeypatch):
        """异进程持锁且存活：拒绝并提示持有者 pid 与解除方法"""
        db = str(tmp_path / "b.json")
        Path(db + ".lock").write_text(json.dumps({"pid": 424242}), encoding="utf-8")
        monkeypatch.setattr(instance_lock, "_pid_alive", lambda pid: True)
        with pytest.raises(instance_lock.InstanceLockError, match="424242"):
            instance_lock.acquire(db)

    def test_dead_pid_takeover(self, tmp_path, monkeypatch):
        """持有进程已退出（崩溃遗留锁）：接管"""
        db = str(tmp_path / "c.json")
        Path(db + ".lock").write_text(json.dumps({"pid": 424243}), encoding="utf-8")
        monkeypatch.setattr(instance_lock, "_pid_alive", lambda pid: False)
        instance_lock.acquire(db)
        assert _holder_pid(db) == os.getpid()

    def test_corrupt_lock_takeover(self, tmp_path):
        """锁文件损坏：视为无主接管"""
        db = str(tmp_path / "d.json")
        Path(db + ".lock").write_text("not-json", encoding="utf-8")
        instance_lock.acquire(db)
        assert _holder_pid(db) == os.getpid()

    def test_reloader_child_takes_over(self, tmp_path, monkeypatch):
        """werkzeug reloader 子进程：接管存活父进程的锁（父进程是 watcher）"""
        db = str(tmp_path / "e.json")
        Path(db + ".lock").write_text(json.dumps({"pid": 424244}), encoding="utf-8")
        monkeypatch.setattr(instance_lock, "_pid_alive", lambda pid: True)
        monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
        instance_lock.acquire(db)
        assert _holder_pid(db) == os.getpid()

    def test_pid_alive_predicates(self):
        assert instance_lock._pid_alive(0) is False
        assert instance_lock._pid_alive(-5) is False
        assert instance_lock._pid_alive("x") is False
        assert instance_lock._pid_alive(os.getpid()) is True  # 当前进程必然存活

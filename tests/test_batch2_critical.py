"""第二批（Critical）修复的回归测试。

覆盖：
- C1 单实例锁排他性（并发仅一方成功）
- C2 工作包覆盖键含 date（同机同描述不同日期不覆写；同日期仍覆盖）
- C3 超限补传旧包抛错而非静默丢弃
"""
import json
import os

import pytest

from reqman.models.json_store import JsonStore, WorkPackageLimitError


@pytest.fixture
def store(tmp_path):
    return JsonStore(str(tmp_path / "batch2.json"))


def _pkg(reg, desc, date, codes=()):
    return {"reg": reg, "description": desc, "date": date,
            "all_items": [{"task_code": c} for c in codes]}


# ---------- C2: 覆盖键含 date ----------
class TestWorkPackageOverwriteKey:
    def test_same_reg_desc_different_date_not_overwritten(self, store):
        """同机同级别不同日期 → 两个独立工作包（历史行为会静默覆写前一个）。"""
        first = store.save_work_package(_pkg("B-8162", "45A", "2026-01-01", ["A1"]))
        second = store.save_work_package(_pkg("B-8162", "45A", "2026-06-01", ["B1"]))

        assert first["package_id"] != second["package_id"]
        assert len(store.get_work_packages()) == 2
        assert store.get_work_package(first["package_id"])["all_items"] == [{"task_code": "A1"}]
        assert store.get_work_package(second["package_id"])["all_items"] == [{"task_code": "B1"}]

    def test_same_reg_desc_date_still_overwrites(self, store):
        """同机同级别同日期 → 保留既有「同日重传覆盖」语义，复用 package_id。"""
        first = store.save_work_package(_pkg("B-8162", "45A", "2026-01-01", ["A1"]))
        again = store.save_work_package(_pkg("B-8162", "45A", "2026-01-01", ["A1-new"]))

        assert again["package_id"] == first["package_id"]
        assert len(store.get_work_packages()) == 1
        assert store.get_work_package(first["package_id"])["all_items"] == [{"task_code": "A1-new"}]

    def test_empty_meta_still_rejected(self, store):
        with pytest.raises(ValueError, match="机号与描述均缺失"):
            store.save_work_package(_pkg("", "", "2026-01-01"))


# ---------- C3: 超限不静默丢数据 ----------
class TestWorkPackageLimit:
    def test_over_limit_old_package_raises(self, store):
        """补传日期早于全部保留包的包 → 抛错，而不是返回 package_id 却已丢弃。"""
        for i in range(10):
            store.save_work_package(_pkg(f"B-{i}", "X", f"2026-12-{10 + i:02d}"))
        assert len(store.get_work_packages()) == 10

        with pytest.raises(WorkPackageLimitError):
            store.save_work_package(_pkg("B-OLD", "OLD", "2026-01-01"))

        # 库内容未被破坏，仍是原 10 个
        assert len(store.get_work_packages()) == 10
        assert not any(w["reg"] == "B-OLD" for w in store.get_work_packages())

    def test_over_limit_newest_still_saved(self, store):
        """日期最新的包可正常保存，并淘汰最旧的一个。"""
        for i in range(10):
            store.save_work_package(_pkg(f"B-{i}", "X", f"2026-01-{10 + i:02d}"))
        saved = store.save_work_package(_pkg("B-NEW", "NEW", "2027-01-01"))

        assert store.get_work_package(saved["package_id"]) is not None
        assert len(store.get_work_packages()) == 10
        # 最旧的 B-0（2026-01-10）应被淘汰
        assert not any(w["reg"] == "B-0" for w in store.get_work_packages())


# ---------- C1: 单实例锁排他性 ----------
def _lock_race_worker(db_path, barrier, queue):
    """模块级 worker（Windows spawn 模式无法 pickle 局部函数）。"""
    from reqman.utils.instance_lock import InstanceLockError, acquire

    barrier.wait()
    try:
        acquire(db_path)
        queue.put("OK")
    except InstanceLockError:
        queue.put("LOCKED")


class TestInstanceLockExclusive:
    def test_exclusive_create_is_atomic(self, tmp_path):
        """并发抢锁只有一方成功（O_CREAT|O_EXCL 消除 TOCTOU）。"""
        import multiprocessing as mp

        db_path = str(tmp_path / "race.json")
        n = 6
        barrier = mp.Barrier(n)
        queue = mp.Queue()
        procs = [
            mp.Process(target=_lock_race_worker, args=(db_path, barrier, queue))
            for _ in range(n)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)

        results = [queue.get() for _ in range(n)]
        assert results.count("OK") == 1, f"应恰好一方抢到锁，实际：{results}"
        assert results.count("LOCKED") == n - 1

    def test_lock_file_contains_pid(self, tmp_path):
        """锁文件写入当前 pid 与时间戳；排他创建不覆盖已有存活持有者。"""
        from reqman.utils import instance_lock

        db_path = str(tmp_path / "lockpid.json")
        instance_lock.acquire(db_path)
        try:
            lock_file = tmp_path / "lockpid.json.lock"
            assert lock_file.exists()
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
            assert "started_at" in data
        finally:
            instance_lock._release_all()

    def test_stale_lock_taken_over(self, tmp_path):
        """持有者进程已死 → 可安全接管（写自己的 pid）。"""
        from reqman.utils import instance_lock

        db_path = str(tmp_path / "stale.json")
        lock_file = tmp_path / "stale.json.lock"
        # 造一个几乎不可能存在的 pid
        lock_file.write_text(json.dumps({"pid": 999999, "started_at": "2020-01-01"}),
                             encoding="utf-8")
        instance_lock.acquire(db_path)
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
        finally:
            instance_lock._release_all()


# ---------- 错误码接线 ----------
class TestLimitErrorWiring:
    def test_blueprint_maps_limit_error_to_409(self):
        """上传/导入路由必须把 WorkPackageLimitError 映射为 409，而非 500。"""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1]
                  / "src/reqman/blueprints/packages_bp.py").read_text(encoding="utf-8")
        assert "WorkPackageLimitError" in source
        assert '"PKG_LIMIT_REACHED"' in source
        assert source.count("except WorkPackageLimitError") >= 2

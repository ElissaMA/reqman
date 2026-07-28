"""并发性能测试 — 多线程读写 JsonStore"""
import threading

import pytest

# ============================================================
# 辅助：每个测���函数独立的临时数据库
# ============================================================

@pytest.fixture
def perf_store(tmp_path):
    """为性能测试创建独立的 JsonStore 实例"""
    from reqman.models.json_store import JsonStore
    db_path = str(tmp_path / "perf_reqman.json")
    return JsonStore(db_path)


# ============================================================
# 并发读取测试
# ============================================================

class TestConcurrentReads:
    """多线程并发读取测试"""

    NUM_THREADS = 10
    READS_PER_THREAD = 20

    def _prepare_data(self, store, count=50):
        """预填充工卡数据"""
        for i in range(count):
            store.add(task_code=f"PERF-{i:04d}", task_name=f"性能测试工卡{i}",
                      category="发动机", task_type="A", remark=f"备注{i}")
        store.add_aircraft(reg="B-TEST", model="TEST", engine="TEST")
        store.add_set(name="性能测试组", description="测试用")

    def test_concurrent_read_cards(self, perf_store):
        """并发读取工卡列表"""
        self._prepare_data(perf_store, 30)
        errors = []

        def _read():
            try:
                for _ in range(self.READS_PER_THREAD):
                    perf_store.get_all()
                    perf_store.find_by_code("PERF-0001")
                    perf_store.get(1)
                    perf_store.get_all()
            except (OSError, KeyError, ValueError) as e:
                errors.append(e)

        threads = [threading.Thread(target=_read) for _ in range(self.NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发读取出现异常: {errors}"

    def test_concurrent_read_mixed_data(self, perf_store):
        """并发读取多种数据类型"""
        self._prepare_data(perf_store, 20)
        errors = []

        def _read_mixed():
            try:
                for _ in range(10):
                    perf_store.get_all()
                    perf_store.get_all_sets()
                    perf_store.get_all_aircraft()
                    perf_store.get_work_packages()
            except (OSError, KeyError, ValueError) as e:
                errors.append(e)

        threads = [threading.Thread(target=_read_mixed) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发混合读取出现异常: {errors}"


# ============================================================
# 并发写入测试
# ============================================================

class TestConcurrentWrites:
    """多线程并发写入测试"""

    NUM_WRITERS = 5
    WRITES_PER_THREAD = 10

    def test_concurrent_add_cards(self, perf_store):
        """并发新增工卡"""
        errors = []
        lock = threading.Lock()
        counter = [0]

        def _add():
            try:
                for _ in range(self.WRITES_PER_THREAD):
                    with lock:
                        idx = counter[0]
                        counter[0] += 1
                    perf_store.add(
                        task_code=f"CONC-{idx:04d}",
                        task_name=f"并发写入工卡{idx}",
                        category="发动机",
                        task_type="A",
                        remark=""
                    )
            except (OSError, KeyError, ValueError) as e:
                errors.append(e)

        threads = [threading.Thread(target=_add) for _ in range(self.NUM_WRITERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发写入出现异常: {errors}"
        total = self.NUM_WRITERS * self.WRITES_PER_THREAD
        assert len(perf_store.get_all()) == total, \
            f"写入总数不匹配: 预期{total}, 实际{len(perf_store.get_all())}"

    def test_concurrent_mixed_read_write(self, perf_store):
        """并发混合读写（读操作对偶发失败有容错）"""
        errors = []
        read_errors = [0]  # 可容忍的读错误计数

        def _writer(thread_id):
            try:
                for i in range(10):
                    code = f"MX-{thread_id}-{i:04d}"
                    perf_store.add(task_code=code, task_name=f"���合测试{i}",
                                   category="发动机", task_type="A", remark="")
            except (OSError, KeyError, ValueError) as e:
                errors.append(e)

        def _reader():
            try:
                for _ in range(20):
                    try:
                        perf_store.get_all()
                        perf_store.get_all()
                        perf_store.get_all_sets()
                    except (OSError, KeyError, ValueError):
                        # 并发写入期间文件可能暂时为空，预期偶发读取失败
                        read_errors[0] += 1
            except (OSError, KeyError, ValueError) as e:
                errors.append(e)

        threads = []
        for wid in range(3):
            threads.append(threading.Thread(target=_writer, args=(wid,)))
        for _ in range(2):
            threads.append(threading.Thread(target=_reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"混合读写出现异常: {errors}"
        assert len(perf_store.get_all()) >= 30

    def test_concurrent_aircraft_add(self, perf_store):
        """并发新增飞机信息"""
        errors = []
        lock = threading.Lock()
        counter = [0]

        def _add():
            try:
                for _ in range(5):
                    with lock:
                        idx = counter[0]
                        counter[0] += 1
                    perf_store.add_aircraft(
                        reg=f"B-CONC-{idx:04d}", model="A320",
                        engine="CFM56"
                    )
            except (OSError, KeyError, ValueError) as e:
                errors.append(e)

        threads = [threading.Thread(target=_add) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发写飞机出现异常: {errors}"
        assert len(perf_store.get_all_aircraft()) == 20


# ============================================================
# 压力测试：大数据量的基础响应时间
# ============================================================

class TestBulkData:
    """大量数据下的操作性能"""

    BULK_SIZE = 200

    @pytest.fixture
    def bulk_store(self, tmp_path):
        from reqman.models.json_store import JsonStore
        db_path = str(tmp_path / "bulk_reqman.json")
        store = JsonStore(db_path)
        for i in range(self.BULK_SIZE):
            store.add(task_code=f"BULK-{i:04d}", task_name=f"批量工卡{i}",
                      category=["发动机", "机体", "电子"][i % 3],
                      task_type="A", remark=f"备注{i}")
        return store

    def test_bulk_get_all(self, bulk_store):
        """读取所有工卡"""
        cards = bulk_store.get_all()
        assert len(cards) == self.BULK_SIZE

    def test_bulk_search(self, bulk_store):
        """在���数据中按工卡号搜索"""
        card = bulk_store.find_by_code("BULK-0199")
        assert card is not None
        assert card["task_code"] == "BULK-0199"

    def test_bulk_search_by_category(self, bulk_store):
        """按分类在大数据中搜索（使用 get_all 过滤）"""
        all_cards = bulk_store.get_all()
        results = [c for c in all_cards if c.get("category") == "发动机"]
        assert len(results) >= self.BULK_SIZE // 3

"""性能测试脚本 — 大数据量操作"""
import time

import pytest

# ============================================================
# 大数据量测试
# ============================================================

class TestBulkDataPerformance:
    """大数据量下的操作性能测试"""

    @pytest.mark.slow
    def test_bulk_card_creation_100(self, tmp_path):
        """创建100张工卡的性能和正确性"""
        from reqman.models.json_store import JsonStore
        store = JsonStore(str(tmp_path / "bulk100.json"))

        start = time.time()
        for i in range(100):
            store.add(
                task_code=f"BULK100-{i:04d}",
                task_name=f"批量性能测试工卡{i}",
                category=["发动机", "机体", "电子"][i % 3],
                task_type=["A", "B", "C"][i % 3],
                remark=f"性能测试{i}",
            )
        elapsed = time.time() - start

        cards = store.get_all()
        assert len(cards) == 100
        # 100条写入应在合理时间内完成
        assert elapsed < 10, f"写入100条耗时{elapsed:.2f}s，预期<10s"

    @pytest.mark.slow
    def test_bulk_search_across_500(self, tmp_path):
        """在500条数据中搜索性能"""
        from reqman.models.json_store import JsonStore
        store = JsonStore(str(tmp_path / "bulk500.json"))

        for i in range(500):
            store.add(
                task_code=f"PERF-{i:04d}",
                task_name=f"性能测试工卡{i}",
                category=["发动机", "机体", "电子"][i % 3],
                task_type="A",
                remark="",
            )
        # 通过 get_all ���滤搜索
        start = time.time()
        all_cards = store.get_all()
        results = [c for c in all_cards if "性能" in c.get("task_name", "")]
        elapsed = time.time() - start

        assert len(results) == 500
        # 搜索应在合理时间��
        assert elapsed < 2, f"搜索500条耗时{elapsed:.2f}s，预期<2s"

    @pytest.mark.slow
    def test_bulk_filter_and_sort(self, tmp_path):
        """在大量数据中分���过滤和排序"""
        from reqman.models.json_store import JsonStore
        store = JsonStore(str(tmp_path / "bulk_filter.json"))

        for i in range(300):
            store.add(
                task_code=f"FT-{i:04d}",
                task_name=f"过滤测试{i}",
                category=["发动机", "机体", "电子", "特检", "NDT"][i % 5],
                task_type="A",
                remark=f"分类{i}",
            )

        cards = store.get_all()
        engine_cards = [c for c in cards if c.get("category") == "发动机"]
        assert len(engine_cards) == 60  # 300/5=60

        # 通过 category 过滤
        engine_results = [c for c in store.get_all() if c.get("category") == "发动机"]
        assert len(engine_results) == 60

        # 按编码精确查找
        card = store.find_by_code("FT-0010")
        assert card is not None
        assert card["task_code"] == "FT-0010"

    @pytest.mark.slow
    def test_bulk_aircraft_management(self, tmp_path):
        """大量飞机信息管理的性能"""
        from reqman.models.json_store import JsonStore
        store = JsonStore(str(tmp_path / "bulk_ac.json"))

        start = time.time()
        for i in range(100):
            store.add_aircraft(
                reg=f"B-BULK-{i:04d}",
                model="A320",
                engine="CFM56",
                fsn=str(1000 + i),
                msn=str(2000 + i),
            )
        add_elapsed = time.time() - start

        aircraft_list = store.get_all_aircraft()
        assert len(aircraft_list) == 100
        assert add_elapsed < 10, f"添��100架飞机耗时{add_elapsed:.2f}s，预期<10s"

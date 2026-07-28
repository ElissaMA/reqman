"""日志清理测试"""
from reqman.models.json_store import JsonStore


class TestLogCleanup:
    def test_trim_logs_preserves_newest(self, json_store: JsonStore):
        """裁剪保留最新日志"""
        for i in range(5):
            json_store.add(f"CARD-{i:03d}", f"工卡{i}", "发动机", "A", "")
        json_store.trim_logs(max_count=2)
        logs = json_store.get_logs()
        assert len(logs) == 2

    def test_trim_logs_returns_deleted_count(self, json_store: JsonStore):
        """裁剪返回删除数量"""
        for i in range(8):
            json_store.add(f"CARD-{i:03d}", f"工卡{i}", "发动机", "A", "")
        deleted = json_store.trim_logs(max_count=5)
        assert deleted == 3

    def test_trim_logs_empty(self, json_store: JsonStore):
        """空日志裁剪返回0"""
        assert json_store.trim_logs() == 0

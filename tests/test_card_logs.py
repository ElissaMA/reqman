"""日志功能测试"""
import pytest
from reqman.models.json_store import JsonStore


class TestCardLogs:
    def test_add_log(self, json_store: JsonStore):
        """添加工卡日志"""
        json_store.add("CARD-001", "测试工卡", "发动机", "A", "")
        logs = json_store.get_logs()
        assert len(logs) >= 1
        # 最新日志排在最前面
        assert logs[0]["operation"] == "add"
        assert logs[0]["target_type"] == "card"

    def test_add_log_id_auto_increment(self, json_store: JsonStore):
        """日志ID自增"""
        json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        json_store.add("CARD-002", "工卡2", "发动机", "A", "")
        logs = json_store.get_logs()
        ids = [l["id"] for l in logs]
        # get_logs 按时间降序返回，所以最新日志在前、ID更大
        assert ids == sorted(ids, reverse=True)
        assert len(set(ids)) == len(ids)  # 无重复ID

    def test_update_log(self, json_store: JsonStore):
        """更新工卡产生日志"""
        r = json_store.add("CARD-001", "旧名称", "发动机", "A", "")
        json_store.update(r["id"], task_name="新名称")
        logs = json_store.get_logs(operation="update")
        assert len(logs) >= 1

    def test_delete_log(self, json_store: JsonStore):
        """删除工卡产生日志"""
        r = json_store.add("CARD-001", "待删除", "发动机", "A", "")
        json_store.delete(r["id"])
        logs = json_store.get_logs(operation="delete")
        assert len(logs) >= 1

    def test_get_logs_filter_operation(self, json_store: JsonStore):
        """按操作类型筛选"""
        json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        r = json_store.add("CARD-002", "工卡2", "发动机", "A", "")
        json_store.update(r["id"], task_name="新名称")
        add_logs = json_store.get_logs(operation="add")
        update_logs = json_store.get_logs(operation="update")
        assert len(add_logs) >= 2
        assert len(update_logs) >= 1

    def test_get_logs_filter_target_type(self, json_store: JsonStore):
        """按目标类型筛选"""
        json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        json_store.add_set(name="测试组", description="", category="发动机")
        card_logs = json_store.get_logs(target_type="card")
        set_logs = json_store.get_logs(target_type="set")
        assert len(card_logs) >= 1
        assert len(set_logs) >= 1

    def test_get_logs_limit(self, json_store: JsonStore):
        """limit参数限制返回数量"""
        for i in range(5):
            json_store.add(f"CARD-{i:03d}", f"工卡{i}", "发动机", "A", "")
        logs = json_store.get_logs(limit=3)
        assert len(logs) == 3

    def test_delete_logs(self, json_store: JsonStore):
        """删除指定日志"""
        json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        logs = json_store.get_logs()
        log_ids = [l["id"] for l in logs]
        deleted = json_store.delete_logs(log_ids[:1])
        assert deleted >= 1

    def test_delete_logs_not_found(self, json_store: JsonStore):
        """删除不存在的日志返回0"""
        deleted = json_store.delete_logs([99999])
        assert deleted == 0

    def test_trim_logs(self, json_store: JsonStore):
        """裁剪日志保留最新N条"""
        for i in range(10):
            json_store.add(f"CARD-{i:03d}", f"工卡{i}", "发动机", "A", "")
        deleted = json_store.trim_logs(max_count=3)
        assert deleted >= 7
        assert len(json_store.get_logs()) == 3

    def test_trim_logs_under_limit(self, json_store: JsonStore):
        """未超上限时返回0"""
        json_store.add("CARD-001", "工卡1", "发动机", "A", "")
        deleted = json_store.trim_logs(max_count=100)
        assert deleted == 0

    def test_trim_logs_empty(self, json_store: JsonStore):
        """空日志返回0"""
        deleted = json_store.trim_logs(max_count=5)
        assert deleted == 0

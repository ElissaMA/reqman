"""工作包功能测试"""
from reqman.models.json_store import JsonStore


class TestWorkPackages:
    def test_save_work_package(self, json_store: JsonStore):
        """新增工作包"""
        data = {"reg": "B-1234", "description": "A320定检", "date": "2026.07.22", "all_items": []}
        result = json_store.save_work_package(data)
        assert "package_id" in result
        assert len(json_store.get_work_packages()) == 1

    def test_save_work_package_update(self, json_store: JsonStore):
        """更新已存在的工作包（相同reg+description）"""
        data1 = {"reg": "B-1234", "description": "A320定检", "date": "2026.07.22", "all_items": []}
        json_store.save_work_package(data1)
        data2 = {"reg": "B-1234", "description": "A320定检", "date": "2026.07.23", "all_items": [{"code": "NEW"}]}
        json_store.save_work_package(data2)  # 覆盖保存
        wps = json_store.get_work_packages()
        assert len(wps) == 1
        assert wps[0]["date"] == "2026.07.23"

    def test_get_work_packages(self, json_store: JsonStore):
        """获取所有工作包（按日期升序）"""
        json_store.save_work_package({"reg": "B-1234", "description": "包1", "date": "2026.07.22"})
        json_store.save_work_package({"reg": "B-5678", "description": "包2", "date": "2026.07.20"})
        wps = json_store.get_work_packages()
        assert len(wps) == 2
        # 按日期升序排列
        assert wps[0]["date"] <= wps[1]["date"]

    def test_get_work_package(self, json_store: JsonStore):
        """获取单个工作包"""
        data = json_store.save_work_package({"reg": "B-1234", "description": "测试", "date": "2026.07.22"})
        wp = json_store.get_work_package(data["package_id"])
        assert wp is not None
        assert wp["reg"] == "B-1234"

    def test_get_work_package_not_found(self, json_store: JsonStore):
        """获取不存在的工作包返回None"""
        assert json_store.get_work_package("nonexistent") is None

    def test_delete_work_package(self, json_store: JsonStore):
        """删除工作包"""
        data = json_store.save_work_package({"reg": "B-1234", "description": "测试", "date": "2026.07.22"})
        assert json_store.delete_work_package(data["package_id"]) is True
        assert len(json_store.get_work_packages()) == 0

    def test_delete_work_package_not_found(self, json_store: JsonStore):
        """删除不存在的工作包返回False"""
        assert json_store.delete_work_package("nonexistent") is False

    def test_work_package_limit_10(self, json_store: JsonStore):
        """工作包数量超过10个时保留最新10个"""
        for i in range(12):
            json_store.save_work_package({"reg": f"B-{i:04d}", "description": f"包{i}", "date": f"2026.07.{i:02d}"})
        wps = json_store.get_work_packages()
        assert len(wps) == 10

    def test_work_package_id_auto_generate(self, json_store: JsonStore):
        """未提供package_id时自动生成UUID"""
        data = json_store.save_work_package({"reg": "B-1234", "description": "测试", "date": "2026.07.22"})
        assert len(data["package_id"]) > 0

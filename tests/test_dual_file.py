"""双文件存储测试"""
import json
import os
from pathlib import Path

from reqman.models.json_store import JsonStore


class TestDualFileStorage:
    def test_write_splits_files(self, tmp_path):
        """写入时拆分到两个文件"""
        db_path = str(tmp_path / "test.json")
        store = JsonStore(db_path)
        store.add("CARD-001", "工卡1", "发动机", "A", "")
        store.save_work_package({"reg": "B-1234", "description": "测试", "date": "2026.07.22"})

        runtime_path = str(tmp_path / "test_runtime.json")
        assert os.path.exists(db_path)
        assert os.path.exists(runtime_path)

        core = json.loads(Path(db_path).read_text(encoding="utf-8"))
        runtime = json.loads(Path(runtime_path).read_text(encoding="utf-8"))

        assert "cards" in core
        assert "work_packages" in runtime

    def test_read_merges_files(self, tmp_path):
        """读取时合并两个文件"""
        db_path = str(tmp_path / "test.json")
        runtime_path = str(tmp_path / "test_runtime.json")

        # 手动写入两个文件
        Path(db_path).write_text(json.dumps({"cards": {"1": {"id": 1, "task_code": "C-001"}}}), encoding="utf-8")
        Path(runtime_path).write_text(json.dumps({"work_packages": [{"package_id": "wp-1"}]}), encoding="utf-8")

        store = JsonStore(db_path)
        data = store._read()
        assert "cards" in data
        assert "work_packages" in data

    def test_init_db_migrates_old_file(self, tmp_path):
        """旧单文件自动迁移到双文件"""
        db_path = str(tmp_path / "test.json")
        # 写入旧格式（所有数据在一个文件）
        Path(db_path).write_text(json.dumps({
            "cards": {"1": {"id": 1, "task_code": "C-001"}},
            "work_packages": [{"package_id": "wp-1"}],
            "next_id": 2
        }), encoding="utf-8")

        store = JsonStore(db_path)
        data = store._read()
        assert "cards" in data
        assert "work_packages" in data

    def test_runtime_keys_classification(self):
        """运行时键列表正确分类（card_logs 已迁移到核心数据）"""
        from reqman.models.json_store import _RUNTIME_KEYS
        assert "work_packages" in _RUNTIME_KEYS
        assert "card_logs" not in _RUNTIME_KEYS
        assert "card_log_next_id" not in _RUNTIME_KEYS
        assert "next_id" in _RUNTIME_KEYS
        assert "code_index" in _RUNTIME_KEYS
        assert "cards" not in _RUNTIME_KEYS
        assert "card_sets" not in _RUNTIME_KEYS
        assert "aircraft" not in _RUNTIME_KEYS

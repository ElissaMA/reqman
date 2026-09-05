"""日期工具与版本变动清单日期格式化测试"""

from reqman.blueprints.packages_bp import _version_log_rows
from reqman.utils.dates import fmt_date10


class _FakeStore:
    def __init__(self, logs):
        self._logs = logs

    def get_version_logs(self, limit=50):
        return self._logs[:limit]


class TestFmtDate10:
    def test_full_datetime_truncated(self):
        assert fmt_date10("2026-08-01 09:00:00") == "2026-08-01"

    def test_already_date(self):
        assert fmt_date10("2026-08-01") == "2026-08-01"

    def test_empty(self):
        assert fmt_date10("") == ""

    def test_none(self):
        assert fmt_date10(None) == ""

    def test_short_value_preserved(self):
        assert fmt_date10("2026") == "2026"


class TestVersionLogRowsDate:
    def test_write_date_formatted_to_yyyy_mm_dd(self):
        store = _FakeStore([{
            "timestamp": "2026-08-01T09:00:00",
            "target_identifier": "CSC-A320-1001-1",
            "target_name": "测试工卡",
            "operation": "update",
            "changes": [{"field": "write_date",
                         "old": "2026-07-01 08:00:00",
                         "new": "2026-08-01 09:00:00"}],
        }])
        rows = _version_log_rows(store)
        assert len(rows) == 1
        assert rows[0]["old"] == "2026-07-01"
        assert rows[0]["new"] == "2026-08-01"

    def test_missing_old_keeps_empty(self):
        store = _FakeStore([{
            "timestamp": "2026-08-01T09:00:00",
            "target_identifier": "CSC-A320-1001-1",
            "target_name": "测试工卡",
            "operation": "update",
            "changes": [{"field": "write_date", "new": "2026-08-01 09:00:00"}],
        }])
        rows = _version_log_rows(store)
        assert rows[0]["old"] == ""
        assert rows[0]["new"] == "2026-08-01"

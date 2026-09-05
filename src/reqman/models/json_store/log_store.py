"""JsonStore 业务方法：变更日志 + AMRO 版本日志查询。"""

from .work_package_store import WorkPackageStore


class LogStore(WorkPackageStore):
    # ---------- 日志查询 ----------

    def get_logs(self, operation: str | None = None, target_type: str | None = None,
                 start_date: str | None = None, end_date: str | None = None,
                 limit: int = 100) -> list[dict]:
        """查询日志，支持按操作类型、目标类型、时间范围筛选，按时间降序"""
        db = self._read()
        logs = list(db.get("card_logs", []))
        if operation:
            logs = [log for log in logs if log.get("operation") == operation]
        if target_type:
            logs = [log for log in logs if log.get("target_type") == target_type]
        if start_date:
            logs = [log for log in logs if log.get("timestamp", "") >= start_date]
        if end_date:
            logs = [log for log in logs if log.get("timestamp", "") <= end_date]
        logs.sort(key=lambda log: log.get("timestamp", ""), reverse=True)
        return logs[:limit]

    def delete_logs(self, log_ids: list[int]) -> int:
        """删除指定 ID 的日志，返回删除数量"""
        with self._lock:
            db = self._read()
            logs = db.get("card_logs", [])
            log_ids_set = set(log_ids)
            new_logs = [log for log in logs if log.get("id") not in log_ids_set]
            deleted = len(logs) - len(new_logs)
            if deleted:
                db["card_logs"] = new_logs
                self._write(db)
            return deleted

    # ---------- AMRO 版本日志（v3.5.0） ----------

    def get_version_logs(self, limit: int = 100) -> list[dict]:
        """版本变动日志：card_logs 倒序筛选 changes 含 write_date 的条目（不建新存储）。"""
        db = self._read()
        logs = [log for log in db.get("card_logs", [])
                if any(c.get("field") == "write_date" for c in log.get("changes", []))]
        logs.sort(key=lambda log: (log.get("timestamp", ""), log.get("id", 0)), reverse=True)
        return logs[:limit]

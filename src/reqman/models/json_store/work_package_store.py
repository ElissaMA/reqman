"""JsonStore 业务方法：工作包 + 库存预警持久化。"""

import uuid

from .card_store import CardStore


class WorkPackageStore(CardStore):
    # ---------- 工作包数据库 ----------

    def save_work_package(self, data):
        with self._lock:
            db = self._read()
            wps = db.setdefault("work_packages", [])
            if "package_id" not in data:
                data["package_id"] = str(uuid.uuid4())
            for i, wp in enumerate(wps):
                if wp.get("reg") == data["reg"] and wp.get("description") == data["description"]:
                    data["package_id"] = wp.get("package_id", data["package_id"])
                    wps[i] = data
                    self._write(db)
                    return data
            wps.append(data)
            if len(wps) > 10:
                wps.sort(key=lambda x: x.get("date", ""), reverse=True)
                wps[:] = wps[:10]
            self._write(db)
            return data

    def get_work_packages(self):
        db = self._read()
        wps = db.get("work_packages", [])
        return sorted(wps, key=lambda x: x.get("date", ""), reverse=False)

    def get_work_package(self, package_id: str) -> dict | None:
        db = self._read()
        for wp in db.get("work_packages", []):
            if wp.get("package_id") == package_id:
                return dict(wp)
        return None

    def delete_work_package(self, package_id: str) -> bool:
        with self._lock:
            db = self._read()
            wps = db.get("work_packages", [])
            new_wps = [w for w in wps if w.get("package_id") != package_id]
            if len(new_wps) == len(wps):
                return False
            db["work_packages"] = new_wps
            self._write(db)
            return True

    # ---------- 库存预警数据库 ----------

    def save_inventory_warning(self, data: dict) -> dict:
        """新增或更新库存预警条目（按 part_number 唯一）。

        合并传入字段，保留已有 id/threshold/name/note；仅回写库存（stock）时
        传入 {"part_number": pn, "stock": value} 即可，不会清掉其他字段。
        """
        with self._lock:
            db = self._read()
            warnings = db.setdefault("inventory_warnings", [])
            pn = str(data.get("part_number", "")).strip().upper()
            if not pn:
                raise ValueError("件号不能为空")
            existing = next(
                (w for w in warnings if w.get("part_number", "").upper() == pn), None
            )
            if existing is not None:
                for k, v in data.items():
                    if k == "part_number":
                        continue
                    existing[k] = v
                self._write(db)
                return dict(existing)
            entry = {
                "id": str(uuid.uuid4()),
                "part_number": pn,
                "name": data.get("name", "") or "",
                "threshold": data.get("threshold", 0.0),
                "stock": data.get("stock", None),
                "note": data.get("note", "") or "",
            }
            warnings.append(entry)
            self._write(db)
            return dict(entry)

    def get_inventory_warnings(self) -> list[dict]:
        db = self._read()
        return sorted(
            (dict(w) for w in db.get("inventory_warnings", [])),
            key=lambda x: x.get("part_number", "").upper(),
        )

    def get_inventory_warning(self, part_number: str) -> dict | None:
        db = self._read()
        pn = str(part_number).strip().upper()
        for w in db.get("inventory_warnings", []):
            if w.get("part_number", "").upper() == pn:
                return dict(w)
        return None

    def delete_inventory_warning(self, part_number: str) -> bool:
        with self._lock:
            db = self._read()
            warnings = db.get("inventory_warnings", [])
            pn = str(part_number).strip().upper()
            new = [w for w in warnings if w.get("part_number", "").upper() != pn]
            if len(new) == len(warnings):
                return False
            db["inventory_warnings"] = new
            self._write(db)
            return True

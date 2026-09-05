"""JsonStore 业务方法：工卡 / 工卡组 / 飞机信息 CRUD + 工卡组同步。"""

from ...config import CATEGORIES
from .core import JsonStoreCore, _today_iso


class CardStore(JsonStoreCore):
    # ---------- 工卡 CRUD ----------

    def get_all(self, search: str = "", category: str = "",
                reminder_type: str = "") -> list[dict]:
        db = self._read()
        cards = list(db.get("cards", {}).values())

        if search:
            keyword = search.lower()
            cards = [
                card for card in cards
                if keyword in card.get("task_code", "").lower() or keyword in card.get("task_name", "").lower()
            ]

        if category:
            cards = [card for card in cards if card.get("category") == category]

        if reminder_type:
            cards = [card for card in cards if card.get("reminder_type") == reminder_type]

        # 按 专业 → 工卡号 排序
        cat_order = {cat: i for i, cat in enumerate(CATEGORIES)}
        cards.sort(key=lambda card: (cat_order.get(card.get("category"), 99), card.get("task_code", "")))
        return cards

    def get(self, card_id: int) -> dict | None:
        db = self._read()
        card = db.get("cards", {}).get(str(card_id))
        return self._norm(card, "card") if card else None

    def find_by_code(self, code: str) -> dict | None:
        db = self._read()
        card_id = db.get("code_index", {}).get(code)
        if card_id is None:
            return None
        card = db.get("cards", {}).get(str(card_id))
        return self._norm(card, "card") if card else None

    def find_by_codes(self, codes: list[str]) -> dict[str, dict]:
        """批量按工卡号查卡：单次读取，返回 {code: card}（查无的 code 不出现）。

        消除逐卡 find_by_code 的 N+1 整库重读。
        """
        if not codes:
            return {}
        db = self._read()
        cards = db.get("cards", {})
        index = db.get("code_index", {})
        result: dict[str, dict] = {}
        seen: set[str] = set()
        for raw in codes:
            code = str(raw).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            card_id = index.get(code)
            if card_id is None:
                continue
            card = cards.get(str(card_id))
            if card:
                result[code] = self._norm(card, "card")
        return result

    def add(self, task_code: str, task_name: str = "",
            category: str = "机体", task_type: str = "",
            remark: str = "", reminder_type: str = "") -> dict | None:
        with self._lock:
            db = self._read()

            # 检查重复
            if task_code in db.get("code_index", {}):
                return None

            if category not in CATEGORIES:
                category = "机体"

            card_id = self._next_id(db)
            card = {
                "id": card_id,
                "task_code": task_code,
                "task_name": task_name,
                "category": category,
                "task_type": task_type,
                "remark": remark,
                "tools": [],
                "materials": [],
                "tools_confirmed": False,
                "materials_confirmed": False,
                "set_id": None,
                "reminder_type": reminder_type,
                "card_ok": False,
                "reminder_confirmed": False,
                "log_time": _today_iso(),
            }

            db.setdefault("cards", {})[str(card_id)] = card
            db.setdefault("code_index", {})[task_code] = card_id

            self._add_log(db, "add", "card", card_id, task_code, task_name, [])
            self._write(db)
            return self._norm(card, "card")

    def update(self, card_id: int, **kwargs) -> dict | None:
        with self._lock:
            db = self._read()
            card = db.get("cards", {}).get(str(card_id))
            if card is None:
                return None

            old_card = dict(card)  # 变更前快照
            old_code = card.get("task_code")

            for key in ("task_code", "task_name", "category",
                        "task_type", "remark", "tools", "materials",
                        "set_id", "tools_confirmed", "materials_confirmed",
                        "reminder_type", "card_ok", "reminder_confirmed", "write_date"):
                if key in kwargs:
                    card[key] = kwargs[key]

            # 数据库条目的新建/编辑日志时间：任何更新都刷新为当天
            card["log_time"] = _today_iso()

            # 如果编码变了，更新索引（新码不得占用其他卡，堵住脏索引源头）
            new_code = card.get("task_code")
            if old_code and old_code != new_code:
                owner = db.get("code_index", {}).get(new_code)
                if new_code and owner is not None and owner != card_id:
                    raise ValueError(f"工卡号 {new_code} 已存在（卡 {owner}）")
                db["code_index"].pop(old_code, None)
                if new_code:
                    db["code_index"][new_code] = card_id

            changes = self._detect_changes(old_card, card, self._CARD_FIELDS)
            self._add_log(db, "update", "card", card_id,
                          card.get("task_code", ""), card.get("task_name", ""), changes)
            self._write(db)
            return self._norm(card, "card")

    def bulk_update(self, updates: dict) -> None:
        """批量更新工卡字段：单次读取 + 单次写入，消除逐卡 update 的 N+1 全文件 IO。

        updates: {card_id: {field: value, ...}}；支持 write_date/card_ok 等合法字段，
        自动维护工卡号索引与变更日志（与 update 行为一致）。
        """
        if not updates:
            return
        with self._lock:
            db = self._read()
            cards = db.get("cards", {})
            code_index = db.setdefault("code_index", {})
            for card_id, fields in updates.items():
                card = cards.get(str(card_id))
                if card is None:
                    continue
                old_card = dict(card)
                for key in ("task_code", "task_name", "category", "task_type", "remark",
                            "tools", "materials", "set_id", "tools_confirmed",
                            "materials_confirmed", "reminder_type", "card_ok",
                            "reminder_confirmed", "write_date"):
                    if key in fields:
                        card[key] = fields[key]
                card["log_time"] = _today_iso()
                old_code = old_card.get("task_code")
                new_code = card.get("task_code")
                if old_code and old_code != new_code:
                    owner = code_index.get(new_code)
                    if new_code and owner is not None and owner != card_id:
                        raise ValueError(f"工卡号 {new_code} 已存在（卡 {owner}）")
                    code_index.pop(old_code, None)
                    if new_code:
                        code_index[new_code] = card_id
                changes = self._detect_changes(old_card, card, self._CARD_FIELDS)
                self._add_log(db, "update", "card", card_id,
                              card.get("task_code", ""), card.get("task_name", ""), changes)
            self._write(db)

    def delete(self, card_id: int) -> bool:
        with self._lock:
            db = self._read()
            card = db.get("cards", {}).pop(str(card_id), None)
            if card is None:
                return False

            db["code_index"].pop(card.get("task_code"), None)
            self._add_log(db, "delete", "card", card_id,
                          card.get("task_code", ""), card.get("task_name", ""), [])
            self._write(db)
            return True

    # ---------- 工卡组 CRUD ----------

    def get_all_sets(self) -> list[dict]:
        db = self._read()
        sets = [self._norm(set, "set") for set in db.get("card_sets", {}).values()]
        sets.sort(key=lambda set: set.get("name", ""))
        return sets

    def get_set(self, set_id: int) -> dict | None:
        db = self._read()
        set = db.get("card_sets", {}).get(str(set_id))
        return self._norm(set, "set") if set else None

    def add_set(self, name: str, description: str = "",
                category: str = "机体", reminder_type: str = "",
                card_ok: bool = False, reminder_confirmed: bool = False) -> dict:
        with self._lock:
            db = self._read()
            set_id = self._next_id(db)
            set = {
                "id": set_id,
                "name": name,
                "description": description,
                "category": category,
                "tools": [],
                "materials": [],
                "tools_confirmed": False,
                "materials_confirmed": False,
                "reminder_type": reminder_type,
                "card_ok": card_ok,
                "reminder_confirmed": reminder_confirmed,
                "log_time": _today_iso(),
            }
            db.setdefault("card_sets", {})[str(set_id)] = set
            self._add_log(db, "add", "set", set_id, name, name, [])
            self._write(db)
            return dict(set)

    def update_set(self, set_id: int, **kwargs) -> dict | None:
        with self._lock:
            db = self._read()
            set = db.get("card_sets", {}).get(str(set_id))
            if set is None:
                return None

            old_set = dict(set)  # 变更前快照
            for key in ("name", "description", "category", "tools",
                         "materials", "tools_confirmed", "materials_confirmed",
                         "reminder_type", "card_ok", "reminder_confirmed"):
                if key in kwargs and kwargs[key] is not None:
                    set[key] = kwargs[key]

            # 数据库条目的新建/编辑日志时间：任何更新都刷新为当天
            set["log_time"] = _today_iso()

            changes = self._detect_changes(old_set, set, self._SET_FIELDS)
            self._add_log(db, "update", "set", set_id,
                          set.get("name", ""), set.get("name", ""), changes)
            self._write(db)
            return dict(set)

    def delete_set(self, set_id: int) -> bool:
        with self._lock:
            db = self._read()
            if str(set_id) not in db.get("card_sets", {}):
                return False

            # 解除关联工卡
            for card in db.get("cards", {}).values():
                if card.get("set_id") == set_id:
                    card["set_id"] = None

            set = db["card_sets"].pop(str(set_id))
            self._add_log(db, "delete", "set", set_id,
                          set.get("name", ""), set.get("name", ""), [])
            self._write(db)
            return True

    def get_cards_in_set(self, set_id: int) -> list[dict]:
        db = self._read()
        return [
            self._norm(card, "card") for card in db.get("cards", {}).values()
            if card.get("set_id") == set_id
        ]

    def get_card_sets_with_cards(self) -> list[dict]:
        """单次读取返回所有工卡组及其组内工卡（含 cards 字段）。

        替代按组逐次 get_cards_in_set 的 N+1 整库重读。
        """
        db = self._read()
        sets = [self._norm(s, "set") for s in db.get("card_sets", {}).values()]
        sets.sort(key=lambda s: s.get("name", ""))
        cards_by_set: dict[str, list] = {}
        for card in db.get("cards", {}).values():
            sid = card.get("set_id")
            if sid is None:
                continue
            cards_by_set.setdefault(str(sid), []).append(self._norm(card, "card"))
        result = []
        for s in sets:
            result.append({**s, "cards": cards_by_set.get(str(s.get("id")), [])})
        return result

    # ---------- 飞机信息 CRUD ----------

    def get_all_aircraft(self) -> list[dict]:
        db = self._read()
        ac_list = list(db.get("aircraft", {}).values())
        ac_list.sort(key=lambda ac: ac.get("reg", ""))
        return [self._norm(ac, "aircraft") for ac in ac_list]

    def get_aircraft(self, aircraft_id: int) -> dict | None:
        db = self._read()
        ac = db.get("aircraft", {}).get(str(aircraft_id))
        return self._norm(ac, "aircraft") if ac else None

    def find_aircraft_by_reg(self, reg: str):
        for ac in self._read().get("aircraft", {}).values():
            if ac.get("reg") == reg:
                return self._norm(ac, "aircraft")
        return None

    def add_aircraft(self, reg: str, model: str = "",
                     engine: str = "", fsn: str = "", msn: str = "", apu: str = "") -> dict:
        with self._lock:
            db = self._read()
            aircraft_id = self._next_id(db)
            ac = {
                "id": aircraft_id,
                "reg": reg,
                "model": model,
                "engine": engine,
                "fsn": fsn,
                "msn": msn,
                "apu": apu,
                "log_time": _today_iso(),
            }
            db.setdefault("aircraft", {})[str(aircraft_id)] = ac
            self._add_log(db, "add", "aircraft", aircraft_id, reg, model, [])
            self._write(db)
            return self._norm(ac, "aircraft")

    def update_aircraft(self, aircraft_id: int, **kwargs) -> dict | None:
        with self._lock:
            db = self._read()
            ac = db.get("aircraft", {}).get(str(aircraft_id))
            if ac is None:
                return None

            old_ac = dict(ac)  # 变更前快照
            for key in ("reg", "model", "engine", "fsn", "msn", "apu"):
                if key in kwargs:
                    ac[key] = kwargs[key]

            # 数据库条目的新建/编辑日志时间：任何更新都刷新为当天
            ac["log_time"] = _today_iso()

            changes = self._detect_changes(old_ac, ac, self._AIRCRAFT_FIELDS)
            self._add_log(db, "update", "aircraft", aircraft_id,
                          ac.get("reg", ""), ac.get("model", ""), changes)
            self._write(db)
            return self._norm(ac, "aircraft")

    def delete_aircraft(self, aircraft_id: int) -> bool:
        with self._lock:
            db = self._read()
            if str(aircraft_id) not in db.get("aircraft", {}):
                return False
            ac = db["aircraft"].pop(str(aircraft_id))
            self._add_log(db, "delete", "aircraft", aircraft_id,
                          ac.get("reg", ""), ac.get("model", ""), [])
            self._write(db)
            return True

    def bulk_aircraft_sync(self, updates: dict, deletes: list, adds: list) -> None:
        """飞机同步批量落盘：新增/更新/删除在单次读取 + 单次写入内完成，
        消除逐架 store 方法的全文件 IO（134 架场景从 ~15s 降至一次写盘）。

        updates: {aircraft_id: {field: value, ...}}
        deletes: [aircraft_id, ...]
        adds:    [{reg, model, engine, fsn, msn, apu}, ...]
        """
        with self._lock:
            db = self._read()
            acs = db.setdefault("aircraft", {})
            for aid, fields in updates.items():
                ac = acs.get(str(aid))
                if ac is None:
                    continue
                old = dict(ac)
                for key in ("reg", "model", "engine", "fsn", "msn", "apu"):
                    if key in fields:
                        ac[key] = fields[key]
                ac["log_time"] = _today_iso()
                changes = self._detect_changes(old, ac, self._AIRCRAFT_FIELDS)
                self._add_log(db, "update", "aircraft", aid,
                              ac.get("reg", ""), ac.get("model", ""), changes)
            for aid in deletes:
                ac = acs.pop(str(aid), None)
                if ac:
                    self._add_log(db, "delete", "aircraft", aid,
                                  ac.get("reg", ""), ac.get("model", ""), [])
            for a in adds:
                aid = self._next_id(db)
                ac = {
                    "id": aid,
                    "reg": a.get("reg", ""),
                    "model": a.get("model", ""),
                    "engine": a.get("engine", ""),
                    "fsn": a.get("fsn", ""),
                    "msn": a.get("msn", ""),
                    "apu": a.get("apu", ""),
                    "log_time": _today_iso(),
                }
                acs[str(aid)] = ac
                self._add_log(db, "add", "aircraft", aid,
                              ac.get("reg", ""), ac.get("model", ""), [])
            self._write(db)

    # ---------- 工卡组同步 ----------

    def sync_set_to_cards(self, set_id: int) -> None:
        """将工卡组的分类/工具/航材/提醒字段同步到组内所有卡"""
        with self._lock:
            db = self._read()
            set = db.get("card_sets", {}).get(str(set_id))
            if not set:
                return
            for field in ("category", "tools", "materials",
                          "tools_confirmed", "materials_confirmed",
                          "card_ok", "reminder_type", "reminder_confirmed"):
                if field not in set:
                    continue
                for card in db.get("cards", {}).values():
                    if card.get("set_id") == set_id:
                        card[field] = set[field]
            self._write(db)

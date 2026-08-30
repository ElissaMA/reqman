"""工卡业务逻辑层

职责：
- 校验输入
- 协调存储操作
- 工具/航材数据的解析与规范
- 工卡组的工具/航材传播
"""

from __future__ import annotations

import logging

from ..models.json_store import JsonStore
from ..utils.validators import clean_text, is_blank

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """业务层异常"""

    def __init__(self, message: str, field: str = ""):
        self.message = message
        self.field = field
        super().__init__(message)


class CardService:
    """工卡管理服务"""

    def __init__(self, store: JsonStore):
        self.store = store

    # ---------- 工具/航材解析 ----------

    @staticmethod
    def parse_tools_mats(form: dict) -> tuple[list[dict], list[dict]]:
        """从 Flask request.form 中提取工具和航材列表。

        处理两种数组格式：
        - tool_name[] / tool_pn[] / tool_qty[] / tool_remark[] / tool_type[]
        - mat_name[] / mat_pn[] / mat_qty[] / mat_remark[] / mat_type[]
        """
        tools, materials = [], []

        for prefix, name_key, fields in [
            ("tool", "device_name", ["tool_name[]", "tool_pn[]", "tool_qty[]", "tool_remark[]", "tool_type[]"]),
            ("mat", "material_name", ["mat_name[]", "mat_pn[]", "mat_qty[]", "mat_remark[]", "mat_type[]"]),
        ]:
            names = form.getlist(fields[0])

            if not names:
                continue

            pns = form.getlist(fields[1])
            qties = form.getlist(fields[2])
            rems = form.getlist(fields[3])
            types = form.getlist(fields[4])

            for i, name in enumerate(names):
                name = clean_text(name)
                if is_blank(name):
                    # 半空行严格校验：名称空但其他字段有值 → 抛错（静默跳过会丢失数据）
                    has_partial = False
                    for field_list in (pns, qties, rems, types):
                        if i < len(field_list) and not is_blank(field_list[i]):
                            has_partial = True
                            break
                    if has_partial:
                        label = "工具" if prefix == "tool" else "航材"
                        raise ServiceError(f"{label}第{i + 1}行缺少名称（件号/数量/备注等已有值），请补全名称或删除该行", f"{prefix}_name")
                    continue

                item = {
                    name_key: name,
                    "part_number": (pns[i].strip() if i < len(pns) else ""),
                    "quantity": (clean_text(qties[i]) if i < len(qties) else ""),
                    "remark": (rems[i].strip() if i < len(rems) else ""),
                    "usage_type": (clean_text(types[i]) if i < len(types) else "") or "必须使用",
                }

                (tools if prefix == "tool" else materials).append(item)

        return tools, materials

    # ---------- 工卡 ----------

    def add_card(self, task_code: str, task_name: str = "",
                 category: str = "机体", task_type: str = "",
                 remark: str = "",
                 tools: list[dict] | None = None,
                 materials: list[dict] | None = None,
                 tools_confirmed: bool = False,
                 materials_confirmed: bool = False,
                 reminder_type: str = "", reminder_confirmed: bool = False,
                 write_date: str = "", card_ok: bool = False) -> dict:
        """新增工卡。code 重复时抛出 ServiceError"""
        if is_blank(task_code):
            raise ServiceError("工卡号不能为空", "task_code")

        card = self.store.add(task_code.strip(), task_name.strip(),
                              category, task_type.strip(), remark.strip())
        if card is None:
            raise ServiceError(f"工卡号 {task_code} 已存在", "task_code")

        updates = {}
        if tools:
            updates["tools"] = tools
        if materials:
            updates["materials"] = materials
        updates["tools_confirmed"] = tools_confirmed
        updates["materials_confirmed"] = materials_confirmed
        updates["reminder_type"] = reminder_type
        updates["reminder_confirmed"] = reminder_confirmed
        updates["write_date"] = write_date
        updates["card_ok"] = card_ok
        self.store.update(card["id"], **updates)

        card = self.store.get(card["id"])
        return card

    def update_card(self, card_id: int, **kwargs) -> dict:
        """更新工卡。不存在或工卡号撞其他卡时抛出 ServiceError"""
        try:
            card = self.store.update(card_id, **kwargs)
        except ValueError as e:
            raise ServiceError(str(e), "task_code") from e
        if card is None:
            raise ServiceError("工卡不存在", "card_id")
        return card

    def delete_card(self, card_id: int) -> None:
        if not self.store.delete(card_id):
            raise ServiceError("工卡不存在", "card_id")

    def get_card(self, card_id: int) -> dict | None:
        return self.store.get(card_id)

    def list_cards(self, search: str = "", category: str = "",
                   reminder_type: str = "") -> list[dict]:
        return self.store.get_all(search=search, category=category,
                                  reminder_type=reminder_type)

    # ---------- 工卡组 ----------

    def add_card_set(self, name: str, description: str = "",
                     category: str = "机体",
                     card_codes: list[str] | None = None,
                     tools: list[dict] | None = None,
                     materials: list[dict] | None = None,
                     tools_confirmed: bool = False,
                     materials_confirmed: bool = False,
                     reminder_type: str = "", reminder_confirmed: bool = False,
                     card_ok: bool = False) -> dict:
        """新增工卡组。所有组内工卡地位平等，共享工具/航材需求"""
        if is_blank(name):
            raise ServiceError("工卡组名称不能为空", "name")

        set = self.store.add_set(name.strip(), description.strip(),
                                 category)

        updates = {}
        if tools:
            updates["tools"] = tools
        if materials:
            updates["materials"] = materials
        updates["tools_confirmed"] = tools_confirmed
        updates["materials_confirmed"] = materials_confirmed
        updates["reminder_type"] = reminder_type
        updates["reminder_confirmed"] = reminder_confirmed
        updates["card_ok"] = card_ok
        if updates:
            self.store.update_set(set["id"], **updates)

        if card_codes:
            self._assign_cards_to_set(set["id"], card_codes)
        self.store.sync_set_to_cards(set["id"])

        return self.store.get_set(set["id"])

    def update_card_set(self, set_id: int, name: str = "",
                         description: str = "",
                         category: str = "",
                         card_codes: list[str] | None = None,
                         tools: list[dict] | None = None,
                         materials: list[dict] | None = None,
                         tools_confirmed: bool | None = None,
                         materials_confirmed: bool | None = None,
                         reminder_type: str | None = None,
                         reminder_confirmed: bool | None = None,
                         card_ok: bool | None = None) -> dict:
        """更新工卡组，保存后自动同步工具/航材"""
        set = self.store.get_set(set_id)
        if set is None:
            raise ServiceError("工卡组不存在", "set_id")

        updates = {}
        if name:
            updates["name"] = name.strip()
        if description:
            updates["description"] = description.strip()
        if category:
            updates["category"] = category
        if tools is not None:
            updates["tools"] = tools
        if materials is not None:
            updates["materials"] = materials
        if tools_confirmed is not None:
            updates["tools_confirmed"] = tools_confirmed
        if materials_confirmed is not None:
            updates["materials_confirmed"] = materials_confirmed
        if reminder_type is not None:
            updates["reminder_type"] = reminder_type
        if reminder_confirmed is not None:
            updates["reminder_confirmed"] = reminder_confirmed
        if card_ok is not None:
            updates["card_ok"] = card_ok

        if updates:
            self.store.update_set(set_id, **updates)

        if card_codes is not None:
            self._assign_cards_to_set(set_id, card_codes)

        self.store.sync_set_to_cards(set_id)
        return self.store.get_set(set_id)

    def _assign_cards_to_set(self, set_id: int, card_codes: list[str]):
        """将指定工卡关联到工卡组，同时解除不再属于此组的工卡"""
        all_cards = self.store.get_all()
        codes = set(card_codes)

        for card in all_cards:
            code = card["task_code"]
            if code in codes:
                if card.get("set_id") != set_id:
                    self.store.update(card["id"], set_id=set_id)
            elif card.get("set_id") == set_id:
                self.store.update(card["id"], set_id=None)

    def delete_card_set(self, set_id: int) -> None:
        if not self.store.delete_set(set_id):
            raise ServiceError("工卡组不存在", "set_id")

    def list_card_sets(self) -> list[dict]:
        return self.store.get_all_sets()

    def get_card_set(self, set_id: int) -> dict | None:
        return self.store.get_set(set_id)

    def get_cards_in_set(self, set_id: int) -> list[dict]:
        return self.store.get_cards_in_set(set_id)

    # ---------- 飞机信息 ----------

    def list_aircraft(self) -> list[dict]:
        return self.store.get_all_aircraft()

    def get_aircraft(self, aircraft_id: int) -> dict | None:
        return self.store.get_aircraft(aircraft_id)

    def add_aircraft(self, reg: str, model: str = "",
                     engine: str = "", fsn: str = "", msn: str = "", apu: str = "") -> dict:
        """新增飞机。机号必填且不得重复（find_aircraft_by_reg 依赖唯一性）"""
        if is_blank(reg):
            raise ServiceError("机号不能为空", "reg")
        reg = reg.strip()
        if self.store.find_aircraft_by_reg(reg):
            raise ServiceError(f"机号 {reg} 已存在", "reg")
        return self.store.add_aircraft(
            reg, model.strip(), engine.strip(),
            fsn.strip(), msn.strip(), apu.strip()
        )

    def update_aircraft(self, aircraft_id: int, **kwargs) -> dict:
        """更新飞机信息。机号清空或撞已有机号时抛出 ServiceError"""
        reg = kwargs.get("reg")
        if reg is not None:
            if is_blank(reg):
                raise ServiceError("机号不能为空", "reg")
            existing = self.store.find_aircraft_by_reg(reg.strip())
            if existing and existing["id"] != aircraft_id:
                raise ServiceError(f"机号 {reg.strip()} 已存在", "reg")
        ac = self.store.update_aircraft(aircraft_id, **kwargs)
        if ac is None:
            raise ServiceError("飞机信息不存在", "aircraft_id")
        return ac

    def delete_aircraft(self, aircraft_id: int) -> None:
        if not self.store.delete_aircraft(aircraft_id):
            raise ServiceError("飞机信息不存在", "aircraft_id")
    # ---------- 工卡组传播与去重 ----------

    def propagate_set_data(self, matched: list, all_items: list, new_cards: list) -> None:
        """将工卡组的共用工具/航材传播给组内所有工卡"""
        for item in matched[:]:
            set_id = item.get("set_id")
            if not set_id:
                card = self.store.find_by_code(item["task_code"])
                if card and card.get("set_id"):
                    set_id = card["set_id"]
            if not set_id:
                continue
            item["set_id"] = set_id
            set = self.store.get_set(set_id)
            if not set:
                continue
            shared_tools = set.get("tools", [])
            shared_materials = set.get("materials", [])
            set_name = set.get("name", "")
            self._merge_item_resources(item, shared_tools, shared_materials)
            item["set_name"] = set_name
            for other in all_items:
                if other.get("set_id") == set_id and other is not item:
                    # 检查工卡本身的确认状态，未确认的不移入 matched
                    other_card = self.store.find_by_code(other.get("task_code", ""))
                    if other_card:
                        tools_ok = other_card.get("tools_confirmed", False)
                        materials_ok = other_card.get("materials_confirmed", False)
                        reminder_ok = other_card.get("reminder_confirmed", False)
                        if not (tools_ok and materials_ok and reminder_ok):
                            continue  # 未确认，跳过，保留在 new_cards
                    if other.get("status") != "matched":
                        other["status"] = "matched"
                        other["db_id"] = item.get("db_id")
                    self._merge_item_resources(other, shared_tools, shared_materials)
                    other["set_name"] = set_name
                    if other in new_cards:
                        new_cards.remove(other)
                        matched.append(other)

    @staticmethod
    def _merge_item_resources(item: dict, shared_tools: list, shared_materials: list) -> None:
        """合并工卡自身工具/航材与工卡组共用工具/航材，组共用部分在前"""
        existing_tools = item.get("tools", [])
        merged_tools = list(shared_tools)
        existing_names = {t.get("device_name", "") for t in merged_tools}
        for t in existing_tools:
            if t.get("device_name", "") and t["device_name"] not in existing_names:
                merged_tools.append(t)
                existing_names.add(t["device_name"])
        item["tools"] = merged_tools

        existing_mats = item.get("materials", [])
        merged_mats = list(shared_materials)
        existing_mat_names = {m.get("material_name", "") for m in merged_mats}
        for m in existing_mats:
            if m.get("material_name", "") and m["material_name"] not in existing_mat_names:
                merged_mats.append(m)
                existing_mat_names.add(m["material_name"])
        item["materials"] = merged_mats

    def dedup_by_set(self, matched: list, new_cards: list) -> None:
        """识别新工卡中属于既有工卡组的项目，归入已匹配"""
        remove_idx = []
        for i, item in enumerate(new_cards):
            card = self.store.find_by_code(item.get("task_code", ""))
            if card and card.get("set_id"):
                # 检查工卡本身的确认状态，未确认的不移入 matched
                tools_ok = card.get("tools_confirmed", False)
                materials_ok = card.get("materials_confirmed", False)
                reminder_ok = card.get("reminder_confirmed", False)
                if not (tools_ok and materials_ok and reminder_ok):
                    continue  # 未确认，跳过，保留在 new_cards
                item["status"] = "matched"
                item["db_id"] = card["id"]
                item["set_id"] = card["set_id"]
                item["set_duplicate"] = True
                item["category"] = card.get("category", item.get("category"))
                item["task_type"] = card.get("task_type", item.get("task_type"))
                matched.append(item)
                remove_idx.append(i)
        for idx in reversed(remove_idx):
            new_cards.pop(idx)

    # ---------- 日志 ----------

    def get_logs(self, operation: str = "", target_type: str = "",
                 start_date: str = "", end_date: str = "") -> list[dict]:
        """查询日志"""
        return self.store.get_logs(
            operation=operation or None,
            target_type=target_type or None,
            start_date=start_date or None,
            end_date=end_date or None,
        )

    def delete_logs(self, log_ids: list[int]) -> int:
        """删除指定 ID 的日志，返回删除数量"""
        return self.store.delete_logs(log_ids)

    def get_logs_by_ids(self, log_ids: list[int]) -> list[dict]:
        """根据 ID 列表查询日志"""
        all_logs = self.store.get_logs()
        log_ids_set = set(log_ids)
        return [log for log in all_logs if log.get("id") in log_ids_set]

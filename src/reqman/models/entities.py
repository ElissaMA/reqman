"""领域实体 — 纯数据结构，不依赖任何存储实现"""

from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------- 工具/航材条目 ----------

@dataclass
class ToolItem:
    device_name: str = ""
    part_number: str = ""
    quantity: str = "1"
    remark: str = ""
    usage_type: str = "必须使用"

    @classmethod
    def from_dict(cls, d: dict) -> "ToolItem":
        return cls(
            device_name=d.get("device_name", ""),
            part_number=d.get("part_number", ""),
            quantity=str(d.get("quantity", "1")),
            remark=d.get("remark", ""),
            usage_type=d.get("usage_type", "必须使用"),
        )


@dataclass
class MaterialItem:
    material_name: str = ""
    part_number: str = ""
    quantity: str = "1"
    remark: str = ""
    usage_type: str = "必须使用"

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialItem":
        return cls(
            material_name=d.get("material_name", ""),
            part_number=d.get("part_number", ""),
            quantity=str(d.get("quantity", "1")),
            remark=d.get("remark", ""),
            usage_type=d.get("usage_type", "必须使用"),
        )


# ---------- 工卡 ----------

@dataclass
class Card:
    id: int
    task_code: str
    task_name: str = ""
    tools_confirmed: bool = False
    materials_confirmed: bool = False
    category: str = "机体"
    task_type: str = ""
    remark: str = ""
    tools: list[dict] = field(default_factory=list)
    materials: list[dict] = field(default_factory=list)
    set_id: Optional[int] = None
    reminder_type: str = "一般提醒"

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        return cls(
            id=d["id"],
            task_code=d.get("task_code", ""),
            task_name=d.get("task_name", ""),
            tools_confirmed=d.get("tools_confirmed", False),
            materials_confirmed=d.get("materials_confirmed", False),
            category=d.get("category", "机体"),
            task_type=d.get("task_type", ""),
            remark=d.get("remark", ""),
            tools=d.get("tools", []),
            materials=d.get("materials", []),
            set_id=d.get("set_id"),
            reminder_type=d.get("reminder_type", "一般提醒"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- 工卡组 ----------

@dataclass
class CardSet:
    id: int
    name: str
    description: str = ""
    tools_confirmed: bool = False
    materials_confirmed: bool = False
    category: str = "机体"
    tools: list[dict] = field(default_factory=list)
    materials: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "CardSet":
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            description=d.get("description", ""),
            tools_confirmed=d.get("tools_confirmed", False),
            materials_confirmed=d.get("materials_confirmed", False),
            category=d.get("category", "机体"),
            tools=d.get("tools", []),
            materials=d.get("materials", []),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- 飞机信息 ----------

@dataclass
class Aircraft:
    id: int
    reg: str = ""              # 机号，如 B-6321
    model: str = ""            # 机型，如 A320-232
    engine: str = ""           # 发动机型号，如 V2500-A5 / CFM56-5B / PW1100
    fsn: str = ""              # 机队序列号（Fleet Serial Number）
    msn: str = ""              # 制造商序列号（Manufacturer Serial Number）
    apu: str = ""              # APU 型号，如 131-9(A)

    @classmethod
    def from_dict(cls, d: dict) -> "Aircraft":
        return cls(
            id=d["id"],
            reg=d.get("reg", ""),
            model=d.get("model", ""),
            engine=d.get("engine", ""),
            fsn=d.get("fsn", ""),
            msn=d.get("msn", ""),
            apu=d.get("apu", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)

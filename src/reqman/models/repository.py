"""数据持久化抽象接口"""

from abc import ABC, abstractmethod
from typing import Optional


class CardRepository(ABC):
    """工卡存储接口 — 方便未来切换 JSON/SQLite/MySQL"""

    @abstractmethod
    def get_all(self, search: str = "", category: str = "") -> list[dict]:
        """列出所有工卡，支持搜索和分类过滤"""
        ...

    @abstractmethod
    def get(self, card_id: int) -> Optional[dict]:
        """按 ID 获取工卡"""
        ...

    @abstractmethod
    def find_by_code(self, code: str) -> Optional[dict]:
        """按工卡号查找"""
        ...

    @abstractmethod
    def add(self, task_code: str, task_name: str = "",
            category: str = "机体", task_type: str = "",
            remark: str = "") -> dict:
        """新增工卡，返回创建后的 dict。工卡号重复返回 None"""
        ...

    @abstractmethod
    def update(self, card_id: int, **kwargs) -> Optional[dict]:
        """更新工卡字段"""
        ...

    @abstractmethod
    def delete(self, card_id: int) -> bool:
        """删除工卡"""
        ...

    # ---------- 工卡组 ----------

    @abstractmethod
    def get_all_sets(self) -> list[dict]:
        ...

    @abstractmethod
    def get_set(self, set_id: int) -> Optional[dict]:
        ...

    @abstractmethod
    def add_set(self, name: str, description: str = "",
                category: str = "机体") -> dict:
        ...

    @abstractmethod
    def update_set(self, set_id: int, **kwargs) -> Optional[dict]:
        ...

    @abstractmethod
    def delete_set(self, set_id: int) -> bool:
        ...

    @abstractmethod
    def get_cards_in_set(self, set_id: int) -> list[dict]:
        ...

    # ---------- 飞机信息 ----------

    @abstractmethod
    def get_all_aircraft(self) -> list[dict]:
        """列出所有飞机"""
        ...

    @abstractmethod
    def get_aircraft(self, aircraft_id: int) -> Optional[dict]:
        """按 ID 获取飞机"""
        ...

    @abstractmethod
    def add_aircraft(self, reg: str, model: str = "",
                     engine: str = "", fsn: str = "", msn: str = "", apu: str = "") -> dict:
        """新增飞机，返回创建后的 dict"""
        ...

    @abstractmethod
    def update_aircraft(self, aircraft_id: int, **kwargs) -> Optional[dict]:
        """更新飞机字段"""
        ...

    @abstractmethod
    def delete_aircraft(self, aircraft_id: int) -> bool:
        """删除飞机"""
        ...

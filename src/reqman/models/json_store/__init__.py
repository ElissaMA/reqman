"""JSON 文件持久化实现（包）

拆分说明：core 提供持久化机制与共享常量；card_store / work_package_store /
log_store 按业务域承载 JsonStore 的方法，统一经 JsonStoreCore 继承链组合。
对外仍只暴露 JsonStore（= 继承链末端 LogStore），保持历史 import 路径不变。
"""

import os

from .core import _RUNTIME_KEYS, JsonStoreCorruptionError, _atomic_write
from .log_store import LogStore as JsonStore

__all__ = ["_RUNTIME_KEYS", "JsonStore", "JsonStoreCorruptionError", "_atomic_write", "os"]

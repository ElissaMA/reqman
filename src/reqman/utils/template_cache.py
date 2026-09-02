"""静态模板字节缓存（性能）

仅用于 assets/ 下的静态资源模板（需求单/提醒单/改版清单）。按 (绝对路径, mtime)
缓存已读取的模板字节，避免每次生成报告都重新读盘——Windows 上杀软可能逐次扫描
xlsx，重复读盘开销明显。

安全约束：缓存的是「字节」，每次调用仍用 BytesIO 重新 load_workbook，保证每个调用
拿到独立的 Workbook 对象，互不串改（openpyxl Workbook 不可跨调用复用写入）。
模板文件被编辑（mtime 变化）后自动失效重载。
"""
from __future__ import annotations

import io
import threading
from pathlib import Path

import openpyxl

_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()


def load_template(path: str | Path) -> openpyxl.Workbook:
    """读取静态模板为独立 Workbook（带 mtime 字节缓存，避免重复读盘）。"""
    p = Path(path)
    mtime = p.stat().st_mtime
    key = str(p.resolve())
    with _lock:
        entry = _cache.get(key)
        if entry is not None and entry[0] == mtime:
            data = entry[1]
        else:
            data = p.read_bytes()
            _cache[key] = (mtime, data)
    return openpyxl.load_workbook(io.BytesIO(data))

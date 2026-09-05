"""日期工具：统一日期显示格式为 YYYY-MM-DD。"""

from __future__ import annotations

__all__ = ["fmt_date10"]


def fmt_date10(value) -> str:
    """将 AMRO/库存日期值规范为 YYYY-MM-DD（取前 10 位）。

    AMRO 原始 write_date 形如 '2026-08-01 09:00:00' 或 '2026-08-01'，
    统一截取前 10 位得到纯日期；空值/非字符串原样返回空串。
    """
    if not isinstance(value, str):
        return "" if value is None else str(value)
    value = value.strip()
    if len(value) >= 10:
        return value[:10]
    return value

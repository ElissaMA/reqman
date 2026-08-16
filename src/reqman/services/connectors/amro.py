"""AMRO 库存查询连接器 — 唯一接触川航 AMRO API 的模块

从上级目录库存查询工具（scal）迁移，TLS 改为标准证书校验（verify=True）。
"""
from __future__ import annotations

import logging
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://me.sichuanair.com/api/v1/plugins/MM_PARTNUMBERCHAXUN_LIST"

# 库存类型 — 开封航化代码待内网验证后启用
INVENTORY_TYPES: dict[str, str] = {"available": "01"}

# SWERK 前 2 位 → 基地中文名
amro_base_map: dict[str, str] = {
    "KM": "昆明", "CD": "成都双流", "CQ": "重庆", "HB": "哈尔滨",
    "TF": "成都天府", "BJ": "北京", "HZ": "杭州",
    "NN": "南宁", "SY": "三亚", "TJ": "天津",
    "WQ": "乌鲁木齐", "XA": "西安",
}

KUNMING_PREFIXES = ("KM",)


def is_kunming(swerk: str) -> bool:
    return swerk.startswith(KUNMING_PREFIXES) if swerk else False


class KunmingStock(NamedTuple):
    total_qty: float
    unit: str
    pn_desc: str


async def query_single_pn(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    pn: str,
    inv_type: str,
) -> list[dict]:
    resp = await client.post(
        API_URL,
        data={
            "I_HHJ": "",
            "I_ZLGO_TYP": inv_type,
            "I_MFRPN": pn,
            "I_MATER_NO_FLEET": "",
        },
        cookies=cookies,
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    code = body.get("code")
    if code != 200:
        msg = body.get("msg", "unknown")
        if code == 100:
            raise RuntimeError("登录已失效，请重新运行登录脚本")
        raise RuntimeError(f"API 返回 code={code}, msg={msg}")
    return body.get("data", [])


async def query_kunming_stock(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    pn: str,
) -> KunmingStock | None:
    total = 0.0
    unit = ""
    desc = ""
    any_success = False

    for inv_type in INVENTORY_TYPES.values():
        try:
            rows = await query_single_pn(client, cookies, pn, inv_type)
            any_success = True
        except RuntimeError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("库存类型 %s 查询失败: %s", inv_type, exc)
            continue
        for row in rows:
            if is_kunming(row.get("swerk", "")):
                total += float(row.get("clabs", 0) or 0)
                if not unit and row.get("meins"):
                    unit = row["meins"]
                if not desc and row.get("maktx"):
                    desc = row["maktx"]

    if not any_success:
        return None
    return KunmingStock(total, unit, desc)


async def check_session(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    pn: str,
) -> bool:
    """会话探活：调用一次 API，code=100 视为登录失效返回 False。"""
    try:
        await query_single_pn(client, cookies, pn, "01")
        return True
    except RuntimeError as e:
        return not ("登录已失效" in str(e) or "会话过期" in str(e))
    except (httpx.HTTPError, ValueError):
        return True

"""AMRO 库存查询连接器 — 唯一接触川航 AMRO API 的模块

从上级目录库存查询工具（scal）迁移，TLS 改为标准证书校验（verify=True）。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import httpx

from ...config import AMRO_AUDIT_FILE, AMRO_RATE_SECONDS

logger = logging.getLogger(__name__)

API_URL = "https://me.sichuanair.com/api/v1/plugins/MM_PARTNUMBERCHAXUN_LIST"

AMRO_API_BASE = "https://me.sichuanair.com/api/v1/plugins"

# 只读白名单：仅允许调用以下 8 个已实测验证的查询端点（写/导出/生成类端点一律拒绝）
READONLY_PLUGINS: frozenset[str] = frozenset({
    "DA_ACREG_LIST", "DA_MPACTYPE_HELP",
    "TD_JC_SMJC_LIST", "TD_JC_ALL_EOJC_LIST", "TD_JC_ALL_GET_ENTITY_BY_JCNO",
    "BM_TSK_LIST", "BM_TSK_002_LIST", "BM_TSK_002_LIST_QT",
})


class AmroSessionExpired(RuntimeError):
    """AMRO 会话失效（业务 code=100）。"""

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


# ---------- 通用只读调用器（v3.5.0 三域同步基座） ----------

_last_request_ts = 0.0  # 模块级节流戳


def _throttle() -> None:
    """全局限速：两次 AMRO 请求间隔 ≥ AMRO_RATE_SECONDS。"""
    global _last_request_ts
    now = time.monotonic()
    wait = _last_request_ts + AMRO_RATE_SECONDS - now
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = now


def _audit_path() -> Path:
    return Path(AMRO_AUDIT_FILE)


def _audit(plugin: str, url: str, form: dict, code, seconds: float) -> None:
    """每次调用追加 JSONL 审计留痕（可自证只查未改）。"""
    entry = {
        "ts": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "plugin": plugin,
        "url": url,
        "form": {k: str(v)[:60] for k, v in form.items()},
        "code": code,
        "seconds": round(seconds, 2),
    }
    path = _audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("AMRO 审计写入失败: %s", path)


async def query_plugin(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    plugin: str,
    form: dict,
    *,
    timeout: int = 30,
) -> dict:
    """通用只读查询：白名单校验 → 限速 → POST → 审计 → 业务码校验。

    code==200 返回完整 body；code==100 抛 AmroSessionExpired；其余业务码抛 RuntimeError。
    """
    if plugin not in READONLY_PLUGINS:
        raise ValueError(f"端点 {plugin} 不在只读白名单，禁止调用")
    url = f"{AMRO_API_BASE}/{plugin}"
    _throttle()
    start = time.monotonic()
    resp = await client.post(url, data=form, cookies=cookies, timeout=timeout)
    seconds = time.monotonic() - start
    resp.raise_for_status()
    body = resp.json()
    code = body.get("code") if isinstance(body, dict) else None
    _audit(plugin, url, form, code, seconds)
    if code == 200:
        return body
    if code == 100:
        raise AmroSessionExpired("登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试")
    msg = body.get("msg", "unknown") if isinstance(body, dict) else "unknown"
    raise RuntimeError(f"AMRO 接口 code={code}, msg={msg}")


async def fetch_all_pages(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    plugin: str,
    base_form: dict,
    *,
    timeout: int = 30,
    max_pages: int = 30,
) -> list[dict]:
    """分页拉全量：page 自增，rows 默认 500（base_form 可覆盖）。

    终止条件：空页，或 len(rows) >= total（total>0 时）。
    BM_TSK_LIST 语义 total 恒 0 → 依赖空页终止。
    """
    rows: list[dict] = []
    page = 1
    while page <= max_pages:
        form = dict(base_form)
        form["page"] = page
        form.setdefault("rows", 500)
        body = await query_plugin(client, cookies, plugin, form, timeout=timeout)
        data = body.get("data") or []
        if not data:
            break
        rows.extend(data)
        total = body.get("total") or 0
        if total and len(rows) >= int(total):
            break
        page += 1
    return rows

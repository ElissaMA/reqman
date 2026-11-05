"""AMRO 库存查询连接器 — 唯一接触川航 AMRO API 的模块

从上级目录库存查询工具（scal）迁移，TLS 改为标准证书校验（verify=True）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import httpx

from ...config import AMRO_AUDIT_FILE, AMRO_RATE_SECONDS

logger = logging.getLogger(__name__)

AMRO_API_BASE = "https://me.sichuanair.com/api/v1/plugins"

# AMRO 网关按 User-Agent 拦截非浏览器指纹（httpx 默认 python-httpx/x 与 requests 均被 403）；
# 所有 AMRO 调用必须经 amro_client() 携带此标识，勿在调用点各自建 AsyncClient。
AMRO_USER_AGENT = "ReqMan/3.7.1 (AMRO read-only)"

# 只读白名单：仅允许调用以下已实测验证的查询端点（写/导出/生成类端点一律拒绝）
READONLY_PLUGINS: frozenset[str] = frozenset({
    "DA_ACREG_LIST", "DA_MPACTYPE_HELP",
    "TD_JC_SMJC_LIST", "TD_JC_NRCJC_LIST", "TD_JC_ALL_EOJC_LIST", "TD_JC_ALL_QECJC_LIST", "TD_JC_ALL_GET_ENTITY_BY_JCNO",
    "BM_TSK_LIST", "BM_TSK_002_LIST", "BM_TSK_002_LIST_QT",
    "MM_PARTNUMBERCHAXUN_LIST",
})


class AmroSessionExpired(RuntimeError):
    """AMRO 会话失效（业务 code=100）。"""


class AmroBlocked(RuntimeError):
    """AMRO 网关拦截（HTTP 403）：网络不可达或被防火墙判定为威胁。"""


def amro_client(**kwargs) -> httpx.AsyncClient:
    """创建统一 AMRO 客户端：固定 UA + 校验证书 + 忽略系统代理环境变量。"""
    headers = dict(kwargs.pop("headers", None) or {})
    headers.setdefault("User-Agent", AMRO_USER_AGENT)
    return httpx.AsyncClient(verify=True, trust_env=False, headers=headers, **kwargs)

# 库存类型 — 开封航化代码待内网验证后启用
INVENTORY_TYPES: dict[str, str] = {"available": "01"}

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
    *,
    timeout: int = 30,
) -> list[dict]:
    """单件号库存查询 — 经通用只读调用器，自动获得白名单校验/限速/审计。

    探活调用方可传更短 timeout（库存查询编排用默认 30s）。
    """
    body = await query_plugin(
        client,
        cookies,
        "MM_PARTNUMBERCHAXUN_LIST",
        {
            "I_HHJ": "",
            "I_ZLGO_TYP": inv_type,
            "I_MFRPN": pn,
            "I_MATER_NO_FLEET": "",
        },
        timeout=timeout,
    )
    # AMRO 可能返回 "data": null（键存在值为 null）——直接迭代会抛 TypeError，
    # 而 TypeError 不在库存查询的 except 范围内，会让整批查询失败而非单件号失败。
    rows = body.get("data") or []
    return [row for row in rows if isinstance(row, dict)]


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


# ---------- 通用只读调用器（v3.5.0 三域同步基座） ----------

_last_request_ts = 0.0  # 模块级节流戳（跨事件循环/线程共享，仅用于计时）
_ts_guard = threading.Lock()  # 仅保护戳的读写，绝不持锁 await，故不阻塞事件循环


async def _throttle() -> None:
    """全局限速：两次 AMRO 请求间隔 ≥ AMRO_RATE_SECONDS（不阻塞事件循环）。

    节流戳用 threading.Lock 短时保护（仅做算术，不 await），真正的等待在锁外
    以 asyncio.sleep 完成。这样在「单 loop 内多协程」「多 asyncio.run 各建新
    loop」「多守护线程」三种场景都正确：既不会被 asyncio.Lock 跨 loop 绑定报错，
    也不会因持锁 await 而死锁事件循环。
    """
    global _last_request_ts
    with _ts_guard:
        now = time.monotonic()
        wait = _last_request_ts + AMRO_RATE_SECONDS - now
        if wait > 0:
            _last_request_ts = now + wait  # 先占位，避免并发重叠
        else:
            _last_request_ts = now
    if wait > 0:
        await asyncio.sleep(wait)


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


_RETRY_ATTEMPTS = 2  # 瞬态失败（超时/传输错误/5xx）总尝试次数（含首次，2026-09-03 起）


def _retryable(exc: Exception) -> bool:
    """瞬态失败判定：超时/传输错误/5xx 可重试；403/4xx 与业务码错误不重试。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


async def query_plugin(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    plugin: str,
    form: dict,
    *,
    timeout: int = 30,
) -> dict:
    """通用只读查询：白名单校验 → 限速 → POST（瞬态失败重试，每次尝试均限速）→ 审计 → 业务码校验。

    code==200 返回完整 body；code==100 抛 AmroSessionExpired；HTTP 403 抛 AmroBlocked；其余业务码抛 RuntimeError。
    超时/传输错误/5xx 按 _RETRY_ATTEMPTS 总次数重试（限速对每次尝试生效，红线不绕过）；
    最终失败写审计留痕（code=-1，403 记 403），避免静默无痕（2026-09-03 全量版本查询超时排查教训）。
    """
    if plugin not in READONLY_PLUGINS:
        raise ValueError(f"端点 {plugin} 不在只读白名单，禁止调用")
    url = f"{AMRO_API_BASE}/{plugin}"
    last_exc: Exception | None = None
    seconds = 0.0
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        await _throttle()
        start = time.monotonic()
        try:
            resp = await client.post(url, data=form, cookies=cookies, timeout=timeout)
            seconds = time.monotonic() - start
            if resp.status_code == 403:
                _audit(plugin, url, form, 403, seconds)
                raise AmroBlocked(
                    "AMRO 网关拦截 HTTP 403：请确认可访问 AMRO（公司网络/VPN）后重试"
                )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            seconds = time.monotonic() - start
            last_exc = exc
            if not _retryable(exc) or attempt >= _RETRY_ATTEMPTS:
                break
            logger.warning("AMRO %s 第 %d 次尝试瞬态失败（%s），限速后重试",
                           plugin, attempt, exc.__class__.__name__)
            continue
        code = body.get("code") if isinstance(body, dict) else None
        _audit(plugin, url, form, code, seconds)
        if code == 200:
            return body
        if code == 100:
            raise AmroSessionExpired("登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试")
        msg = body.get("msg", "unknown") if isinstance(body, dict) else "unknown"
        raise RuntimeError(f"AMRO 接口 code={code}, msg={msg}")
    _audit(plugin, url, form, -1, seconds)
    raise last_exc


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

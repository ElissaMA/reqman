"""库存查询业务编排 — 读Excel → 去重 → 并发查询 → 副本暂存"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import httpx

from ..config import OUTPUT_DIR
from .connectors import amro
from .connectors.session import LoginSessionStore
from .xlsx_workbook import read_demand, write_inventory_copy

logger = logging.getLogger(__name__)


class QueryResult(NamedTuple):
    filename: str
    total: int
    success: int
    fail: int
    shortage: int
    warning: int


def _deduplicate_pns(rows):
    seen: dict[str, list[str]] = {}
    qty_map: dict[str, list[float]] = {}
    for r in rows:
        if r.part_number not in seen:
            seen[r.part_number] = []
            qty_map[r.part_number] = []
        seen[r.part_number].append(r.stock_cell)
        qty_map[r.part_number].append(r.qty)
    return list(seen.keys()), seen, qty_map


def _is_warning(pn: str, qty: float, stock: float, thresholds: dict | None) -> bool:
    """警戒（标黄）判定：库内件号用设定警戒线；库外回退原 库存<使用量+2。"""
    thr = thresholds.get(pn) if thresholds else None
    if thr is not None:
        return stock < thr
    return qty <= stock < qty + 2


class InventoryService:
    def __init__(self, session_store: LoginSessionStore, max_concurrent: int = 10):
        self.session_store = session_store
        self.max_concurrent = max_concurrent
        self._last_probe_state = "none"

    @staticmethod
    def _duration_seconds(login_at: str | None) -> int:
        if not login_at:
            return 0
        try:
            started = datetime.fromisoformat(login_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return max(int((now - started.astimezone(timezone.utc)).total_seconds()), 0)
        except (TypeError, ValueError, OverflowError):
            return 0

    async def _probe_cached_session(self, data: dict) -> str:
        """严格探活：valid / expired / probe_error，不把网络异常当成有效。"""
        async with httpx.AsyncClient(verify=True, trust_env=False) as client:
            pn = data["cookies"].get("I_MFRPN") or "ST1946-107"
            try:
                await amro.query_single_pn(client, data["cookies"], pn, "01")
                return "valid"
            except amro.AmroSessionExpired:
                return "expired"
            except (httpx.HTTPError, OSError, ValueError, RuntimeError):
                return "probe_error"

    def check_login_state(self) -> str:
        data = self.session_store.load()
        if not data:
            self._last_probe_state = "none"
            return "none"
        try:
            state = asyncio.run(self._probe_cached_session(data))
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            state = "probe_error"
        self._last_probe_state = state
        if state == "expired":
            self.session_store.clear()
        elif state in {"valid", "probe_error"}:
            self.session_store.mark_probe(state)
        return state

    def get_login_status(self) -> dict:
        data = self.session_store.load()
        if not data:
            self._last_probe_state = "none"
            return {
                "ready": False,
                "state": "none",
                "account": None,
                "login_at": None,
                "last_checked_at": None,
                "login_duration_seconds": 0,
            }
        ready = self.check_login()
        state = "valid" if ready else self._last_probe_state
        if state not in {"valid", "expired", "probe_error"}:
            state = "valid" if ready else "expired"
        latest = self.session_store.load() or data
        return {
            "ready": ready,
            "state": state,
            "account": latest.get("account"),
            "login_at": latest.get("login_at"),
            "last_checked_at": latest.get("last_checked_at"),
            "login_duration_seconds": self._duration_seconds(latest.get("login_at")),
        }

    def check_login(self) -> bool:
        """探活：AMRO 明确失效才清缓存，网络异常返回不可用。"""
        return self.check_login_state() == "valid"

    def save_login(self, cookies: list[dict], account: str | None = None) -> None:
        self.session_store.save(cookies, account=account)

    def run_query(
        self,
        demand_path: str | Path,
        output_stem: str | None = None,
        warning_thresholds: dict | None = None,
        warning_pns: list | None = None,
        store=None,
    ) -> tuple[Path, str, QueryResult]:
        data = self.session_store.load()
        if not data:
            raise RuntimeError("登录已失效，请重新运行登录脚本")
        cookies = data["cookies"]

        rows = read_demand(demand_path)
        if not rows:
            raise ValueError("需求单中未找到航材件号")

        demand_pns, pn_cells, pn_qty = _deduplicate_pns(rows)
        # 预警库件号也查 AMRO 库存（去重保序，避免重复查询）
        query_pns = list(dict.fromkeys(demand_pns + (warning_pns or [])))

        async def _run():
            results: dict[str, float] = {}
            success = fail = 0
            sem = asyncio.Semaphore(self.max_concurrent)
            async with httpx.AsyncClient(verify=True, trust_env=False) as client:
                async def query_one(pn: str) -> None:
                    nonlocal success, fail
                    async with sem:
                        try:
                            stock = await amro.query_kunming_stock(client, cookies, pn)
                            if stock is not None:
                                results[pn] = stock.total_qty
                                success += 1
                            else:
                                results[pn] = 0.0
                                fail += 1
                        except (httpx.HTTPError, ValueError, RuntimeError) as e:
                            results[pn] = 0.0
                            fail += 1
                            logger.warning("查询失败 %s: %s", pn, e)
                await asyncio.gather(*[query_one(pn) for pn in query_pns])
            return results, success, fail

        results, success, fail = asyncio.run(_run())
        buf, filename = write_inventory_copy(
            demand_path, results, pn_qty, pn_cells, output_stem=output_stem,
            warning_thresholds=warning_thresholds,
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUTPUT_DIR / filename
        dest.write_bytes(buf.getvalue())

        shortage = sum(
            1 for pn in pn_cells for qty in pn_qty.get(pn, [0])
            if results.get(pn, 0) < qty
        )
        warning = sum(
            1 for pn in pn_cells for qty in pn_qty.get(pn, [0])
            if _is_warning(pn, qty, results.get(pn, 0), warning_thresholds)
        )

        # 回写预警库件号缓存库存（仅更新已存在条目，避免复活已删除项；失败不阻断主流程）
        if store is not None and warning_pns:
            for pn in warning_pns:
                try:
                    if store.get_inventory_warning(pn) is not None:
                        store.save_inventory_warning(
                            {"part_number": pn, "stock": results.get(pn, 0.0)}
                        )
                except (OSError, ValueError, RuntimeError):
                    logger.warning("预警库库存回写失败: %s", pn)

        return dest, filename, QueryResult(
            filename, len(demand_pns), success, fail, shortage, warning,
        )

"""库存查询业务编排 — 读Excel → 去重 → 并发查询 → 副本暂存"""
from __future__ import annotations

import asyncio
import logging
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


class InventoryService:
    def __init__(self, session_store: LoginSessionStore, max_concurrent: int = 10):
        self.session_store = session_store
        self.max_concurrent = max_concurrent

    def get_login_status(self) -> dict:
        data = self.session_store.load()
        if not data:
            return {"ready": False, "remaining_seconds": 0}
        return {"ready": self.check_login(), "remaining_seconds": self.session_store.remaining_seconds()}

    def check_login(self) -> bool:
        """探活：有缓存则真实调用一次 AMRO API。"""
        data = self.session_store.load()
        if not data:
            return False
        async def _probe():
            async with httpx.AsyncClient(verify=True) as client:
                pn = data["cookies"].get("I_MFRPN") or "ST1946-107"
                return await amro.check_session(client, data["cookies"], pn)
        try:
            return asyncio.run(_probe())
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            return False

    def save_login(self, cookies: list[dict]) -> None:
        self.session_store.save(cookies)

    def run_query(
        self,
        demand_path: str | Path,
        output_stem: str | None = None,
    ) -> tuple[Path, str, QueryResult]:
        data = self.session_store.load()
        if not data:
            raise RuntimeError("登录已失效，请重新运行登录脚本")
        cookies = data["cookies"]

        rows = read_demand(demand_path)
        if not rows:
            raise ValueError("需求单中未找到航材件号")

        all_pns, pn_cells, pn_qty = _deduplicate_pns(rows)

        async def _run():
            results: dict[str, float] = {}
            success = fail = 0
            sem = asyncio.Semaphore(self.max_concurrent)
            async with httpx.AsyncClient(verify=True) as client:
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
                await asyncio.gather(*[query_one(pn) for pn in all_pns])
            return results, success, fail

        results, success, fail = asyncio.run(_run())
        buf, filename = write_inventory_copy(
            demand_path, results, pn_qty, pn_cells, output_stem=output_stem,
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
            if qty <= results.get(pn, 0) < qty + 2
        )
        return dest, filename, QueryResult(filename, len(all_pns), success, fail, shortage, warning)

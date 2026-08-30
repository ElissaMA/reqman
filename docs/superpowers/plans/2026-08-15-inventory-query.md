# 库存查询功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在需求单系统（reqman）中新增独立库存查询页，用户上传需求单 Excel，系统批量查询川航 AMRO 昆明库存并回填副本 G 列（标红/标黄），登录通过自举登录脚本获取临时凭证。

**Architecture:** 遵循现有"工厂+蓝图+服务层"架构。新增 `connectors/`（AMRO 适配器 + 临时登录缓存）、`inventory_service.py`（业务编排）、`xlsx_workbook.py`（迁移自 scal）、`inventory_bp.py`（路由）、`templates/inventory/index.html`（前端）。登录脚本独立于 Web 应用（`scripts/`），通过自举（uv + playwright + 国内源）运行，凭证自动上传到 `/inventory/login/upload`。

**Tech Stack:** Python 3.10+、Flask 3.1+、httpx（服务端查询）、openpyxl、playwright（仅登录脚本）、uv（自举）、Bootstrap 5.3（前端）。

**Spec:** `docs/superpowers/specs/2026-08-15-inventory-query-design.md`

## Global Constraints

- 版本目标 3.3.0；pyproject.toml version 与 CHANGELOG 同步（功能/大改 → 3.3.0）
- 统一文案集 P1–P12（见 Spec §九）：后端 `MESSAGES` 常量、前端 `const MSG`、脚本 `MSG = {}`，禁止散落硬编码
- "会话"一律表述为"登录"；不出现"Cookie"字样；工具统一称"登录脚本"
- 登录凭证一次性、不长期储存；临时缓存默认 2h（`AMRO_SESSION_TTL`）
- TLS 标准证书校验（`verify=True`）
- AMRO 外部 API 一律 mock，测试隔离 DB 副本，严禁触碰 `data/reqman_db.json`
- 国内源：PyPI 阿里云 `https://mirrors.aliyun.com/pypi/simple/`；playwright 内核 `https://registry.npmmirror.com/-/binary/playwright/`
- 环境存脚本同级 `.runtime/` 目录，仅首次下载
- 现有测试命令：`pytest -m "not slow"`、`ruff check src/ tests/`

---

### Task 1: AMRO 连接器（connectors.amro）

**Files:**
- Create: `src/reqman/services/connectors/__init__.py`
- Create: `src/reqman/services/connectors/amro.py`
- Test: `tests/test_amro_connector.py`

**Interfaces:**
- Produces:
  - `API_URL: str` — AMRO 库存查询接口地址
  - `amro_base_map: dict[str, str]` — SWERK 前缀 → 基地中文名
  - `is_kunming(swerk: str) -> bool`
  - `query_single_pn(client: httpx.AsyncClient, cookies: dict[str, str], pn: str, inv_type: str) -> list[dict]`
  - `query_kunming_stock(client: httpx.AsyncClient, cookies: dict[str, str], pn: str) -> KunmingStock | None`
  - `class KunmingStock(NamedTuple)` — 字段 `total_qty: float, unit: str, pn_desc: str`
  - `check_session(client: httpx.AsyncClient, cookies: dict[str, str], pn: str) -> bool` — 会话探活，code=100 返回 False

- [ ] **Step 1: 创建包与测试文件**

创建 `src/reqman/services/connectors/__init__.py`（空文件）。编写 `tests/test_amro_connector.py`：

```python
"""AMRO 连接器单元测试（mock httpx）"""
import pytest
import httpx
from reqman.services.connectors import amro


def _make_client(json_body):
    class _FakeResp:
        def __init__(self, body, status=200):
            self._body = body
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=None)

        def json(self):
            return self._body

    class _FakeClient:
        def __init__(self):
            self.data = {}

        async def post(self, url, data=None, cookies=None, timeout=None):
            self.data = {"url": url, "data": data, "cookies": cookies}
            return _FakeResp(json_body)

    return _FakeClient(), _FakeResp


class TestIsKunming:
    def test_kunming_prefix(self):
        assert amro.is_kunming("KM123") is True

    def test_non_kunming(self):
        assert amro.is_kunming("CD100") is False

    def test_empty(self):
        assert amro.is_kunming("") is False


class TestQueryKunmingStock:
    @pytest.mark.asyncio
    async def test_sums_kunming_only(self, monkeypatch):
        body = {"code": 200, "data": [
            {"swerk": "KM01", "clabs": 5, "meins": "EA", "maktx": "螺钉"},
            {"swerk": "KM02", "clabs": 3, "meins": "EA", "maktx": ""},
            {"swerk": "CD01", "clabs": 100, "meins": "EA", "maktx": ""},
        ]}
        client, _ = _make_client(body)
        stock = await amro.query_kunming_stock(client, {"k": "v"}, "PN-1")
        assert stock is not None
        assert stock.total_qty == 8.0
        assert stock.unit == "EA"
        assert stock.pn_desc == "螺钉"

    @pytest.mark.asyncio
    async def test_session_expired_raises(self):
        client, _ = _make_client({"code": 100, "msg": "会话过期"})
        with pytest.raises(RuntimeError, match="会话过期"):
            await amro.query_kunming_stock(client, {}, "PN-1")

    @pytest.mark.asyncio
    async def test_all_requests_fail_returns_none(self):
        class _FailResp:
            def raise_for_status(self):
                raise httpx.ConnectError("no net")

            def json(self):
                raise AssertionError("should not reach")

        class _FailClient:
            async def post(self, url, data=None, cookies=None, timeout=None):
                return _FailResp()

        stock = await amro.query_kunming_stock(_FailClient(), {}, "PN-1")
        assert stock is None


class TestCheckSession:
    @pytest.mark.asyncio
    async def test_ok_session(self):
        client, _ = _make_client({"code": 200, "data": []})
        assert await amro.check_session(client, {}, "PN-1") is True

    @pytest.mark.asyncio
    async def test_expired_session(self):
        client, _ = _make_client({"code": 100, "msg": "会话过期"})
        assert await amro.check_session(client, {}, "PN-1") is False

    @pytest.mark.asyncio
    async def test_network_error_still_true(self):
        class _FailClient:
            async def post(self, url, data=None, cookies=None, timeout=None):
                raise httpx.ConnectError("no net")

        assert await amro.check_session(_FailClient(), {}, "PN-1") is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_amro_connector.py -v`
Expected: FAIL（`ModuleNotFoundError: reqman.services.connectors`）或 asyncio 标记缺失。若 `pytest.mark.asyncio` 不可用，改用 `pytest-asyncio`；若未安装，将异步测试改为使用 `asyncio.run()` 同步调用（见 Step 4 备选）。

- [ ] **Step 3: 实现 amro.py**

```python
"""AMRO 库存查询连接器 — 唯一接触川航 AMRO API 的模块

从上级目录库存查询工具（scal）迁移，TLS 改为标准证书校验（verify=True）。
"""
from __future__ import annotations

from typing import NamedTuple

import httpx

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
        except Exception:
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
        if "登录已失效" in str(e) or "会话过期" in str(e):
            return False
        return True
    except Exception:
        return True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_amro_connector.py -v`
Expected: PASS。

备选：若未安装 `pytest-asyncio`，将各 `@pytest.mark.asyncio` 异步测试改为同步包装，如：
```python
def test_sums_kunming_only(self, monkeypatch):
    body = {...}
    client, _ = _make_client(body)
    import asyncio
    stock = asyncio.run(amro.query_kunming_stock(client, {"k": "v"}, "PN-1"))
    assert stock.total_qty == 8.0
```
（优先尝试安装 pytest-asyncio；若避免新增 dev 依赖则用 asyncio.run 包装。）

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/connectors/__init__.py src/reqman/services/connectors/amro.py tests/test_amro_connector.py
git commit -m "feat: AMRO库存查询连接器（verify=True，mock测试）"
```

---

### Task 2: 登录凭证临时缓存（connectors.session）

**Files:**
- Create: `src/reqman/services/connectors/session.py`
- Test: `tests/test_session_cache.py`

**Interfaces:**
- Consumes: 无（纯标准库）
- Produces:
  - `class LoginSessionStore`
    - `__init__(self, path: str | Path, ttl_seconds: int = 7200)`
    - `load(self) -> dict | None` — 返回 `{"cookies": {name: value}, "expires_at": iso}`；无/过期返回 None
    - `save(self, cookies: list[dict]) -> None` — 原子写，记录 created_at/expires_at
    - `clear(self) -> None`
    - `remaining_seconds(self) -> int` — 剩余秒数；无缓存返回 0

- [ ] **Step 1: 写测试 `tests/test_session_cache.py`**

```python
"""登录凭证临时缓存测试"""
import json
import time
from pathlib import Path
from reqman.services.connectors.session import LoginSessionStore


def _cookies():
    return [{"name": "JSESSIONID", "value": "abc123"}]


class TestLoginSessionStore:
    def test_save_then_load(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=7200)
        store.save(_cookies())
        loaded = store.load()
        assert loaded is not None
        assert loaded["cookies"]["JSESSIONID"] == "abc123"
        assert "expires_at" in loaded

    def test_load_missing_returns_none(self, tmp_path: Path):
        store = LoginSessionStore(tmp_path / "nope.json", ttl_seconds=7200)
        assert store.load() is None

    def test_expired_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=-1)  # 立即过期
        store.save(_cookies())
        assert store.load() is None

    def test_remaining_seconds(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=7200)
        store.save(_cookies())
        rem = store.remaining_seconds()
        assert 7190 <= rem <= 7200

    def test_clear(self, tmp_path: Path):
        path = tmp_path / "session.json"
        store = LoginSessionStore(path, ttl_seconds=7200)
        store.save(_cookies())
        store.clear()
        assert store.load() is None
        assert not path.exists()

    def test_corrupt_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "session.json"
        path.write_text("{bad json", encoding="utf-8")
        store = LoginSessionStore(path, ttl_seconds=7200)
        assert store.load() is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_session_cache.py -v`
Expected: FAIL（`ModuleNotFoundError: reqman.services.connectors.session`）

- [ ] **Step 3: 实现 session.py**

```python
"""登录凭证临时缓存 — 一次性凭证，短时复用，用完/超时即删

与业务数据库（json_store）解耦；原子写防并发损坏；预留未来用户绑定字段。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _atomic_write(path: Path, data: dict) -> None:
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except (OSError, TypeError):
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class LoginSessionStore:
    """一次性登录凭证临时缓存（默认 TTL 2 小时）。"""

    _lock = threading.Lock()

    def __init__(self, path: str | Path, ttl_seconds: int = 7200):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_raw(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("登录凭证缓存读取失败: %s", self.path)
            return None

    def load(self) -> dict | None:
        with self._lock:
            data = self._read_raw()
            if not data:
                return None
            expires = data.get("expires_at", "")
            try:
                expires_dt = datetime.fromisoformat(expires)
            except (ValueError, TypeError):
                return None
            if expires_dt < datetime.now(timezone.utc).astimezone():
                return None
            cookies = data.get("cookies", {})
            if not isinstance(cookies, dict) or not cookies:
                return None
            return {"cookies": cookies, "expires_at": expires}

    def save(self, cookies: list[dict]) -> None:
        cookie_map = {c.get("name", ""): c.get("value", "") for c in cookies if c.get("name")}
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(seconds=self.ttl_seconds)
        data = {
            "cookies": cookie_map,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            # 预留用户绑定字段（G1 全局共享，未来用户体系接入时填充）
            "user": None,
        }
        with self._lock:
            _atomic_write(self.path, data)

    def clear(self) -> None:
        with self._lock:
            try:
                if self.path.exists():
                    self.path.unlink()
            except OSError:
                logger.warning("清除登录凭证缓存失败: %s", self.path)

    def remaining_seconds(self) -> int:
        data = self._read_raw()
        if not data:
            return 0
        expires = data.get("expires_at", "")
        try:
            expires_dt = datetime.fromisoformat(expires)
        except (ValueError, TypeError):
            return 0
        rem = (expires_dt - datetime.now(timezone.utc).astimezone()).total_seconds()
        return max(int(rem), 0)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_session_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/connectors/session.py tests/test_session_cache.py
git commit -m "feat: 登录凭证临时缓存（原子写，TTL 2h 可配）"
```

---

### Task 3: 需求单 Excel 读写（xlsx_workbook）

**Files:**
- Create: `src/reqman/services/xlsx_workbook.py`
- Test: `tests/test_xlsx_workbook.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class DemandRow(NamedTuple)` — `part_number: str, name: str, qty: float, stock_cell: str, row_idx: int`
  - `read_demand(path: str | Path) -> list[DemandRow]` — 读航材区（表头"定检专业\n（航材）"）+ 备用区（"备用航材需求"）
  - `write_inventory_copy(source_path: str | Path, results: dict[str, float], pn_qty: dict[str, list[float]], pn_cells: dict[str, list[str]], timestamp_suffix: str | None = None) -> Path`

- [ ] **Step 1: 写测试，创建 fixture xlsx**

创建 `tests/test_xlsx_workbook.py`，用 openpyxl 在 tmp_path 构建需求单样表：

```python
"""需求单 Excel 读写测试（区域识别/回填/标红标黄）"""
from pathlib import Path
import openpyxl
from openpyxl.styles import PatternFill
from reqman.services.xlsx_workbook import read_demand, write_inventory_copy

RED = "FF0000"
YELLOW = "FFFF00"


def _build_demand_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "需求单"
    # 航材区表头（第 14 行），数据 15 行起
    ws["A14"] = "定检专业\n（航材）"
    ws["A15"] = "发动机"
    ws["B15"] = "螺钉"
    ws["C15"] = "PN-001"
    ws["E15"] = "2"
    ws["A16"] = "发动机"
    ws["B16"] = "螺母"
    ws["C16"] = "PN-002"
    ws["E16"] = "5"
    # 备用区标题与表头
    ws["A18"] = "备用航材需求"
    ws["A19"] = "机体"
    ws["B19"] = "垫片"
    ws["C19"] = "PN-003"
    ws["E19"] = "1"
    wb.save(path)


class TestReadDemand:
    def test_read_both_sections(self, tmp_path: Path):
        p = tmp_path / "demand.xlsx"
        _build_demand_xlsx(p)
        rows = read_demand(p)
        assert len(rows) == 3
        assert rows[0].part_number == "PN-001"
        assert rows[0].qty == 2.0
        assert rows[2].part_number == "PN-003"

    def test_pn_uppercased(self, tmp_path: Path):
        p = tmp_path / "demand.xlsx"
        _build_demand_xlsx(p)
        rows = read_demand(p)
        assert rows[0].part_number == "PN-001"


class TestWriteInventoryCopy:
    def _setup(self, tmp_path: Path):
        src = tmp_path / "demand.xlsx"
        _build_demand_xlsx(src)
        rows = read_demand(src)
        pn_cells, pn_qty = {}, {}
        for r in rows:
            pn_cells.setdefault(r.part_number, []).append(r.stock_cell)
            pn_qty.setdefault(r.part_number, []).append(r.qty)
        return src, pn_cells, pn_qty

    def test_writes_stock_and_red(self, tmp_path: Path):
        src, pn_cells, pn_qty = self._setup(tmp_path)
        results = {"PN-001": 1.0, "PN-002": 10.0, "PN-003": 3.0}
        dest = write_inventory_copy(src, results, pn_qty, pn_cells, timestamp_suffix="TEST")
        assert dest.exists()
        assert "_库存已填_TEST.xlsx" in dest.name
        wb = openpyxl.load_workbook(dest)
        ws = wb.active
        # PN-001 需求 2 库存 1 → 标红
        assert ws["G15"].value == 1
        assert ws["B15"].fill.start_color.rgb.endswith(RED)
        # PN-002 需求 5 库存 10 → 正常不标色
        assert ws["G16"].value == 10
        assert ws["B16"].fill.patternType is None
        # PN-003 需求 1 库存 3 → 告警黄（1 <= 3 < 3? 否：3 >= 1+2 正常）
        wb.close()

    def test_warning_yellow(self, tmp_path: Path):
        src, pn_cells, pn_qty = self._setup(tmp_path)
        results = {"PN-001": 2.0, "PN-002": 6.0, "PN-003": 2.0}
        dest = write_inventory_copy(src, results, pn_qty, pn_cells, timestamp_suffix="WARN")
        wb = openpyxl.load_workbook(dest)
        ws = wb.active
        # PN-003 需求 1 库存 2 → 需求<=2<需求+2 → 标黄
        assert ws["B19"].fill.start_color.rgb.endswith(YELLOW)
        wb.close()

    def test_no_stock_fills_zero(self, tmp_path: Path):
        src, pn_cells, pn_qty = self._setup(tmp_path)
        results = {}
        dest = write_inventory_copy(src, results, pn_qty, pn_cells, timestamp_suffix="ZERO")
        wb = openpyxl.load_workbook(dest)
        ws = wb.active
        assert ws["G15"].value == 0
        assert ws["B15"].fill.start_color.rgb.endswith(RED)  # 0 < 需求
        wb.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_xlsx_workbook.py -v`
Expected: FAIL（`ModuleNotFoundError: reqman.services.xlsx_workbook`）

- [ ] **Step 3: 实现 xlsx_workbook.py**

```python
"""需求单 Excel 读写 — 迁移自上级目录库存查询工具（scal）

读航材区（表头"定检专业\\n（航材）"）与备用区（"备用航材需求"），
回填 G 列库存并标红（库存<需求）/标黄（需求≤库存<需求+2）。
原文件只读，输出带时间戳副本。
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import NamedTuple

import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

RED_FILL = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
YELLOW_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

MATERIAL_HEADER = "定检专业\n（航材）"
SPARE_HEADER = "备用航材需求"

COL_PN = 3     # C
COL_NAME = 2   # B
COL_QTY = 5    # E
COL_STOCK = 7  # G


class DemandRow(NamedTuple):
    part_number: str
    name: str
    qty: float
    stock_cell: str
    row_idx: int


def _find_data_start(ws: openpyxl.Worksheet, header_keyword: str) -> int | None:
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=1):
        cell = row[0]
        if cell.value and header_keyword in str(cell.value):
            for r in range(cell.row + 1, ws.max_row + 1):
                val = ws.cell(r, COL_PN).value
                if val and str(val).strip() not in ("", "件号"):
                    return r
    return None


def _next_section_row(ws: openpyxl.Worksheet, start: int) -> int | None:
    for r in range(start, ws.max_row + 1):
        val = ws.cell(r, 1).value
        if val and re.match(r"^[三四五六七八九十]、", str(val).strip()):
            return r
    return None


def _parse_qty(raw: str | int | float | None) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    m = re.search(r"[\d.]+", str(raw))
    return float(m.group()) if m else 0.0


def read_demand(path: str | Path) -> list[DemandRow]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("No active sheet")

    rows: list[DemandRow] = []
    mat_start = _find_data_start(ws, MATERIAL_HEADER)
    spare_start = _find_data_start(ws, SPARE_HEADER)

    if mat_start:
        end = _next_section_row(ws, mat_start) or (ws.max_row + 1)
        if spare_start and spare_start > mat_start:
            end = min(end, spare_start)
        for r in range(mat_start, end):
            pn = ws.cell(r, COL_PN).value
            if not pn or not str(pn).strip():
                continue
            name = str(ws.cell(r, COL_NAME).value or "").strip()
            qty = _parse_qty(ws.cell(r, COL_QTY).value)
            rows.append(DemandRow(
                str(pn).strip().upper(), name, qty,
                get_column_letter(COL_STOCK) + str(r), r,
            ))

    if spare_start:
        end = _next_section_row(ws, spare_start) or (ws.max_row + 1)
        for r in range(spare_start, end):
            pn = ws.cell(r, COL_PN).value
            if not pn or not str(pn).strip():
                continue
            name = str(ws.cell(r, COL_NAME).value or "").strip()
            qty = _parse_qty(ws.cell(r, COL_QTY).value)
            rows.append(DemandRow(
                str(pn).strip().upper(), name, qty,
                get_column_letter(COL_STOCK) + str(r), r,
            ))

    wb.close()
    return rows


def write_inventory_copy(
    source_path: str | Path,
    results: dict[str, float],
    pn_qty: dict[str, list[float]],
    pn_cells: dict[str, list[str]],
    timestamp_suffix: str | None = None,
) -> Path:
    source = Path(source_path)
    if timestamp_suffix is None:
        timestamp_suffix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    dest = source.parent / f"{source.stem}_库存已填_{timestamp_suffix}.xlsx"

    wb = openpyxl.load_workbook(source)
    ws = wb.active
    if ws is None:
        raise ValueError("No active sheet")

    for pn, cells in pn_cells.items():
        stock_val = results.get(pn, 0.0)
        qtys = pn_qty.get(pn, [0.0])

        for cell_addr, qty in zip(cells, qtys):
            cell = ws[cell_addr]
            cell.value = int(stock_val) if stock_val == int(stock_val) else stock_val

            if stock_val < qty:
                fill = RED_FILL
            elif stock_val < qty + 2:
                fill = YELLOW_FILL
            else:
                fill = None

            if fill:
                row = cell.row
                for c in range(2, 8):  # B(2) ~ G(7)
                    ws.cell(row, c).fill = fill

    wb.save(dest)
    wb.close()
    return dest
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_xlsx_workbook.py -v`
Expected: PASS。若标黄判定与预期不符，核对规则：`stock < qty` 标红；`qty <= stock < qty + 2` 标黄（注意测试中"需求1库存3"应正常不标色，"需求1库存2"标黄）。

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/xlsx_workbook.py tests/test_xlsx_workbook.py
git commit -m "feat: 需求单Excel读写（区域识别/回填/标红标黄）"
```

---

### Task 4: 库存查询业务编排（inventory_service）

**Files:**
- Create: `src/reqman/services/inventory_service.py`
- Test: `tests/test_inventory_service.py`

**Interfaces:**
- Consumes:
  - `amro.query_kunming_stock`, `amro.check_session`（Task 1）
  - `xlsx_workbook.read_demand`, `xlsx_workbook.write_inventory_copy`（Task 3）
  - `LoginSessionStore`（Task 2）
- Produces:
  - `class InventoryService`
    - `__init__(self, session_store: LoginSessionStore, max_concurrent: int = 10)`
    - `get_login_status(self) -> dict` — `{"ready": bool, "remaining_seconds": int}`
    - `check_login(self) -> bool` — 探活（读缓存，有则调 check_session）
    - `save_login(self, cookies: list[dict]) -> None`
    - `run_query(self, demand_path: str | Path) -> QueryResult` — 全流程查询
  - `class QueryResult(NamedTuple)` — `dest_path: Path, total: int, success: int, fail: int, shortage: int, warning: int`

- [ ] **Step 1: 写测试 `tests/test_inventory_service.py`**

```python
"""库存查询业务编排测试"""
from pathlib import Path
import pytest
from reqman.services.inventory_service import InventoryService
from reqman.services.connectors.session import LoginSessionStore


def _store(tmp_path: Path):
    return LoginSessionStore(tmp_path / "session.json", ttl_seconds=7200)


class TestGetLoginStatus:
    def test_not_ready(self, tmp_path: Path):
        svc = InventoryService(_store(tmp_path))
        status = svc.get_login_status()
        assert status["ready"] is False
        assert status["remaining_seconds"] == 0

    def test_ready(self, tmp_path: Path):
        store = _store(tmp_path)
        store.save([{"name": "JSESSIONID", "value": "abc"}])
        svc = InventoryService(store)
        status = svc.get_login_status()
        assert status["ready"] is True
        assert status["remaining_seconds"] > 0


class TestSaveLogin:
    def test_saves_and_ready(self, tmp_path: Path):
        store = _store(tmp_path)
        svc = InventoryService(store)
        svc.save_login([{"name": "JSESSIONID", "value": "xyz"}])
        assert store.load()["cookies"]["JSESSIONID"] == "xyz"


class TestRunQuery:
    def test_query_flow(self, tmp_path: Path, monkeypatch):
        import openpyxl
        src = tmp_path / "demand.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A14"] = "定检专业\n（航材）"
        ws["A15"] = "发动机"; ws["B15"] = "螺钉"; ws["C15"] = "PN-001"; ws["E15"] = "2"
        wb.save(src)

        async def fake_query(client, cookies, pn):
            from reqman.services.connectors.amro import KunmingStock
            return KunmingStock(1.0, "EA", "螺钉")

        import reqman.services.connectors.amro as amro_mod
        monkeypatch.setattr(amro_mod, "query_kunming_stock", fake_query)

        store = _store(tmp_path)
        store.save([{"name": "JSESSIONID", "value": "abc"}])
        svc = InventoryService(store, max_concurrent=2)
        result = svc.run_query(src)
        assert result.total == 1
        assert result.success == 1
        assert result.shortage == 1  # 需求2 库存1 → 标红
        assert result.dest_path.exists()

    def test_query_no_login_raises(self, tmp_path: Path):
        svc = InventoryService(_store(tmp_path))
        with pytest.raises(RuntimeError):
            svc.run_query(tmp_path / "x.xlsx")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_inventory_service.py -v`
Expected: FAIL（`ModuleNotFoundError: reqman.services.inventory_service`）

- [ ] **Step 3: 实现 inventory_service.py**

```python
"""库存查询业务编排 — 读Excel → 去重 → 并发查询 → 副本回填"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import NamedTuple

import httpx

from .connectors.amro import check_session, query_kunming_stock
from .connectors.session import LoginSessionStore
from .xlsx_workbook import read_demand, write_inventory_copy

logger = logging.getLogger(__name__)


class QueryResult(NamedTuple):
    dest_path: Path
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
        return {"ready": True, "remaining_seconds": self.session_store.remaining_seconds()}

    def check_login(self) -> bool:
        """探活：有缓存则真实调用一次 AMRO API。"""
        data = self.session_store.load()
        if not data:
            return False
        async def _probe():
            async with httpx.AsyncClient(verify=True) as client:
                pn = data["cookies"].get("I_MFRPN") or "ST1946-107"
                return await check_session(client, data["cookies"], pn)
        try:
            return asyncio.run(_probe())
        except Exception:
            return False

    def save_login(self, cookies: list[dict]) -> None:
        self.session_store.save(cookies)

    def run_query(self, demand_path: str | Path) -> QueryResult:
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
                            stock = await query_kunming_stock(client, cookies, pn)
                            if stock is not None:
                                results[pn] = stock.total_qty
                                success += 1
                            else:
                                results[pn] = 0.0
                                fail += 1
                        except Exception as e:
                            results[pn] = 0.0
                            fail += 1
                            logger.warning("查询失败 %s: %s", pn, e)
                await asyncio.gather(*[query_one(pn) for pn in all_pns])
            return results, success, fail

        results, success, fail = asyncio.run(_run())
        dest = write_inventory_copy(demand_path, results, pn_qty, pn_cells)

        shortage = sum(
            1 for pn in pn_cells for qty in pn_qty.get(pn, [0])
            if results.get(pn, 0) < qty
        )
        warning = sum(
            1 for pn in pn_cells for qty in pn_qty.get(pn, [0])
            if qty <= results.get(pn, 0) < qty + 2
        )
        return QueryResult(dest, len(all_pns), success, fail, shortage, warning)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_inventory_service.py -v`
Expected: PASS。注意 `check_login` 探活用占位件号需真实 API，测试中不覆盖（仅接口存在）。

- [ ] **Step 5: Commit**

```bash
git add src/reqman/services/inventory_service.py tests/test_inventory_service.py
git commit -m "feat: 库存查询业务编排（去重/并发/回填/统计）"
```

---

### Task 5: 配置与环境变量（config + pyproject + gitignore + 依赖注入）

**Files:**
- Modify: `src/reqman/config.py`
- Modify: `src/reqman/__init__.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - `config.AMRO_API_URL: str`
  - `config.AMRO_COOKIE_FILE: Path`（`data/cookie/amro_cookies.json`）
  - `config.AMRO_MAX_CONCURRENT: int`
  - `config.AMRO_SESSION_TTL: int`（秒，默认 7200）
  - `config.AMRO_LOGIN_VERSION: str`（登录脚本版本，如 "1"）
  - `app.extensions["inventory_service"]`（`InventoryService` 实例）

- [ ] **Step 1: 修改 config.py**

在 `src/reqman/config.py` 末尾追加：

```python
# ---------- AMRO 库存查询 ----------
AMRO_API_URL: str = os.getenv("AMRO_API_URL", "https://me.sichuanair.com/api/v1/plugins/MM_PARTNUMBERCHAXUN_LIST")
AMRO_COOKIE_FILE: Path = BASE_DIR / os.getenv("AMRO_COOKIE_FILE", "data/cookie/amro_cookies.json")
AMRO_MAX_CONCURRENT: int = int(os.getenv("AMRO_MAX_CONCURRENT", "10"))
AMRO_SESSION_TTL: int = int(os.getenv("AMRO_SESSION_TTL", "7200"))  # 2 小时
AMRO_LOGIN_VERSION: str = os.getenv("AMRO_LOGIN_VERSION", "1")

# 自动创建 cookie 目录
AMRO_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: 修改 app.py 依赖注入**

在 `src/reqman/__init__.py` 的 DI 区（`app.extensions["card_service"] = ...` 之后）追加：

```python
from .services.connectors.session import LoginSessionStore
from .services.inventory_service import InventoryService
app.extensions["inventory_service"] = InventoryService(
    LoginSessionStore(str(AMRO_COOKIE_FILE), ttl_seconds=AMRO_SESSION_TTL),
    max_concurrent=AMRO_MAX_CONCURRENT,
)
```
同时更新 `from .config import ...` 导入（增加 `AMRO_COOKIE_FILE, AMRO_MAX_CONCURRENT, AMRO_SESSION_TTL`）。

- [ ] **Step 3: 修改 pyproject.toml 依赖**

在 `[project] dependencies` 增加 `"httpx>=0.27"`：
```toml
dependencies = [
    "flask>=3.1.0",
    "gunicorn>=21.2.0",
    "openpyxl>=3.1.0",
    "python-dotenv>=1.0.0",
    "tzdata>=2024.1",
    "httpx>=0.27",
]
```

- [ ] **Step 4: 修改 .gitignore**

追加：
```
data/cookie/
```

- [ ] **Step 5: 验证应用可启动**

Run: `python -c "from reqman import create_app; app = create_app(); assert 'inventory_service' in app.extensions; print('OK')"`
Expected: OK（无报错，依赖注入完成）。

- [ ] **Step 6: 运行相关测试**

Run: `python -m pytest tests/test_card_service.py tests/test_json_store.py -v`
Expected: PASS（回归无影响）。再运行 `ruff check src/reqman/config.py src/reqman/__init__.py`

- [ ] **Step 7: Commit**

```bash
git add src/reqman/config.py src/reqman/__init__.py pyproject.toml .gitignore
git commit -m "feat: AMRO配置与依赖注入（TTL 2h 默认，httpx依赖）"
```

---

### Task 6: 库存查询蓝图（inventory_bp）

**Files:**
- Create: `src/reqman/blueprints/inventory_bp.py`
- Create: `src/reqman/templates/inventory/index.html`（骨架，详细前端在 Task 9）
- Modify: `src/reqman/__init__.py`（注册蓝图）
- Test: `tests/integration/test_inventory_api.py`

**Interfaces:**
- Consumes: `app.extensions["inventory_service"]`（Task 5）；`utils.response.api_success/api_error`；`utils.error_handlers.ValidationError`
- Produces:
  - `inventory_bp: Blueprint`（url_prefix 无，路由见 Spec §五）
  - `MESSAGES: dict[str, str]` — P1–P12 文案集（供前端/脚本引用基准）
  - 路由：`GET /inventory`、`GET /inventory/session`、`GET /inventory/setup-package`、`POST /inventory/check-config`、`POST /inventory/login/upload`、`POST /inventory/query`

- [ ] **Step 1: 写集成测试 `tests/integration/test_inventory_api.py`**

```python
"""库存查询接口集成测试（mock AMRO）"""
import io
import zipfile
from pathlib import Path
import pytest
import openpyxl

# 复用 integration/conftest.py 的 app/client fixture

MESSAGES = {
    "P4": "❌ 系统未登录AMRO：请先点击「检查配置」选择脚本位置，或「新建配置」下载登录脚本，解压后双击运行完成登录",
    "P8": "登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试",
    "P10": "下载配置包（ZIP）后请解压，双击其中 start_login.bat 完成登录",
}


def _build_demand(tmp_path: Path) -> Path:
    src = tmp_path / "demand.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A14"] = "定检专业\n（航材）"
    ws["A15"] = "发动机"; ws["B15"] = "螺钉"; ws["C15"] = "PN-001"; ws["E15"] = "2"
    wb.save(src)
    return src


class TestInventoryPage:
    def test_page_accessible(self, client):
        resp = client.get("/inventory")
        assert resp.status_code == 200


class TestSession:
    def test_not_ready(self, client):
        resp = client.get("/inventory/session", headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["ready"] is False


class TestSetupPackage:
    def test_downloads_zip(self, client):
        resp = client.get("/inventory/setup-package")
        assert resp.status_code == 200
        assert resp.mimetype in ("application/zip", "application/x-zip-compressed")
        content = resp.data
        zf = zipfile.ZipFile(io.BytesIO(content))
        names = zf.namelist()
        assert any("amro_login.py" in n for n in names)
        assert any("start_login.bat" in n for n in names)
        assert any("README" in n for n in names)


class TestCheckConfig:
    def test_rejects_wrong_content(self, client):
        resp = client.post(
            "/inventory/check-config",
            data={"file": (io.BytesIO(b"not a script"), "foo.txt")},
            headers={"X-Requested-With": "XMLHttpRequest"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False


class TestLoginUpload:
    def test_upload_marks_ready(self, client, tmp_path):
        cookies_json = '[{"name":"JSESSIONID","value":"abc123"}]'
        resp = client.post(
            "/inventory/login/upload",
            data={"cookies": cookies_json},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # 再查状态应为 ready
        resp2 = client.get("/inventory/session", headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp2.get_json()["data"]["ready"] is True

    def test_upload_invalid_json(self, client):
        resp = client.post(
            "/inventory/login/upload",
            data={"cookies": "not json"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400


class TestQuery:
    def test_query_requires_login(self, client, tmp_path):
        src = _build_demand(tmp_path)
        with src.open("rb") as f:
            resp = client.post(
                "/inventory/query",
                data={"file": (f, "demand.xlsx")},
                headers={"X-Requested-With": "XMLHttpRequest"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "重新运行登录脚本" in data["message"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/integration/test_inventory_api.py -v`
Expected: FAIL（蓝图未注册，404）。

- [ ] **Step 3: 实现 inventory_bp.py**

```python
"""库存查询蓝图 — 页面 / 登录状态 / 配置包 / 检查 / 上传 / 查询"""
import io
import json
import zipfile

from flask import Blueprint, current_app, render_template, request, send_file

from ..config import AMRO_LOGIN_VERSION
from ..services.xlsx_workbook import read_demand
from ..utils.error_handlers import ValidationError
from ..utils.response import api_error, api_success

inventory_bp = Blueprint("inventory", __name__, template_folder="../templates")

logger = logging.getLogger(__name__)

# 统一文案集（P1–P12）— 三端集中定义，前端与脚本引用此基准
MESSAGES = {
    "P1": "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。",
    "P2": "已打开登录页面，请在浏览器中完成川航 AMRO 登录（账号/密码/验证码），登录后请保持页面不动。",
    "P3": "✅ 登录成功，本页面即将就绪。",
    "P4": "❌ 系统未登录AMRO：请先点击「检查配置」选择脚本位置，或「新建配置」下载登录脚本，解压后双击运行完成登录",
    "P5": "✅ 登录有效，剩余约 {minutes} 分钟",
    "P6": "⚠️ 登录有效期内若在其他浏览器/设备登录川航 AMRO，当前登录将被挤掉失效，需重新运行登录脚本",
    "P7": "❌ 查询登录已过期：请重新运行登录脚本",
    "P8": "登录已失效（可能被其他登录挤掉），请重新运行登录脚本后重试",
    "P9": "查询完成。",
    "P10": "下载配置包（ZIP）后请解压，双击其中 start_login.bat 完成登录",
    "P11": "未检测到有效配置：请选择正确的 amro_login.py 或配置包（ZIP）文件；若配置缺失或版本过旧，请点击「新建配置」重新下载",
    "P12": "✅ 配置正常：版本与当前系统匹配，可运行登录脚本完成登录",
}


def _service():
    return current_app.extensions["inventory_service"]


@inventory_bp.route("/inventory")
def index():
    return render_template("inventory/index.html", messages=MESSAGES, login_version=AMRO_LOGIN_VERSION)


@inventory_bp.route("/inventory/session", methods=["GET"])
def session_status():
    svc = _service()
    status = svc.get_login_status()
    data = {"ready": status["ready"], "remaining_seconds": status["remaining_seconds"]}
    if status["ready"]:
        minutes = max(status["remaining_seconds"] // 60, 1)
        data["message"] = MESSAGES["P5"].format(minutes=minutes)
    else:
        data["message"] = MESSAGES["P4"]
    return api_success(data=data)


@inventory_bp.route("/inventory/setup-package", methods=["GET"])
def setup_package():
    """动态生成登录脚本配置包 ZIP（注入当前服务器地址）。"""
    server_url = request.host_url.rstrip("/")
    py_source = _login_py_template(server_url)
    bat_source = _login_bat_template()
    readme_source = (
        "川航 AMRO 登录脚本配置包\n"
        "=======================\n"
        "1. 将本文件夹解压到任意位置\n"
        "2. 双击 start_login.bat\n"
        "3. 按提示关闭已登录的川航 AMRO 页面，点击确认后完成登录\n"
        "登录成功后脚本将自动上传凭证，本系统页面即可开始查询。\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("amro_login.py", py_source)
        zf.writestr("start_login.bat", bat_source)
        zf.writestr("README.txt", readme_source)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="amro_login_setup.zip",
                     mimetype="application/zip")


@inventory_bp.route("/inventory/check-config", methods=["POST"])
def check_config():
    """检查配置：上传 amro_login.py 或 ZIP，校验版本与地址。"""
    f = request.files.get("file")
    if f is None or not f.filename:
        raise ValidationError(MESSAGES["P11"])
    content = f.read()
    is_zip = f.filename.lower().endswith(".zip")
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                py_src = zf.read("amro_login.py").decode("utf-8")
        except (zipfile.BadZipFile, KeyError):
            raise ValidationError(MESSAGES["P11"])
    else:
        if not f.filename.endswith(".py"):
            raise ValidationError(MESSAGES["P11"])
        try:
            py_src = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError(MESSAGES["P11"])
    # 校验版本
    if f"LOGIN_VERSION = \"{AMRO_LOGIN_VERSION}\"" not in py_src and \
       f"LOGIN_VERSION='{AMRO_LOGIN_VERSION}'" not in py_src:
        raise ValidationError(MESSAGES["P11"])
    return api_success(message=MESSAGES["P12"])


@inventory_bp.route("/inventory/login/upload", methods=["POST"])
def login_upload():
    """登录凭证上传（登录脚本自动调用）。"""
    raw = (request.form.get("cookies") or "").strip()
    if not raw:
        raise ValidationError("缺少登录凭证")
    try:
        cookies = json.loads(raw)
    except json.JSONDecodeError:
        raise ValidationError("登录凭证格式错误")
    if not isinstance(cookies, list):
        raise ValidationError("登录凭证格式错误")
    _service().save_login(cookies)
    return api_success(message=MESSAGES["P3"])


@inventory_bp.route("/inventory/query", methods=["POST"])
def query():
    """执行库存查询：需先校验登录有效。"""
    svc = _service()
    if not svc.check_login():
        return api_error(MESSAGES["P8"], error_code="LOGIN_EXPIRED", status_code=400)
    f = request.files.get("file")
    if f is None or not f.filename or not f.filename.endswith(".xlsx"):
        raise ValidationError("请选择正确的需求单 Excel 文件（.xlsx）")
    tmp = Path(current_app.root_path).parent.parent / "output"
    tmp.mkdir(exist_ok=True)
    demand_path = tmp / "inventory_input.xlsx"
    f.save(demand_path)
    try:
        result = svc.run_query(demand_path)
    except RuntimeError:
        return api_error(MESSAGES["P8"], error_code="LOGIN_EXPIRED", status_code=400)
    except ValueError as e:
        raise ValidationError(str(e))
    data = {
        "total": result.total,
        "success": result.success,
        "fail": result.fail,
        "shortage": result.shortage,
        "warning": result.warning,
        "filename": result.dest_path.name,
    }
    return api_success(data=data, message=MESSAGES["P9"])


def _login_py_template(server_url: str) -> str:
    return (
        f'"""川航 AMRO 登录脚本 — 自动提取登录凭证并上传到需求单系统"""\n'
        "import asyncio, json, sys, tkinter as tk\n"
        "from tkinter import messagebox\n"
        f'SERVER_URL = "{server_url}"\n'
        f'UPLOAD_URL = "{server_url}/inventory/login/upload"\n'
        f'LOGIN_VERSION = "{AMRO_LOGIN_VERSION}"\n'
        'MSG_P1 = "⚠️ 使用前请先关闭浏览器中已登录的川航 AMRO 页面，否则会导致登录获取失败。"\n'
        'MSG_P2 = "已打开登录页面，请在浏览器中完成川航 AMRO 登录（账号/密码/验证码），登录后请保持页面不动。"\n'
        'MSG_P3 = "✅ 登录成功，本页面即将就绪。"\n'
        '\n'
        'def confirm():\n'
        '    root = tk.Tk(); root.withdraw()\n'
        '    ok = messagebox.askokcancel("提示", MSG_P1)\n'
        '    root.destroy()\n'
        '    return ok\n'
        '\n'
        'async def main():\n'
        '    from playwright.async_api import async_playwright\n'
        '    import httpx\n'
        '    if not confirm():\n'
        '        return\n'
        '    async with async_playwright() as p:\n'
        '        browser = await p.chromium.launch(headless=False)\n'
        '        ctx = await browser.new_context()\n'
        '        page = await ctx.new_page()\n'
        '        print(MSG_P2)\n'
        '        await page.goto("https://me.sichuanair.com/views/home.shtml", wait_until="domcontentloaded")\n'
        '        deadline = asyncio.get_event_loop().time() + 300\n'
        '        while asyncio.get_event_loop().time() < deadline:\n'
        '            cookies = await ctx.cookies()\n'
        '            names = {c["name"] for c in cookies}\n'
        '            if "JSESSIONID" in names:\n'
        '                async with httpx.AsyncClient(verify=True, timeout=15) as client:\n'
        '                    await client.post(UPLOAD_URL, data={"cookies": json.dumps(cookies, ensure_ascii=False)})\n'
        '                print(MSG_P3)\n'
        '                await browser.close()\n'
        '                return\n'
        '            await asyncio.sleep(2)\n'
        '        await browser.close()\n'
        '        raise TimeoutError("登录超时")\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    asyncio.run(main())\n'
    )


def _login_bat_template() -> str:
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "setlocal\r\n"
        "cd /d %~dp0\r\n"
        "set PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/\r\n"
        "set UV_PYTHON_INSTALL_MIRROR=https://mirrors.aliyun.com/python-release/\r\n"
        "set PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright/\r\n"
        "if not exist .runtime\\venv\\Scripts\\python.exe (\r\n"
        "    echo [首次使用] 正在自动安装运行环境，请稍候...\r\n"
        "    where uv >nul 2>nul || (python -m pip install -q uv || py -m pip install -q uv)\r\n"
        "    uv python install 3.11 || echo [警告] Python 安装失败\r\n"
        "    uv venv .runtime\\venv\r\n"
        "    .runtime\\venv\\Scripts\\python -m pip install -q -r scripts\\requirements-login.txt\r\n"
        "    .runtime\\venv\\Scripts\\playwright install chromium\r\n"
        ")\r\n"
        ".runtime\\venv\\Scripts\\python amro_login.py\r\n"
        "pause\r\n"
    )
```

- [ ] **Step 4: 注册蓝图**

在 `src/reqman/__init__.py` 蓝图注册区追加：
```python
from .blueprints.inventory_bp import inventory_bp
...
app.register_blueprint(inventory_bp)
```
同时蓝图文件内需要 `import logging`（补全顶部）。

- [ ] **Step 5: 创建 index.html 骨架（完整 UI 在 Task 9）**

创建 `src/reqman/templates/inventory/index.html` 最小可渲染页面：
```html
{% extends "base.html" %}
{% block title %}库存查询 - 定检需求单管理{% endblock %}
{% block content %}
<div class="card">
    <div class="card-header"><h5 class="mb-0">库存查询</h5></div>
    <div class="card-body">
        <p id="sessionMsg">{{ messages.P4 }}</p>
        <div class="d-flex gap-2">
            <a href="/inventory/setup-package" class="btn btn-primary btn-sm">🛠 新建配置</a>
            <button class="btn btn-outline-secondary btn-sm" id="checkConfigBtn">🔍 检查配置</button>
        </div>
        <div class="mt-3">
            <input type="file" id="demandFile" class="form-control" accept=".xlsx">
            <button class="btn btn-success btn-sm mt-2" id="startQueryBtn">开始查询</button>
        </div>
        <div id="resultBox" class="mt-3"></div>
    </div>
</div>
{% endblock %}
{% block scripts %}
<script>
const MSG = {{ messages | tojson }};
function refreshSession() {
    fetch('/inventory/session', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(r => r.json()).then(d => {
            document.getElementById('sessionMsg').textContent = d.data.message;
        });
}
refreshSession();
setInterval(refreshSession, 60000);
</script>
{% endblock %}
```
（base.html 已含 toast/loader 全局组件。）

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/integration/test_inventory_api.py -v`
Expected: PASS。

- [ ] **Step 7: 运行回归 + ruff**

Run: `python -m pytest -m "not slow" -q`（全量）与 `ruff check src/`
Expected: 全部通过；若 `logging` 未导入报错，补 `import logging`。

- [ ] **Step 8: Commit**

```bash
git add src/reqman/blueprints/inventory_bp.py src/reqman/templates/inventory/index.html src/reqman/__init__.py tests/integration/test_inventory_api.py
git commit -m "feat: 库存查询蓝图（session/setup-package/check-config/upload/query）"
```

---

### Task 7: 登录脚本资源（scripts/）

**Files:**
- Create: `scripts/amro_login.py`
- Create: `scripts/start_login.bat`
- Create: `scripts/requirements-login.txt`

**Interfaces:**
- Consumes: 无（独立运行）
- Produces: 登录脚本（含 `LOGIN_VERSION` 与 `SERVER_URL` 占位，运行时被 Task 6 模板替换生成 ZIP）

- [ ] **Step 1: 创建脚本资源**

创建 `scripts/amro_login.py`（即 Task 6 中 `_login_py_template` 生成的完整代码，含 `SERVER_URL = "http://127.0.0.1:5001"` 默认占位、`LOGIN_VERSION = "1"`、P1/P2/P3 文案、确认弹窗、playwright 登录、上传逻辑）。创建 `scripts/start_login.bat`（自举入口，内容同 Task 6 `_login_bat_template`）。创建 `scripts/requirements-login.txt`：

```
httpx>=0.27
playwright>=1.48
```

- [ ] **Step 2: 验证脚本语法**

Run: `python -m py_compile scripts/amro_login.py`
Expected: 无错误。

- [ ] **Step 3: 同步模板与脚本内容一致**

检查 `inventory_bp.py` 的 `_login_py_template` 与 `scripts/amro_login.py` 保持同步（同一逻辑、同一 LOGIN_VERSION、同一文案）。若不一致，以 `scripts/amro_login.py` 为准回填模板（模板即脚本内容 + 注入 SERVER_URL/LOGIN_VERSION）。

- [ ] **Step 4: Commit**

```bash
git add scripts/amro_login.py scripts/start_login.bat scripts/requirements-login.txt
git commit -m "feat: 登录脚本资源（自举+国内源+自动上传）"
```

---

### Task 8: 前端查询页（inventory/index.html 完整版）

**Files:**
- Modify: `src/reqman/templates/inventory/index.html`（完整三区块 UI）
- Modify: `src/reqman/templates/base.html`（导航入口）

**Interfaces:**
- Consumes: `{{ messages }}`、`{{ login_version }}`（Task 6 传入）；`/inventory/session`、`/inventory/check-config`、`/inventory/query`、`/inventory/setup-package` 路由
- Produces: 完整交互页面

- [ ] **Step 1: 修改 base.html 导航**

在 `src/reqman/templates/base.html` 导航中，"工作包"链接后追加：
```html
<li class="nav-item">
    <a class="nav-link {{ 'active' if request.path == '/inventory' }}" href="/inventory">库存查询</a>
</li>
```

- [ ] **Step 2: 完整实现 index.html**

覆盖三区块：① 登录状态卡（P4/P5/P6 文案、剩余时间、页面进入探活 + 60s 轮询）② 配置区（新建配置 P10、检查配置 P11/P12、使用指引弹窗）③ 查询区（upload-zone 拖拽/点击、开始查询 P1 modal 确认 → 进度/结果 P9）。关键逻辑：

```html
{% extends "base.html" %}
{% block title %}库存查询 - 定检需求单管理{% endblock %}
{% block content %}
<style>
    .inventory-status { display:flex; align-items:center; gap:10px; padding:14px 16px; border-radius:10px; }
    .inventory-status.ok { background:#e8f5e9; color:#2e7d32; }
    .inventory-status.bad { background:#fdecea; color:#c62828; }
</style>
<div class="card mb-4">
    <div class="card-header"><h5 class="mb-0">📦 库存查询</h5></div>
    <div class="card-body">
        <!-- ① 状态卡 -->
        <div id="sessionCard" class="inventory-status bad mb-3">
            <span id="sessionIcon">❌</span>
            <div>
                <div id="sessionMsg">{{ messages.P4 }}</div>
                <div id="sessionWarn" style="display:none" class="small">{{ messages.P6 }}</div>
            </div>
        </div>

        <!-- ② 配置区 -->
        <div class="d-flex flex-wrap gap-2 mb-3">
            <a href="/inventory/setup-package" class="btn btn-primary btn-sm" title="{{ messages.P10 }}">🛠 新建配置</a>
            <button class="btn btn-outline-secondary btn-sm" id="checkConfigBtn">🔍 检查配置</button>
            <button class="btn btn-outline-info btn-sm" id="guideBtn">❓ 使用指引</button>
        </div>
        <input type="file" id="checkFile" accept=".py,.zip" style="display:none">

        <!-- ③ 查询区 -->
        <div class="row g-3">
            <div class="col-md-8">
                <div class="upload-zone" id="zoneDemand" onclick="document.getElementById('demandFile').click()">
                    <div class="icon">📋</div>
                    <h6 class="mt-2">点击上传需求单 Excel</h6>
                    <p class="text-muted small mb-0">支持 .xlsx（含航材区/备用区）</p>
                    <input type="file" id="demandFile" name="file" accept=".xlsx" style="display:none"
                           onchange="fileSelected(this,'zoneDemand')">
                    <div class="file-name small text-success mt-2" style="display:none"></div>
                </div>
            </div>
            <div class="col-md-4 d-flex align-items-center">
                <button class="btn btn-success btn-sm px-4" id="startQueryBtn">▶ 开始查询</button>
            </div>
        </div>
        <div id="progressBox" class="mt-3" style="display:none">
            <div class="progress"><div class="progress-bar" id="queryProgress" style="width:0%"></div></div>
            <p class="small text-muted mt-1" id="progressLabel">准备中...</p>
        </div>
        <div id="resultBox" class="mt-3"></div>
    </div>
</div>

<!-- P1 确认 Modal -->
<div class="modal fade" id="p1Modal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h6 class="modal-title">⚠️ 使用提示</h6></div>
        <div class="modal-body">{{ messages.P1 }}</div>
        <div class="modal-footer">
            <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">取消</button>
            <button class="btn btn-primary btn-sm" id="p1ConfirmBtn">确认</button>
        </div>
    </div></div>
</div>

<!-- 使用指引 Modal -->
<div class="modal fade" id="guideModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h6 class="modal-title">使用指引</h6></div>
        <div class="modal-body">
            <ol class="mb-0">
                <li>点击「新建配置」下载配置包并解压</li>
                <li>双击其中 start_login.bat，确认提示后完成登录</li>
                <li>页面状态变为"登录有效"后，上传需求单 Excel 并点击「开始查询」</li>
            </ol>
        </div>
    </div></div>
</div>
{% endblock %}

{% block scripts %}
<script>
const MSG = {{ messages | tojson }};
var loginReady = false;

function fileSelected(input, zoneId) {
    var zone = document.getElementById(zoneId);
    var name = input.files[0] ? input.files[0].name : '';
    if (name) {
        zone.classList.add('has-file');
        zone.querySelector('.file-name').textContent = '✅ ' + name;
        zone.querySelector('.file-name').style.display = 'block';
    }
}

function refreshSession() {
    fetch('/inventory/session', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(r => r.json()).then(d => {
            var data = d.data;
            var card = document.getElementById('sessionCard');
            var msg = document.getElementById('sessionMsg');
            var warn = document.getElementById('sessionWarn');
            msg.textContent = data.message;
            if (data.ready) {
                loginReady = true;
                card.className = 'inventory-status ok mb-3';
                document.getElementById('sessionIcon').textContent = '✅';
                warn.style.display = 'block';
            } else {
                loginReady = false;
                card.className = 'inventory-status bad mb-3';
                document.getElementById('sessionIcon').textContent = '❌';
                warn.style.display = 'none';
            }
        }).catch(function(){ window.safeToast('获取登录状态失败', 'error'); });
}

document.addEventListener('DOMContentLoaded', function() {
    refreshSession();
    setInterval(refreshSession, 60000);

    document.getElementById('checkConfigBtn').addEventListener('click', function() {
        document.getElementById('checkFile').click();
    });
    document.getElementById('checkFile').addEventListener('change', function() {
        var f = this.files[0];
        if (!f) return;
        var fd = new FormData();
        fd.append('file', f);
        window.showLoader();
        fetch('/inventory/check-config', { method: 'POST', body: fd,
            headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(r => r.json()).then(d => {
                window.hideLoader();
                window.safeToast(d.message, d.success ? 'success' : 'error');
            }).catch(function(){ window.hideLoader(); window.safeToast('检查配置失败', 'error'); });
        this.value = '';
    });
    document.getElementById('guideBtn').addEventListener('click', function() {
        new bootstrap.Modal(document.getElementById('guideModal')).show();
    });

    document.getElementById('startQueryBtn').addEventListener('click', function() {
        var p1 = new bootstrap.Modal(document.getElementById('p1Modal'));
        document.getElementById('p1ConfirmBtn').onclick = function() {
            p1.hide();
            doQuery();
        };
        p1.show();
    });
});

function doQuery() {
    var input = document.getElementById('demandFile');
    if (!input.files.length) { window.safeToast('请先选择需求单 Excel 文件', 'warning'); return; }
    if (!loginReady) { window.safeToast(MSG.P4, 'warning'); return; }
    var fd = new FormData();
    fd.append('file', input.files[0]);
    window.showLoader();
    document.getElementById('progressBox').style.display = 'block';
    document.getElementById('queryProgress').style.width = '0%';
    fetch('/inventory/query', { method: 'POST', body: fd,
        headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(r => r.json()).then(d => {
            window.hideLoader();
            document.getElementById('progressBox').style.display = 'none';
            if (d.success) {
                var data = d.data;
                document.getElementById('resultBox').innerHTML =
                    '<div class="alert alert-success">' +
                    '查询完成：共 ' + data.total + ' 件号，成功 ' + data.success +
                    '，失败 ' + data.fail + '，标红 ' + data.shortage + '，标黄 ' + data.warning +
                    '。<br>输出文件：' + data.filename + '</div>';
                window.safeToast(d.message, 'success');
            } else {
                window.safeToast(d.message, 'error');
            }
        }).catch(function(){ window.hideLoader(); window.safeToast('查询失败', 'error'); });
}
</script>
{% endblock %}
```

- [ ] **Step 3: 手动验证页面**

Run: `python src/reqman/app.py` 后访问 `http://127.0.0.1:5001/inventory`。
Expected: 页面渲染三区块，状态卡显示"❌ 系统未登录AMRO"，导航含"库存查询"链接。

- [ ] **Step 4: Commit**

```bash
git add src/reqman/templates/inventory/index.html src/reqman/templates/base.html
git commit -m "feat: 库存查询前端页面（状态/配置/查询三区块+统一文案）"
```

---

### Task 9: 版本升级与文档同步

**Files:**
- Modify: `pyproject.toml`（version → 3.3.0）
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `SERVER_README.md`（如涉及部署说明，最小化）

- [ ] **Step 1: 升级版本号**

`pyproject.toml`：`version = "3.3.0"`。

- [ ] **Step 2: 更新 CHANGELOG**

在顶部新增：
```markdown
## [3.3.0] - Unreleased
### Added
- 库存查询功能：上传需求单 Excel 批量查询川航 AMRO 昆明库存，副本回填 G 列并标红/标黄
- 通用连接器框架（services/connectors/）：AMRO 适配器 + 登录凭证临时缓存（TTL 2h 可配）
- 登录脚本（scripts/）：uv 自举 + 国内高速源（阿里云 PyPI / npmmirror playwright），自动上传登录凭证
- 库存查询页（/inventory）：新建配置 / 检查配置 / 登录状态探活 / 查询进度与结果
- 统一提示文案集（P1–P12）
```

- [ ] **Step 3: 更新 README**

在功能模块表追加"库存查询"条目，简述用法；更新版本号为 3.3.0。

- [ ] **Step 4: 全量验证**

Run:
```
python -m pytest -m "not slow"
python -m pytest -m e2e
ruff check src/ tests/
```
Expected: 全部通过。确认真实 `data/reqman_db.json` 未变（git status 无该文件改动）。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml CHANGELOG.md README.md SERVER_README.md
git commit -m "chore: 版本升级至3.3.0，库存查询功能文档同步"
```

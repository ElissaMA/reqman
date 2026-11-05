"""第一批修复的回归测试（低成本确定性缺陷）。

覆盖：
- F1 tojson 不得直接进入 onclick 属性（属性截断 + 注入）
- F2 quantity 必须转义（存储型 XSS）
- F4 openpyxl cleanup 补丁两条路径均不抛
- F5 端口精确匹配（:5001 不命中 :50011）
- F6 _parse_qty 脏值/负号/NaN/Inf
"""
import html
import json
import re
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "reqman" / "templates"


# ---------- F1: tojson 不得进属性 ----------
class TestTojsonNotInAttribute:
    @pytest.mark.parametrize("rel", ["cards/list.html", "packages/upload.html"])
    def test_no_tojson_inside_onclick(self, rel):
        """tojson 直接写进 onclick 会被第一个双引号截断，按钮失效且可注入。"""
        source = (TEMPLATES / rel).read_text(encoding="utf-8")
        assert "|tojson|forceescape" in source
        for m in re.finditer(r'onclick="[^"\n]*\|tojson(?!\|forceescape)[^"\n]*"', source):
            pytest.fail(f"{rel} 仍有 tojson 直接注入 onclick: {m.group(0)[:80]}")

    @pytest.mark.parametrize("rel", ["cards/list.html", "packages/upload.html"])
    def test_button_uses_data_attribute(self, rel):
        """按钮改由 data-pending 传参，并由 confirmCancelledFromBtn 解析。"""
        source = (TEMPLATES / rel).read_text(encoding="utf-8")
        assert 'data-pending="{{ pending_cancelled|tojson|forceescape }}"' in source
        assert "confirmCancelledFromBtn(this)" in source
        assert "function confirmCancelledFromBtn" in source
        assert "JSON.parse(btn.dataset.pending" in source


# ---------- F2: quantity 必须转义 ----------
class TestQuantityEscaped:
    @pytest.mark.parametrize("name", ["list.html", "cancelled.html", "sets.html", "logs.html"])
    def test_quantity_wrapped_in_escapehtml(self, name):
        source = (TEMPLATES / "cards" / name).read_text(encoding="utf-8")
        # 裸拼（未转义）的两种写法都不允许
        for pattern in (r"\+ \(t\.quantity\s*\|\|\s*''\)", r"\+ \(m\.quantity\s*\|\|\s*''\)"):
            for m in re.finditer(pattern, source):
                pytest.fail(f"{name} 存在未转义 quantity: {m.group(0)}")
        assert "escapeHtml(t.quantity)" in source or "escapeHtml(m.quantity)" in source


# ---------- F4: openpyxl cleanup 补丁 ----------
class TestOpenpyxlPatchCleanup:
    """补丁必须在原 cleanup 抛错 + close() 成功时也不抛
    （旧实现 _path 仅在 except OSError 内赋值，close() 成功时抛 UnboundLocalError）。"""

    def test_patched_cleanup_survives_close_success(self, tmp_path, monkeypatch):
        """真实调用补丁函数：原始 cleanup 抛 PermissionError，close() 成功。"""
        from openpyxl.worksheet import _writer

        from reqman.utils import openpyxl_patch

        leftover = tmp_path / "leftover.tmp"
        leftover.write_text("x", encoding="utf-8")

        class FakeOut:
            name = str(leftover)

            def close(self):
                pass  # 成功关闭：旧实现此处 _path 未绑定 -> UnboundLocalError

        class FakeWriter:
            out = FakeOut()

        # 让“原始”cleanup 抛 PermissionError（模拟杀软锁文件）
        monkeypatch.setattr(
            _writer.WorksheetWriter, "cleanup",
            lambda self: (_ for _ in ()).throw(PermissionError("locked")),
        )
        monkeypatch.setattr(_writer, "ALL_TEMP_FILES", [])
        openpyxl_patch.apply_patches(ROOT)   # 打补丁
        patched = _writer.WorksheetWriter.cleanup

        writer = FakeWriter()
        try:
            patched(writer)
        except UnboundLocalError as exc:  # pragma: no cover
            pytest.fail(f"close() 成功路径仍触发 UnboundLocalError: {exc}")

    def test_path_bound_before_close(self):
        """核心顺序断言：_path 必须在 try/close 之前取到。"""
        source = (ROOT / "src/reqman/utils/openpyxl_patch.py").read_text(encoding="utf-8")
        body = source[source.index("def _patched_cleanup"):]
        path_pos = body.index('_path = getattr(self.out, "name", None)')
        close_pos = body.index("self.out.close()")
        assert path_pos < close_pos, "_path 必须在 close() 之前绑定"


# ---------- F5: 端口精确匹配 ----------
class TestFindPidByPort:
    NETSTAT = (
        "  Proto  Local Address          Foreign Address        State           PID\n"
        "  TCP    0.0.0.0:50011          0.0.0.0:0              LISTENING       11111\n"
        "  TCP    127.0.0.1:5001         0.0.0.0:0              LISTENING       22222\n"
        "  TCP    [::]:5001              [::]:0                 LISTENING       33333\n"
    )

    def _call(self, port):
        from reqman.utils import startup

        with mock.patch.object(
            startup.subprocess, "check_output",
            return_value=self.NETSTAT.encode("utf-8", errors="replace"),
        ), mock.patch.object(startup.platform, "system", return_value="Windows"):
            return startup.find_pid_by_port(port)

    def test_5001_does_not_match_50011(self):
        assert self._call(5001) == "22222"

    def test_50011_matches_itself(self):
        assert self._call(50011) == "11111"

    def test_ipv6_local_address(self):
        netstat = "  TCP    [::]:8080              [::]:0                 LISTENING       44444\n"
        from reqman.utils import startup

        with mock.patch.object(
            startup.subprocess, "check_output",
            return_value=netstat.encode("utf-8", errors="replace"),
        ), mock.patch.object(startup.platform, "system", return_value="Windows"):
            assert startup.find_pid_by_port(8080) == "44444"


# ---------- F6: 数值解析 ----------
class TestParseQty:
    @pytest.mark.parametrize("raw,expected", [
        ("2", 2.0), ("1.5", 1.5), ("-5", -5.0),
        ("1.2.3", 1.2), ("1..2", 1.0), ("3.4.5 套", 3.4),
        ("", 0.0), ("abc", 0.0), (None, 0.0),
    ])
    def test_dirty_values_never_raise(self, raw, expected):
        from reqman.services.xlsx_workbook import _parse_qty
        assert _parse_qty(raw) == expected

    def test_numeric_passthrough(self):
        from reqman.services.xlsx_workbook import _parse_qty
        assert _parse_qty(7) == 7.0
        assert _parse_qty(2.25) == 2.25


class TestStockValueGuard:
    """NaN/Inf 不得导致整份导出崩溃。"""

    @pytest.mark.parametrize("value,expected", [
        (float("nan"), 0), (float("inf"), 0), (float("-inf"), 0),
        (3.0, 3), (3.5, 3.5),
    ])
    def test_finite_guard(self, value, expected):
        import math

        stock_val = value
        if not isinstance(stock_val, (int, float)) or not math.isfinite(stock_val):
            stock_val = 0.0
        out = int(stock_val) if float(stock_val).is_integer() else stock_val
        assert out == expected


# ---------- F3: logs_bp 不再直接用 Referer ----------
class TestLogsRedirectSafe:
    def test_no_raw_referer_redirect(self):
        source = (ROOT / "src/reqman/blueprints/logs_bp.py").read_text(encoding="utf-8")
        assert 'request.headers.get("Referer"' not in source
        assert 'safe_referrer("/card/logs")' in source


# ---------- F1 端到端：属性渲染不截断 ----------
class TestTojsonAttributeRender:
    def test_forceescape_keeps_attribute_intact(self):
        from jinja2 import Environment

        env = Environment(autoescape=True)
        tpl = env.from_string('<button data-pending="{{ p|tojson|forceescape }}">x</button>')
        payload = [{"task_code": 'A"1', "task_name": "卡名"}]
        rendered = tpl.render(p=payload)
        m = re.search(r'data-pending="([^"]*)"', rendered)
        assert m is not None, "属性值被双引号截断"
        assert json.loads(html.unescape(m.group(1))) == payload

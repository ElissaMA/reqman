"""模板字节缓存：独立对象 + mtime 失效"""
import time

import openpyxl

from reqman.utils.template_cache import load_template


def _write(wb_path, value):
    wb = openpyxl.Workbook()
    wb.active["A1"] = value
    wb.save(wb_path)


def test_returns_independent_workbooks(tmp_path):
    p = tmp_path / "t.xlsx"
    _write(p, "v1")
    a = load_template(p)
    b = load_template(p)
    assert a is not b  # 每次返回独立 Workbook 对象
    a.active["A1"] = "mut"
    assert b.active["A1"].value == "v1"  # 互不串改（缓存的是字节，不复用对象）


def test_mtime_invalidation(tmp_path):
    p = tmp_path / "t.xlsx"
    _write(p, "v1")
    assert load_template(p).active["A1"].value == "v1"
    time.sleep(1.1)  # 确保 mtime 前进，触发缓存失效
    _write(p, "v2")
    assert load_template(p).active["A1"].value == "v2"

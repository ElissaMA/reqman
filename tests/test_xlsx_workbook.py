"""需求单 Excel 读写测试（区域识别/回填/标红标黄）"""
import io
from pathlib import Path

import openpyxl

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
        buf, filename = write_inventory_copy(src, results, pn_qty, pn_cells, timestamp_suffix="TEST")
        assert isinstance(buf, io.BytesIO)
        assert "_库存已填_TEST.xlsx" in filename
        wb = openpyxl.load_workbook(buf)
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
        buf, _ = write_inventory_copy(src, results, pn_qty, pn_cells, timestamp_suffix="WARN")
        wb = openpyxl.load_workbook(buf)
        ws = wb.active
        # PN-003 需求 1 库存 2 → 需求<=2<需求+2 → 标黄
        assert ws["B19"].fill.start_color.rgb.endswith(YELLOW)
        wb.close()

    def test_no_stock_fills_zero(self, tmp_path: Path):
        src, pn_cells, pn_qty = self._setup(tmp_path)
        results = {}
        buf, _ = write_inventory_copy(src, results, pn_qty, pn_cells, timestamp_suffix="ZERO")
        wb = openpyxl.load_workbook(buf)
        ws = wb.active
        assert ws["G15"].value == 0
        assert ws["B15"].fill.start_color.rgb.endswith(RED)  # 0 < 需求
        wb.close()

    def test_output_stem_preserves_original_name(self, tmp_path: Path):
        src, pn_cells, pn_qty = self._setup(tmp_path)
        results = {"PN-001": 1.0}
        buf, filename = write_inventory_copy(
            src, results, pn_qty, pn_cells, timestamp_suffix="KEEP", output_stem="原始需求单"
        )
        assert filename == "原始需求单_库存已填_KEEP.xlsx"
        assert buf.getvalue()

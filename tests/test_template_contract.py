"""模板契约快照测试（修复计划阶段0）。

固定区文字/合并/打印区按 assets 真实模板断言；任何生成器写入模板固定区的行为
都会在此被拦截。动态区白名单与结构异常报错行为也在此验证。
"""
import openpyxl
import pytest

from reqman.config import (
    CHECK_TEMPLATE_FILE,
    MATERIALS_TEMPLATE_FILE,
    REMINDER_TEMPLATE_FILE,
    TEMPLATE_FILE,
    TOOLS_TEMPLATE_FILE,
)


def _cell(ws, coord):
    return str(ws[coord].value or "").strip()


def _visible_cells(ws):
    """返回未被合并隐藏的单元格（合并区只保留左上角，Excel 渲染同此语义）。"""
    ranges = list(ws.merged_cells.ranges)
    for row in range(1, ws.max_row + 1):
        for col in range(1, ws.max_column + 1):
            hidden = any(
                r.min_row <= row <= r.max_row and r.min_col <= col <= r.max_col
                and (r.min_row, r.min_col) != (row, col)
                for r in ranges
            )
            if not hidden:
                yield ws.cell(row=row, column=col)


# ---------- 需求单 ----------
class TestDemandContract:
    def test_fixed_cells(self):
        ws = openpyxl.load_workbook(TEMPLATE_FILE)["需求单"]
        assert _cell(ws, "A1").startswith("定检中队定检需求单")
        assert "定检运行条件" in _cell(ws, "A2")
        assert "工装" in _cell(ws, "A13") and "航材需求" in _cell(ws, "A13")
        assert _cell(ws, "A14") == "定检专业\n（工具）"
        assert _cell(ws, "A15") == "发动机工具"      # 区标签带"工具"后缀，生成器不得缩写
        assert _cell(ws, "A18") == "机体工具"
        assert _cell(ws, "A21") == "电子工具"
        assert _cell(ws, "A24") == "本次定检新增工作"
        assert _cell(ws, "B24") == "无"
        assert _cell(ws, "A25") == "定检专业\n（航材）"
        assert _cell(ws, "A35") == "三、备用航材需求(定检中队、MCC负责)"
        assert _cell(ws, "A36") == "专业"

    def test_merges_and_print_area(self):
        ws = openpyxl.load_workbook(TEMPLATE_FILE)["需求单"]
        merges = {str(r) for r in ws.merged_cells.ranges}
        # 模板已收敛为 8 列（删除「区域放行确认」列，备用区删除「调配数量」列）
        for m in ("A1:H1", "A2:H2", "A13:H13", "A35:H35", "B24:H24"):
            assert m in merges, m
        assert ws.max_column == 8
        pa = str(ws.print_area or "").replace("$", "")
        assert pa.endswith("H42"), pa

    def test_font_rules(self):
        """全表字体统一 SimSun；总表头22加粗 / 区域表头16加粗 / 内容14不加粗。"""
        from reqman.services.form_generator import (
            FONT_NAME,
            FONT_SIZE_BODY,
            FONT_SIZE_SECTION,
            FONT_SIZE_TITLE,
        )

        ws = openpyxl.load_workbook(TEMPLATE_FILE)["需求单"]
        visible = _visible_cells(ws)
        names = {c.font.name for c in visible}
        assert names == {FONT_NAME}, names
        assert FONT_SIZE_TITLE == 22 and FONT_SIZE_SECTION == 16 and FONT_SIZE_BODY == 14

        assert ws["A1"].font.sz == FONT_SIZE_TITLE and ws["A1"].font.bold
        for coord in ("A2", "A3", "A13", "A14", "A24", "A25", "A35", "A36"):
            assert ws[coord].font.sz == FONT_SIZE_SECTION and ws[coord].font.bold, coord

        # 内容行：14 号且不加粗（B 列在条件区属 A:B 合并的隐藏部分，A26 等为专业标签）
        for coord in ("A4", "C4", "D4", "G4", "B15", "C15", "B26", "H42"):
            assert ws[coord].font.sz == FONT_SIZE_BODY, coord
            assert not ws[coord].font.bold, coord
        # 专业区标签属区域表头：16 加粗
        for coord in ("A15", "A18", "A21", "A29", "A37", "A39", "A41"):
            assert ws[coord].font.sz == FONT_SIZE_SECTION, coord
            assert ws[coord].font.bold, coord


# ---------- 提醒单 ----------
class TestReminderContract:
    def test_fixed_cells(self):
        ws = openpyxl.load_workbook(REMINDER_TEMPLATE_FILE)["工卡提醒"]
        assert _cell(ws, "A1") == "定检工作提醒单"
        assert _cell(ws, "B2") == "定检级别："      # 标签原文，代码只应追加值
        assert "图例" in _cell(ws, "A5") or "红色字体" in _cell(ws, "A5")
        assert _cell(ws, "A6") == "电子"
        assert _cell(ws, "B6") == "发动机"
        assert _cell(ws, "C6") == "机体"

    def test_capacity(self):
        ws = openpyxl.load_workbook(REMINDER_TEMPLATE_FILE)["工卡提醒"]
        assert ws.max_row >= 5000


# ---------- 工具清单 ----------
class TestToolsContract:
    def test_zones_and_preprinted(self):
        ws = openpyxl.load_workbook(TOOLS_TEMPLATE_FILE)["定检工具"]
        merges = {str(r) for r in ws.merged_cells.ranges}
        for m in ("A1:G1", "A3:A18", "A19:A28", "A29:A38", "A39:A48"):
            assert m in merges, m
        assert _cell(ws, "B3") == "手套"
        assert _cell(ws, "B4") == "毛巾"
        # 区首/末行边框属于模板基线，具体样式允许模板维护者调整；仅确认边框定义存在。
        for first, last in ((19, 28), (29, 38), (39, 48)):
            for col in ("B", "D"):
                assert ws[f"{col}{first}"].border.top.style is not None, f"{col}{first}"
                assert ws[f"{col}{last}"].border.bottom.style is not None, f"{col}{last}"

    def test_no_internal_merges_in_zones(self):
        """区内除 A 标签外无内部合并（_extend_zone 只平移下方合并的假设）。"""
        ws = openpyxl.load_workbook(TOOLS_TEMPLATE_FILE)["定检工具"]
        zones = [(3, 18), (19, 28), (29, 38), (39, 48)]
        for rng in ws.merged_cells.ranges:
            if rng.min_col == 1 and rng.max_col == 1:
                continue   # A 列区标签
            for start, end in zones:
                assert not (start <= rng.min_row and rng.max_row <= end), \
                    f"区内出现内部合并 {rng}"


# ---------- 航化清单 ----------
class TestMaterialsContract:
    def test_zones_and_preprinted(self):
        ws = openpyxl.load_workbook(MATERIALS_TEMPLATE_FILE)["定检航化"]
        merges = {str(r) for r in ws.merged_cells.ranges}
        for m in ("A1:H1", "A3:A11", "A12:A17", "A18:A24"):
            assert m in merges, m
        assert "纸胶带" in _cell(ws, "B3")
        assert _cell(ws, "B12") == "清洗剂"       # 外场预印
        assert "警戒" in _cell(ws, "A25")
        assert _cell(ws, "B26") == "无纺布"
        assert ws["C18"].font.size is not None       # 非例行区字体由模板维护


# ---------- 改版清单 ----------
class TestCheckContract:
    def test_fixed_cells_and_capacity(self):
        ws = openpyxl.load_workbook(CHECK_TEMPLATE_FILE)["改版清单"]
        assert _cell(ws, "A1") == "工卡改版清单"
        merges = {str(r) for r in ws.merged_cells.ranges}
        assert "A1:C1" in merges
        assert (_cell(ws, "A2"), _cell(ws, "B2"), _cell(ws, "C2")) == ("电子", "发动机", "机体")
        assert ws.max_row >= 4996
        assert ws["A3"].fill.fill_type == "solid"   # 数据区预置绿底


# ---------- 生成器对固定区的保护（隔离副本验证行为） ----------
class TestGeneratorRespectsFixedZone:
    def test_zone_label_missing_raises(self, tmp_path, monkeypatch):
        """模板结构异常必须明确报错（区标签被改坏的场景）。"""
        import reqman.services.checklist_generator as cg

        dst = tmp_path / "tools_broken.xlsx"
        wb = openpyxl.load_workbook(TOOLS_TEMPLATE_FILE)
        wb["定检工具"]["A3"] = "通用工具区"   # 改坏区标签
        wb.save(dst)
        monkeypatch.setattr(cg, "TOOLS_TEMPLATE_FILE", dst)
        with pytest.raises(RuntimeError, match="模板结构异常"):
            cg.generate_tool_list(
                {"reg": "B-1234", "description": "T", "date": "2026-09-10"},
                [{"device_name": "扳手", "part_number": "PN", "quantity": "1",
                  "category": "发动机", "usage_type": "必须使用"}])

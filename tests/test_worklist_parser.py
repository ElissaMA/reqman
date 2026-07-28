"""worklist_parser ���元测试

使用 mock 模拟 openpyxl 行为，避免依赖真实 Excel 文件。
"""

from unittest.mock import MagicMock, patch

import pytest

from reqman.services.worklist_parser import (
    WorklistError,
    _parse_aircraft_info,
    _parse_items,
    merge_aircraft_info,
    parse_worklist,
)

# ============================================================
# Helper：创建模拟 Cell
# ============================================================

def _cell(value, column=1):
    """创建一个模拟的 openpyxl Cell 对象"""
    c = MagicMock()
    c.value = value
    c.column = column
    return c


def _make_row(*values):
    """创建一行模拟 Cell 元组（12 列），values 可以是 (value, column) 或 value"""
    cells = []
    for v in values:
        if isinstance(v, tuple):
            cells.append(_cell(v[0], v[1]))
        else:
            cells.append(_cell(v, len(cells) + 1))

    # 补齐到 12 列，其余为空 cell
    while len(cells) < 12:
        cells.append(_cell(None, len(cells) + 1))
    return tuple(cells)


# ============================================================
# Fixtures：模拟工作表
# ============================================================

@pytest.fixture
def ws_empty():
    """空工作表（无数据行，行数不足）"""
    ws = MagicMock()
    ws.max_row = 2
    ws.max_column = 12
    ws.iter_rows.return_value = []
    return ws


@pytest.fixture
def ws_aircraft_only():
    """只有飞机信息（Row 2）没有工卡数据（Row 7 不存在）的工作表"""
    ws = MagicMock()
    ws.max_row = 5  # < 7，无工卡区
    ws.max_column = 12

    # Row 2: 飞机信息
    row2 = _make_row(
        (None, 1),           # A2
        ("B-1234", 2),       # B2 = reg
        (None, 3),           # C2
        ("A320", 4),         # D2 = type
        (None, 5), (None, 6), (None, 7), (None, 8),
        (None, 9), (None, 10), (None, 11), (None, 12),
    )
    # Row 4: 日��
    row4 = _make_row(
        (None, 1), (None, 2),
        ("2026-01-15", 3),   # C4 = date
        (None, 4), (None, 5), (None, 6), (None, 7), (None, 8),
        (None, 9), (None, 10), (None, 11), (None, 12),
    )

    def iter_rows(min_row=None, max_row=None, values_only=False, **_):
        if min_row == 2:
            yield row2
        elif min_row == 4:
            yield row4
        elif min_row == 7:
            return iter([])

    ws.iter_rows.side_effect = iter_rows
    return ws


@pytest.fixture
def ws_with_items():
    """包含飞机信息和工卡数据的工作表"""
    ws = MagicMock()
    ws.max_row = 8
    ws.max_column = 12

    # Row 2: 飞机信息
    row2 = _make_row(
        (None, 1), ("B-5678", 2), (None, 3), ("B737", 4),
        (None, 5), (None, 6), (None, 7), (None, 8),
        (None, 9), (None, 10), (None, 11), (None, 12),
    )
    # Row 4: 日期
    row4 = _make_row(
        (None, 1), (None, 2), ("2026-03-20", 3),
        (None, 4), (None, 5), (None, 6), (None, 7), (None, 8),
        (None, 9), (None, 10), (None, 11), (None, 12),
    )
    # Row 7: 第一个工卡
    row7 = _make_row(
        (None, 1), ("B737-001", 2), (None, 3), (None, 4),
        ("A", 5), ("发动机", 6), (None, 7), ("测试发动机检查", 8),
        (None, 9), (None, 10), (None, 11), ("工具: 扳手", 12),
    )
    # Row 8: 第二个工卡
    row8 = _make_row(
        (None, 1), ("B737-002", 2), (None, 3), (None, 4),
        ("EO分段", 5), ("机身", 6), (None, 7), ("机身蒙皮检查", 8),
        (None, 9), (None, 10), (None, 11), (None, 12),
    )

    def iter_rows(min_row=None, max_row=None, values_only=False, **_):
        if min_row == 2 and max_row == 2:
            yield row2
        elif min_row == 4 and max_row == 4:
            yield row4
        elif min_row == 7:
            yield row7
            yield row8

    ws.iter_rows.side_effect = iter_rows
    return ws


# ============================================================
# parse_worklist 集成测试
# ============================================================

class TestParseWorklist:
    """Excel 解析功能测试"""

    @patch("openpyxl.load_workbook")
    @patch("os.path.getsize")
    def test_parse_success(self, mock_getsize, mock_load, ws_with_items):
        """成功解析工作清单"""
        mock_getsize.return_value = 1024  # 1 KB

        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws_with_items
        mock_load.return_value = wb

        result = parse_worklist("dummy.xlsx")

        assert result["total_count"] == 2
        assert result["aircraft_info"]["reg"] == "B-5678"
        assert result["aircraft_info"]["type"] == "B737"
        assert result["items"][0]["task_code"] == "B737-001"
        assert result["items"][1]["task_code"] == "B737-002"

    @patch("openpyxl.load_workbook")
    @patch("os.path.getsize")
    def test_parse_file_too_large(self, mock_getsize, mock_load):
        """文件过大时应抛出异常"""
        mock_getsize.return_value = 20 * 1024 * 1024  # 20 MB

        with pytest.raises(WorklistError, match="文件过大"):
            parse_worklist("large.xlsx")
        mock_load.assert_not_called()

    @patch("os.path.getsize")
    def test_parse_empty_sheet(self, mock_getsize):
        """空工作表（行数不足）应抛出异常"""
        mock_getsize.return_value = 1024
        ws = MagicMock()
        ws.max_row = 3  # < 7
        ws.max_column = 12

        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws

        with patch("openpyxl.load_workbook", return_value=wb), pytest.raises(WorklistError, match="内容不足"):
            parse_worklist("empty.xlsx")

    @patch("openpyxl.load_workbook")
    @patch("os.path.getsize")
    def test_parse_no_sheets(self, mock_getsize, mock_load):
        """无工作表的 Excel 应抛出异常"""
        mock_getsize.return_value = 1024

        wb = MagicMock()
        wb.sheetnames = []
        mock_load.return_value = wb

        with pytest.raises(WorklistError, match="没有工作表"):
            parse_worklist("nosheets.xlsx")

    @patch("openpyxl.load_workbook")
    @patch("os.path.getsize")
    def test_parse_invalid_file(self, mock_getsize, mock_load):
        """无��打开的文件应抛出异常"""
        mock_getsize.return_value = 1024
        mock_load.side_effect = ValueError("文件损坏")

        with pytest.raises(WorklistError, match="无法打开"):
            parse_worklist("invalid.xlsx")

    @patch("openpyxl.load_workbook")
    @patch("os.path.getsize")
    def test_parse_too_many_rows(self, mock_getsize, mock_load):
        """超过最大行数应抛出异常"""
        mock_getsize.return_value = 1024

        ws = MagicMock()
        ws.max_row = 6000  # 超过 MAX_ROWS
        ws.max_column = 12

        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        mock_load.return_value = wb

        with pytest.raises(WorklistError, match="行数过多"):
            parse_worklist("toolarge.xlsx")

    @patch("openpyxl.load_workbook")
    @patch("os.path.getsize")
    def test_parse_duplicate_codes_dedup(self, mock_getsize, mock_load):
        """重复的工卡���应去重"""
        mock_getsize.return_value = 1024

        ws = MagicMock()
        ws.max_row = 9
        ws.max_column = 12

        # Row 2: 飞机信息
        row2 = _make_row(
            (None, 1), ("B-9999", 2), (None, 3), ("A320", 4),
            (None, 5), (None, 6), (None, 7), (None, 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )
        # Row 7-9: 三个重复编码的工卡
        row7 = _make_row(
            (None, 1), ("DUP-001", 2), (None, 3), (None, 4),
            ("A", 5), ("发动机", 6), (None, 7), ("重复工卡", 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )
        row8 = _make_row(
            (None, 1), ("DUP-001", 2), (None, 3), (None, 4),
            ("A", 5), ("发动机", 6), (None, 7), ("重复工卡", 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )
        row9 = _make_row(
            (None, 1), ("DUP-001", 2), (None, 3), (None, 4),
            ("A", 5), ("发动机", 6), (None, 7), ("重复工卡", 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )

        def iter_rows(min_row=None, max_row=None, values_only=False, **_):
            if min_row == 2:
                yield row2
            elif min_row == 7:
                yield row7
                yield row8
                yield row9

        ws.iter_rows.side_effect = iter_rows

        wb = MagicMock()
        wb.sheetnames = ["Sheet1"]
        wb.active = ws
        mock_load.return_value = wb

        result = parse_worklist("dup.xlsx")
        assert result["total_count"] == 1  # 3行但编码相同，去重后1个


# ============================================================
# _parse_aircraft_info 单元测试
# ============================================================

class TestAircraftInfoExtraction:
    """飞机信息提取功能测试"""

    def test_parse_full_info(self, ws_aircraft_only):
        """提取完整的飞机信息"""
        info = _parse_aircraft_info(ws_aircraft_only)
        assert info["reg"] == "B-1234"
        assert info["type"] == "A320"
        assert info["date"] == "2026.01.15"

    def test_parse_partial_info(self):
        """工作表缺少某些字段时应有默认���"""
        ws = MagicMock()
        ws.max_row = 5
        ws.max_column = 12

        # Row 2: 只有注册号
        row2 = _make_row(
            (None, 1), ("B-5678", 2),  # B2 = reg
            (None, 3), (None, 4), (None, 5), (None, 6), (None, 7), (None, 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )

        def iter_rows(min_row=None, max_row=None, values_only=False, **_):
            if min_row == 2:
                yield row2
            elif min_row == 4:
                row4 = _make_row(
                    (None, 1), (None, 2), (None, 3), (None, 4),
                    (None, 5), (None, 6), (None, 7), (None, 8),
                    (None, 9), (None, 10), (None, 11), (None, 12),
                )
                yield row4

        ws.iter_rows.side_effect = iter_rows

        info = _parse_aircraft_info(ws)
        assert info["reg"] == "B-5678"
        assert info["type"] == ""  # 未提供
        assert info["date"] == ""

    def test_parse_empty_ws(self, ws_empty):
        """空工作表应返回默认值"""
        info = _parse_aircraft_info(ws_empty)
        assert info == {"reg": "", "type": "", "package": "", "description": "", "date": ""}

    def test_parse_date_format(self):
        """日期中的横线应替换为点号"""
        ws = MagicMock()
        ws.max_row = 5
        ws.max_column = 12

        row2 = _make_row(
            (None, 1), ("B-1234", 2), (None, 3), (None, 4),
            (None, 5), (None, 6), (None, 7), (None, 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )
        row4 = _make_row(
            (None, 1), (None, 2), ("2026-12-31 10:00:00", 3),
            (None, 4), (None, 5), (None, 6), (None, 7), (None, 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )

        def iter_rows(min_row=None, max_row=None, values_only=False, **_):
            if min_row == 2:
                yield row2
            elif min_row == 4:
                yield row4

        ws.iter_rows.side_effect = iter_rows

        info = _parse_aircraft_info(ws)
        assert info["date"] == "2026.12.31"

    def test_date_cell_without_slash(self):
        """日期单元格值不包含横线应保持原样"""
        ws = MagicMock()
        ws.max_row = 5
        ws.max_column = 12

        row2 = _make_row((None, 1), ("B-1234", 2))
        row4 = _make_row((None, 1), (None, 2), ("2026.01.15", 3))

        def iter_rows(min_row=None, max_row=None, values_only=False, **_):
            if min_row == 2:
                yield row2
            elif min_row == 4:
                yield row4

        ws.iter_rows.side_effect = iter_rows

        info = _parse_aircraft_info(ws)
        assert info["date"] == "2026.01.15"  # 不需要替换


# ============================================================
# _parse_items 单元测试
# ============================================================

class TestParseItems:
    """工卡列表解析功能测试"""

    def test_parse_items_basic(self, ws_with_items):
        """解析基本的工卡列表"""
        items = _parse_items(ws_with_items, "例行")
        assert len(items) == 2
        assert items[0]["task_code"] == "B737-001"
        assert items[1]["task_code"] == "B737-002"
        assert items[0]["source"] == "例行"

    def test_parse_items_empty(self, ws_empty):
        """没有工卡数据时返回空列表"""
        items = _parse_items(ws_empty, "例行")
        assert items == []

    def test_parse_items_source(self, ws_with_items):
        """source 字段应正确传递 file_type"""
        items = _parse_items(ws_with_items, "非例行")
        assert items[0]["source"] == "非例行"

    def test_parse_items_category_mapping(self, ws_with_items):
        """'机身' 分类应映射为 '机体'"""
        items = _parse_items(ws_with_items, "例行")
        # 第二个工卡的 category 是 "��身"
        card_002 = [i for i in items if i["task_code"] == "B737-002"]
        if card_002:
            assert card_002[0]["category"] in ("机体", "机身")

    def test_parse_items_remark(self, ws_with_items):
        """备注应被正确解析"""
        items = _parse_items(ws_with_items, "例行")
        card_001 = [i for i in items if i["task_code"] == "B737-001"]
        if card_001:
            assert card_001[0].get("remark") == "工具: 扳手"

    def test_parse_items_empty_row_skipped(self):
        """空行（无工卡号）应跳过"""
        ws = MagicMock()
        ws.max_row = 8
        ws.max_column = 12

        # Row 7: 空行
        row7 = _make_row(
            (None, 1), (None, 2),
        )
        # Row 8: 有效工卡
        row8 = _make_row(
            (None, 1), ("VALID-001", 2), (None, 3), (None, 4),
            ("A", 5), ("发动机", 6), (None, 7), ("有效工卡", 8),
            (None, 9), (None, 10), (None, 11), (None, 12),
        )

        def iter_rows(min_row=None, max_row=None, values_only=False, **_):
            if min_row == 7:
                yield row7
                yield row8

        ws.iter_rows.side_effect = iter_rows
        items = _parse_items(ws, "例行")
        assert len(items) == 1
        assert items[0]["task_code"] == "VALID-001"


# ============================================================
# merge_aircraft_info 单元测试
# ============================================================

class TestMergeAircraftInfo:
    """飞机信息合并功能测试"""

    def test_merge_multiple(self):
        """合并多个飞机信息，优先使用非空值"""
        info1 = {"reg": "B-1234", "type": "", "package": "", "description": "", "date": "2026.01.01"}
        info2 = {"reg": "", "type": "A320", "package": "", "description": "", "date": ""}
        merged = merge_aircraft_info([info1, info2])
        assert merged["reg"] == "B-1234"
        assert merged["type"] == "A320"
        assert merged["date"] == "2026.01.01"

    def test_merge_single(self):
        """合并单个信息"""
        info = {"reg": "B-1234", "type": "A320", "package": "PKG-001",
                "description": "测试", "date": "2026.01.01"}
        merged = merge_aircraft_info([info])
        assert merged == info

    def test_merge_empty_list(self):
        """空列表应返回空字典"""
        merged = merge_aircraft_info([])
        assert merged == {"reg": "", "type": "", "package": "",
                          "description": "", "date": ""}

    def test_merge_conflict(self):
        """冲突字段应保留第一个非空值"""
        info1 = {"reg": "B-1111", "type": "A320", "package": "", "description": "", "date": ""}
        info2 = {"reg": "B-2222", "type": "B737", "package": "", "description": "", "date": ""}
        merged = merge_aircraft_info([info1, info2])
        assert merged["reg"] == "B-1111"
        assert merged["type"] == "A320"

    def test_merge_skips_none(self):
        """包含 None 的输入应被跳过"""
        merged = merge_aircraft_info([None, {"reg": "B-1234", "type": "A320"}])
        assert merged["reg"] == "B-1234"
        assert merged["type"] == "A320"

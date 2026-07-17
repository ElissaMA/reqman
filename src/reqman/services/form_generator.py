# -*- coding: utf-8 -*-


from __future__ import annotations

import io
import os
import logging
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from ..config import TEMPLATE_FILE

logger = logging.getLogger(__name__)




def _discover_formula_map(ws, min_row=15, max_col=9):
    """扫描模板数据区，建立 (row, col) -> formula 的映射。"""
    formula_map = {}
    for row in range(min_row, ws.max_row + 1):
        for col in range(1, max_col + 1):
            cell = ws.cell(row, col)
            if cell.value and str(cell.value).startswith('='):
                formula_map[(row, col)] = cell.value
    return formula_map


def _save_formulas(ws, formula_map, max_row=None):
    """从工作表保存公式到映射（反向操作：读取当前 ws 中的公式覆盖映射）。"""
    if max_row is None:
        max_row = ws.max_row
    for row in range(1, max_row + 1):
        for col in range(1, 10):
            cell = ws.cell(row, col)
            if cell.value and str(cell.value).startswith('='):
                formula_map[(row, col)] = cell.value


def _restore_formulas(ws, formula_map, max_row=None):
    """将保存的公式写回工作表中对应单元格。"""
    if max_row is None:
        max_row = ws.max_row
    for (row, col), formula in formula_map.items():
        if row <= max_row:
            ws.cell(row, col).value = formula

THIN = Side(style="thin")
MEDIUM = Side(style="medium")
FULL_THIN = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FULL_MEDIUM = Border(left=MEDIUM, right=MEDIUM, top=MEDIUM, bottom=MEDIUM)
NO_BORDER = Border()
BOLD_16 = Font(name="SimSun", size=16, bold=True)
BOLD_14 = Font(name="SimSun", size=14, bold=True)
DATA_14 = Font(name="SimSun", size=14)
BOLD_12 = Font(name="SimSun", size=12, bold=True)
BOLD_22 = Font(name="SimSun", size=22, bold=True)
WRAP_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
WRAP_VERTICAL = Alignment(vertical="center", wrap_text=True)
LEFT_CENTER = Alignment(horizontal="left", vertical="center")
DATA_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
COLS = 9
ROW_HEIGHT_DATA = 34
CATEGORY_ORDER = {
    0: "发动机",
    1: "机体",
    2: "电子",
}


def set_border(ws, row, col, border=FULL_THIN):
    ws.cell(row=row, column=col).border = border


def set_cell(ws, row, col, value="", border=FULL_THIN, alignment=WRAP_VERTICAL, font=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.border = border
    cell.alignment = alignment
    if font:
        cell.font = font
    return cell


def write_placeholder(ws, row, cat, text="（暂无）"):
    set_cell(ws, row, 1, cat)
    set_cell(ws, row, 2, text)
    for col in range(3, COLS + 1):
        ws.cell(row=row, column=col).border = FULL_THIN
    ws.row_dimensions[row].height = ROW_HEIGHT_DATA



def _write_category_block_min_rows(ws, start_row, items, min_rows,
                                   name_key, task_key,
                                   merge_h_col=True, formula_cols=None):
    """Write data rows grouped by category, padded to min_rows.
    
    - Items with usage_type "检查有问题领用" get remark annotation.
    - A-column (category label) and H-column are merged within each group.
    - Returns the next available row.
    """
    grouped = {}
    for item in items:
        grouped.setdefault(item.get("category", "电子"), []).append(item)
    
    row = start_row
    for cat in ["发动机", "机体", "电子"]:
        cat_items = grouped.get(cat, [])
        cat_start = row
        
        if not cat_items:
            set_cell(ws, row, 1, cat)
            set_cell(ws, row, 2, "（暂无）")
            for bc in range(3, COLS + 1):
                set_border(ws, row, bc)
            ws.row_dimensions[row].height = ROW_HEIGHT_DATA
            row += 1
            while row - cat_start < min_rows:
                for bc in range(2, COLS + 1):
                    if formula_cols and bc in formula_cols:
                        set_border(ws, row, bc)
                    else:
                        set_cell(ws, row, bc, font=DATA_14, alignment=DATA_ALIGN_CENTER)
                ws.row_dimensions[row].height = ROW_HEIGHT_DATA
                row += 1
        else:
            for item in cat_items:
                remark = item.get("remark", "")
                if item.get("usage_type") == "检查有问题领用":
                    remark = "检查有问题领用" + ("; " + remark if remark else "")

                set_cell(ws, row, 1, cat, font=DATA_14, alignment=DATA_ALIGN_CENTER)
                set_cell(ws, row, 2, item.get(name_key, ""), font=DATA_14, alignment=DATA_ALIGN_CENTER)
                set_cell(ws, row, 3, item.get("part_number", ""), font=DATA_14, alignment=DATA_ALIGN_CENTER)
                set_cell(ws, row, 4, item.get(task_key, ""), font=DATA_14, alignment=DATA_ALIGN_CENTER)
                set_cell(ws, row, 5, item.get("quantity", "1"), font=DATA_14, alignment=DATA_ALIGN_CENTER)
                set_cell(ws, row, 6, remark, font=DATA_14, alignment=DATA_ALIGN_CENTER)
                # 跳过公式列（如 I 列的 MCC 调配反馈），仅补边框
                for bc in range(7, COLS + 1):
                    if formula_cols and bc in formula_cols:
                        # 公式列：保留公式，只补边框
                        set_border(ws, row, bc)
                    else:
                        set_cell(ws, row, bc, font=DATA_14, alignment=DATA_ALIGN_CENTER)
                ws.row_dimensions[row].height = ROW_HEIGHT_DATA
                row += 1
            
            while row - cat_start < min_rows:
                for bc in range(2, COLS + 1):
                    if formula_cols and bc in formula_cols:
                        set_border(ws, row, bc)
                    else:
                        set_cell(ws, row, bc, font=DATA_14, alignment=DATA_ALIGN_CENTER)
                ws.row_dimensions[row].height = ROW_HEIGHT_DATA
                row += 1
        
        if row - cat_start > 1:
            ws.merge_cells(start_row=cat_start, start_column=1,
                          end_row=row - 1, end_column=1)
            if merge_h_col:
                ws.merge_cells(start_row=cat_start, start_column=8,
                              end_row=row - 1, end_column=8)
    return row



def generate_form(form_data, parsed_data, output_filename=None):
    """生成需求单 Excel，返回 (BytesIO, filename) 元组 — 不落盘。"""
    if not output_filename:
        reg = form_data.get("reg", "XXXX")
        # Strip B- prefix if present
        if reg.startswith("B-"):
            reg = reg[2:]
        date_str = form_data.get("date", datetime.now().strftime("%Y.%m.%d"))
        desc = form_data.get("description", "")
        output_filename = f"定检需求单（B-{reg} {desc}）{date_str}.xlsx"

    if not os.path.exists(TEMPLATE_FILE):
        raise FileNotFoundError(f"模板文件不存在：{TEMPLATE_FILE}")

    wb = openpyxl.load_workbook(TEMPLATE_FILE)
    ws = wb["需求单"]
    try:
        # 发现模板中的公式
        formula_map = _discover_formula_map(ws)
        # 公式所在的列（用于写数据时跳过）
        formula_cols = set(col for (_, col) in formula_map.keys())

        _fill_header(ws, form_data)
        _fill_conditions(ws, form_data.get("conditions", []))
        _clear_data_area(ws, formula_map)
        matched_tools = parsed_data.get("matched_tools", [])
        matched_materials = parsed_data.get("matched_materials", [])
        spare_auto = parsed_data.get("spare_auto", [])
        new_cards = parsed_data.get("new_cards", [])
        sub_cards = parsed_data.get("sub_cards", [])
        spare_manual = form_data.get("spare_items", [])
        row = 15
        row = _write_tool_section(ws, row, matched_tools, formula_cols=formula_cols)
        row = _write_new_work_row(ws, row, new_cards, sub_cards)
        row = _write_material_section(ws, row, matched_materials, formula_cols=formula_cols)
        last_row = _write_spare_section(ws, row, spare_auto, spare_manual, formula_cols=formula_cols)
        _clear_rows_below(ws, last_row, formula_map)
    finally:
        buffer = io.BytesIO()
        wb.save(buffer)
        wb.close()
        buffer.seek(0)

    return buffer, output_filename

def _fill_header(ws, form_data):
    date_str = form_data.get("date", datetime.now().strftime("%Y.%m.%d"))
    reg = form_data.get("reg", "B-XXXX")
    desc = form_data.get("description", "XXA")
    ws["A1"].value = f"机务二队定检需求单（ {date_str}）"
    ws["A1"].value += "\n"
    ws["A1"].value += f"（{reg} {desc}）"
    ws["A1"].font = BOLD_22
    ws["A1"].alignment = WRAP_CENTER
    for c in range(1, COLS + 1):
        ws.cell(row=1, column=c).border = FULL_MEDIUM
    ws.cell(row=2, column=1).border = Border(left=MEDIUM, right=THIN, top=MEDIUM, bottom=MEDIUM)
    ws.cell(row=2, column=COLS).border = Border(left=THIN, right=MEDIUM, top=MEDIUM, bottom=MEDIUM)
    for c in range(2, COLS):
        ws.cell(row=2, column=c).border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
    for c in range(1, COLS + 1):
        cell = ws.cell(row=2, column=c)
        cell.font = BOLD_16
        cell.alignment = LEFT_CENTER
    for c in range(1, COLS + 1):
        cell = ws.cell(row=3, column=c)
        b = cell.border
        cell.border = Border(left=b.left, right=b.right, top=THIN, bottom=b.bottom)
        cell.font = BOLD_16
        cell.alignment = WRAP_CENTER


def _fill_conditions(ws, conditions):
    for i, cond in enumerate(conditions):
        row = 4 + i
        if row > 12:
            break
        ws.cell(row=row, column=3, value=cond.get("requirement", ""))
        ws.cell(row=row, column=4, value=cond.get("remark", ""))
        ws.cell(row=row, column=7, value=cond.get("responsible", ""))


def _clear_data_area(ws, formula_map=None):
    """清除第15行起的数据区，但保留公式列。"""
    if formula_map is None:
        formula_map = {}
    # 发现模板中已有公式
    _save_formulas(ws, formula_map)
    for mr in list(ws.merged_cells.ranges):
        if mr.min_row >= 15:
            ws.unmerge_cells(str(mr))
    for row in ws.iter_rows(min_row=15, max_row=ws.max_row, max_col=COLS):
        for cell in row:
            key = (cell.row, cell.column)
            if key in formula_map:
                # 保留公式，仅重置样式
                cell.border = NO_BORDER
                cell.font = Font()
                cell.alignment = Alignment()
            else:
                try:
                    cell.value = None
                except AttributeError:
                    pass
                cell.border = NO_BORDER
                cell.font = Font()
                cell.alignment = Alignment()
    _restore_formulas(ws, formula_map)


def _clear_rows_below(ws, start_row, formula_map=None):
    """清除 start_row 起的数据，保留公式。"""
    if formula_map is None:
        formula_map = {}
    _save_formulas(ws, formula_map)
    for mr in list(ws.merged_cells.ranges):
        if mr.min_row >= start_row:
            ws.unmerge_cells(str(mr))
    for row in ws.iter_rows(min_row=start_row, max_row=ws.max_row, max_col=COLS):
        for cell in row:
            key = (cell.row, cell.column)
            if key in formula_map:
                cell.border = NO_BORDER
                cell.font = Font()
                cell.alignment = Alignment()
                cell.fill = PatternFill()
            else:
                try:
                    cell.value = None
                except AttributeError:
                    pass
                cell.border = NO_BORDER
                cell.font = Font()
                cell.alignment = Alignment()
                cell.fill = PatternFill()
    _restore_formulas(ws, formula_map)


def _write_tool_section(ws, start_row, tools, formula_cols=None):
    """All tools go here (both must-use and check-use). Min 3 rows per category.
    Tools with usage_type "检查有问题领用" get remark annotation.
    Calls the shared category block helper."""
    return _write_category_block_min_rows(ws, start_row, tools, 3,
        name_key="device_name", task_key="task_name",
        formula_cols=formula_cols)


def _write_new_work_row(ws, start_row, new_cards, sub_cards=None):
    row = start_row
    set_cell(ws, row, 1, "本次定检新增工作", FULL_MEDIUM, alignment=WRAP_CENTER)
    ws.cell(row=row, column=1).font = BOLD_16
    texts = []
    if sub_cards:
        for c in sub_cards:
            texts.append("%s %s（工卡组子卡）" % (c.get("task_code",""), c.get("task_name","")))
    if new_cards:
        for c in new_cards:
            texts.append("%s %s（未匹配）" % (c.get("task_code",""), c.get("task_name","")))
    if texts:
        set_cell(ws, row, 2, "; ".join(texts), FULL_MEDIUM, alignment=WRAP_VERTICAL)
        ws.cell(row=row, column=2).font = Font(name="SimSun", size=16, bold=True, color="FF0000")
    else:
        set_cell(ws, row, 2, "无", FULL_MEDIUM, alignment=WRAP_CENTER)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=COLS)
    for c in range(3, COLS):
        ws.cell(row=row, column=c).border = FULL_MEDIUM
    ws.row_dimensions[row].height = 48
    return row + 1


def _write_material_section(ws, start_row, materials, formula_cols=None):
    """"必须使用" materials only. Min 3 rows per category."""
    # Header row
    headers = ["定检专业\n（航材）", "航材名称",
               "件号", "工作名称",
               "数量", "备注",
               "库存情况（库存不足需标红底色）",
               "区域放行确认",
               "MCC调配反馈（只调配库存为红色项目）"]
    for i, t in enumerate(headers):
        cell = ws.cell(row=start_row, column=i + 1, value=t)
        cell.font = BOLD_16
        cell.alignment = WRAP_CENTER
        cell.border = FULL_MEDIUM
    ws.row_dimensions[start_row].height = 47
    # Data rows via helper
    return _write_category_block_min_rows(ws, start_row + 1, materials, 3,
        name_key="material_name", task_key="task_name",
        formula_cols=formula_cols)


def _write_spare_section(ws, start_row, spare_auto, spare_manual, formula_cols=None):
    """"检查有问题领用" materials go here. Min 1 row per category."""
    # Section title
    cell = ws.cell(row=start_row, column=1,
                   value="三、备用航材需求(机务二队、MCC负责)")
    cell.font = BOLD_16
    cell.alignment = Alignment(vertical="center")
    for c in range(1, COLS + 1):
        ws.cell(row=start_row, column=c).border = FULL_MEDIUM
        ws.cell(row=start_row, column=c).font = BOLD_16
    ws.merge_cells(start_row=start_row, start_column=1,
                  end_row=start_row, end_column=COLS)
    ws.row_dimensions[start_row].height = 26
    # Header row: "备件" + column headers
    hr = start_row + 1
    for c in range(1, COLS + 1):
        set_cell(ws, hr, c, border=FULL_THIN,
                alignment=Alignment(vertical="center"))
    ws.cell(row=hr, column=1).value = "备件"
    ws.cell(row=hr, column=1).font = BOLD_16
    ws.cell(row=hr, column=1).alignment = WRAP_CENTER
    col_headers = ["", "航材名称", "件号",
                   "工作名称", "数量", "备注",
                   "库存情况（库存不足需标红底色）",
                   "调配数量", "MCC调配情况反馈"]
    for i in range(1, COLS):
        cell = ws.cell(row=hr, column=i + 1)
        cell.value = col_headers[i]
        cell.font = BOLD_16
        cell.alignment = WRAP_CENTER
        cell.border = FULL_THIN
    # Data rows via helper: merge_h_col=False（备用区不再合并调配数量列）
    data_start = hr + 1
    return _write_category_block_min_rows(ws, data_start, spare_auto, 1,
        name_key="material_name", task_key="task_name",
        merge_h_col=False, formula_cols=formula_cols)

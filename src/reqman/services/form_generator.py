

from __future__ import annotations

import io
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from ..config import TEMPLATE_FILE
from ..utils.template_cache import load_template

logger = logging.getLogger(__name__)




THIN = Side(style="thin")
MEDIUM = Side(style="medium")
FULL_THIN = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FULL_MEDIUM = Border(left=MEDIUM, right=MEDIUM, top=MEDIUM, bottom=MEDIUM)
NO_BORDER = Border()
WRAP_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
WRAP_VERTICAL = Alignment(vertical="center", wrap_text=True)
LEFT_CENTER = Alignment(horizontal="left", vertical="center")
COLS = 9
ROW_HEIGHT_DATA = 34
SHEET_NAME = "需求单"
# 模板固定锚点（契约见 tests/test_template_contract.py）
ANCHOR_TOOL_HEADER = "定检专业\n（工具）"
ANCHOR_MAT_HEADER = "定检专业\n（航材）"
ANCHOR_NEW_WORK = "本次定检新增工作"
ANCHOR_SPARE_TITLE_PREFIX = "三、备用航材需求"
PLACEHOLDER_EMPTY = "（暂无）"
# 条件区数据行范围（模板 A3 表头之下、A13 区标题之前）
CONDITION_FIRST_ROW = 4
CONDITION_LAST_ROW = 12


def set_border(ws, row, col, border=FULL_THIN):
    ws.cell(row=row, column=col).border = border


def set_cell(ws, row, col, value="", border=FULL_THIN, alignment=WRAP_VERTICAL, font=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.border = border
    cell.alignment = alignment
    if font:
        cell.font = font
    return cell


def _copy_style(src, dst):
    """复制模板单元格样式（字体/边框/填充/对齐/数字格式），供动态行继承。"""
    dst.font = src.font.copy()
    dst.border = src.border.copy()
    dst.fill = src.fill.copy()
    dst.alignment = src.alignment.copy()
    dst.number_format = src.number_format


def _find_row_by_text(ws, text, col=1, start=1, end=None) -> int | None:
    """按 A 列文字前缀查找锚点行（模板结构变化的容错定位）。"""
    end = end or ws.max_row
    for row in range(start, end + 1):
        if str(ws.cell(row=row, column=col).value or "").strip().startswith(text):
            return row
    return None


def _first_data_row_in_section(ws, anchor_row, col=1):
    """区标题行的下一行即第一个数据行（表头行本身由模板保留）。"""
    return anchor_row + 1


def write_placeholder(ws, row, cat, text=PLACEHOLDER_EMPTY):
    set_cell(ws, row, 1, cat)
    set_cell(ws, row, 2, text)
    for col in range(3, COLS + 1):
        ws.cell(row=row, column=col).border = FULL_THIN
    ws.row_dimensions[row].height = ROW_HEIGHT_DATA



def _pad_empty_rows(ws, row, cat_start, min_rows, style_ref=None):
    while row - cat_start < min_rows:
        for bc in range(2, COLS + 1):
            if style_ref is not None:
                _copy_style(style_ref, ws.cell(row=row, column=bc))
            else:
                set_cell(ws, row, bc, font=None, alignment=DATA_ALIGN_CENTER_DEFAULT())
        ws.row_dimensions[row].height = ROW_HEIGHT_DATA
        row += 1
    return row


def DATA_ALIGN_CENTER_DEFAULT():
    return Alignment(horizontal="center", vertical="center", wrap_text=True)


def _insert_rows_preserve(ws, row: int, amount: int, style_ref_row: int | None = None):
    """在固定锚点前插行，并手动平移合并、行高和样式。"""
    if amount <= 0:
        return
    ranges = list(ws.merged_cells.ranges)
    for rng in ranges:
        ws.unmerge_cells(str(rng))
    heights = {
        r: ws.row_dimensions[r].height
        for r in range(row, ws.max_row + 1)
        if ws.row_dimensions[r].height is not None
    }
    source_row = style_ref_row
    if source_row is not None and source_row >= row:
        source_row += amount
    ws.insert_rows(row, amount)
    for r, height in heights.items():
        ws.row_dimensions[r + amount].height = height
    if source_row is not None:
        for new_row in range(row, row + amount):
            for col in range(1, ws.max_column + 1):
                _copy_style(ws.cell(row=source_row, column=col),
                            ws.cell(row=new_row, column=col))
            ws.row_dimensions[new_row].height = ws.row_dimensions[source_row].height
    for rng in ranges:
        min_row = rng.min_row + amount if rng.min_row >= row else rng.min_row
        max_row = rng.max_row + amount if rng.max_row >= row else rng.max_row
        ws.merge_cells(start_row=min_row, start_column=rng.min_col,
                       end_row=max_row, end_column=rng.max_col)


def _ensure_block_capacity(ws, row: int, needed: int, anchor_text: str,
                           style_ref_row: int | None = None) -> None:
    """确保动态块在下一个固定锚点前有足够行。"""
    anchor = _find_row_by_text(ws, anchor_text, start=row)
    if anchor is None:
        raise RuntimeError(f"需求单模板结构异常：未找到锚点“{anchor_text}”")
    extra = row + needed - anchor
    if extra > 0:
        _insert_rows_preserve(ws, anchor, extra, style_ref_row or anchor - 1)


def _category_row_count(items: list[dict], min_rows: int) -> int:
    """按发动机/机体/电子三专业计算动态块需要的行数。"""
    counts = {cat: 0 for cat in ("发动机", "机体", "电子")}
    for item in items:
        if item.get("category") in counts:
            counts[item["category"]] += 1
    return sum(max(count, min_rows) for count in counts.values())



def _write_category_block_min_rows(ws, start_row, items, min_rows,
                                   name_key, task_key,
                                   merge_h_col=True, style_ref=None,
                                   cat_labels=None, next_anchor_text=None,
                                   style_ref_row=None):
    """Write data rows grouped by category, padded to min_rows.

    - Items with usage_type "检查有问题领用" get remark annotation.
    - A-column (category label) and H-column are merged within each group.
    - 动态单元格样式复制模板参考行（style_ref），不再强制统一字体/边框。
    - cat_labels: {专业: 模板原标签}（如 发动机→发动机工具）；给出时 A 列写模板标签原文。
    - Returns the next available row.
    """
    grouped = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)

    row = start_row
    for cat in ["发动机", "机体", "电子"]:
        cat_items = grouped.get(cat, [])
        cat_start = row
        a_label = (cat_labels or {}).get(cat, cat)

        if not cat_items:
            set_cell(ws, row, 1, a_label)
            set_cell(ws, row, 2, PLACEHOLDER_EMPTY)
            for bc in range(3, COLS + 1):
                set_border(ws, row, bc)
            ws.row_dimensions[row].height = ROW_HEIGHT_DATA
            row += 1
            row = _pad_empty_rows(ws, row, cat_start, min_rows, style_ref)
        else:
            for item in cat_items:
                remark = item.get("remark", "")
                if item.get("usage_type") == "检查有问题领用":
                    remark = "检查有问题领用" + ("，" + remark if remark else "")

                values = [a_label, item.get(name_key, ""), item.get("part_number", ""),
                          item.get("set_name", "") or item.get(task_key, ""),
                          item.get("quantity", ""), remark]
                for col, value in enumerate(values, start=1):
                    cell = ws.cell(row=row, column=col, value=value)
                    if style_ref is not None:
                        _copy_style(style_ref, cell)
                    else:
                        cell.border = FULL_THIN
                        cell.alignment = WRAP_CENTER
                for bc in range(7, COLS + 1):
                    cell = ws.cell(row=row, column=bc)
                    if style_ref is not None:
                        _copy_style(style_ref, cell)
                    else:
                        cell.border = FULL_THIN
                        cell.alignment = WRAP_CENTER
                ws.row_dimensions[row].height = ROW_HEIGHT_DATA
                row += 1
            row = _pad_empty_rows(ws, row, cat_start, min_rows, style_ref)

        if row - cat_start > 1:
            ws.merge_cells(start_row=cat_start, start_column=1,
                          end_row=row - 1, end_column=1)
            if merge_h_col:
                ws.merge_cells(start_row=cat_start, start_column=8,
                              end_row=row - 1, end_column=8)
    return row



def generate_form(form_data, parsed_data, output_filename=None):
    """生成需求单 Excel，返回 (BytesIO, filename) 元组 — 不落盘。

    模板固定区（标题/条件表/区标签/表头/锚点文字）原样保留；
    生成器只写动态数据单元格，并按实际末行更新打印范围。
    """
    if not output_filename:
        reg = form_data.get("reg", "XXXX")
        # Strip B- prefix if present
        reg = reg.removeprefix("B-")
        date_str = form_data.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
        desc = form_data.get("description", "")
        output_filename = f"定检需求单（B-{reg} {desc}）{date_str}.xlsx"

    if not os.path.exists(TEMPLATE_FILE):
        raise FileNotFoundError(f"模板文件不存在：{TEMPLATE_FILE}")

    wb = load_template(TEMPLATE_FILE)
    ws = wb[SHEET_NAME]
    try:
        _fill_header(ws, form_data)
        _fill_conditions(ws, form_data.get("conditions", []))
        matched_tools = parsed_data.get("matched_tools", [])
        matched_materials = parsed_data.get("matched_materials", [])
        spare_auto = parsed_data.get("spare_auto", [])
        new_cards = parsed_data.get("new_cards", [])
        sub_cards = parsed_data.get("sub_cards", [])
        # 先给超出模板预留区的动态块让位，固定锚点随行插入平移。
        # 先给超出模板预留区的动态块让位，固定锚点随行插入平移。
        tool_start = _anchor_tool_data_start(ws)
        tool_rows = _category_row_count(matched_tools, 3)
        _ensure_block_capacity(ws, tool_start, tool_rows, ANCHOR_NEW_WORK,
                               style_ref_row=tool_start)
        mat_header = _find_row_by_text(ws, ANCHOR_MAT_HEADER, start=tool_start)
        spare_title = _find_row_by_text(ws, ANCHOR_SPARE_TITLE_PREFIX, start=tool_start)
        if mat_header is None or spare_title is None:
            raise RuntimeError("需求单模板结构异常：未找到航材区/备用区锚点")
        mat_rows = _category_row_count(matched_materials, 3)
        _ensure_block_capacity(ws, mat_header + 1, mat_rows, ANCHOR_SPARE_TITLE_PREFIX,
                               style_ref_row=mat_header + 1)
        # 读取平移后的模板区标签，再清动态值和可重建合并。
        tool_start = _anchor_tool_data_start(ws)
        cat_labels = _read_tool_zone_labels(ws, tool_start)
        _clear_dynamic_area(ws)
        tool_start = _anchor_tool_data_start(ws)
        _write_tool_section(ws, tool_start, matched_tools, cat_labels)
        new_work_row = _find_row_by_text(ws, ANCHOR_NEW_WORK, start=tool_start)
        if new_work_row is None:
            raise RuntimeError("需求单模板结构异常：未找到新增工作锚点")
        _write_new_work_row(ws, new_work_row, new_cards, sub_cards)
        mat_header = _find_row_by_text(ws, ANCHOR_MAT_HEADER, start=new_work_row)
        if mat_header is None:
            raise RuntimeError("需求单模板结构异常：未找到航材表头锚点")
        _write_material_section(ws, mat_header, matched_materials)
        spare_title = _find_row_by_text(ws, ANCHOR_SPARE_TITLE_PREFIX, start=mat_header)
        if spare_title is None:
            raise RuntimeError("需求单模板结构异常：未找到备用航材标题锚点")
        last_row = _write_spare_section(ws, spare_title, spare_auto,
                                        form_data.get("spare_items", []))
        _clear_rows_below(ws, last_row)
        _update_print_area(ws, last_row)
    finally:
        buffer = io.BytesIO()
        wb.save(buffer)
        wb.close()
        buffer.seek(0)

    return buffer, output_filename


def _fill_header(ws, form_data):
    """A1 标题模板驱动：读取模板原文，只替换日期/机号/描述占位。

    模板 A1 原文形如“定检中队定检需求单（XXXX.XX.XX）\\n（B-XXXX XXA）”；
    队名与标题主体来自模板，仅占位段被替换。行 1-3 样式不再重建。
    """
    date_str = form_data.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    reg = str(form_data.get("reg", "B-XXXX")).removeprefix("B-")
    desc = form_data.get("description", "XXA")

    template_title = str(ws["A1"].value or "")
    lines = template_title.split("\n")
    # 行1：队名+标题主体保留，仅替换括号内日期占位
    first = re.sub(r"（[^）]*）", f"（ {date_str}）", lines[0], count=1) \
        if "XXXX" in lines[0] else re.sub(r"（[^）]*）$", f"（ {date_str}）", lines[0], count=1)
    # 行2：机号/描述占位整段替换
    second = f"（B-{reg} {desc}）" if len(lines) > 1 else ""
    ws["A1"].value = "\n".join([first] + ([second] if second else []))


def _fill_conditions(ws, conditions):
    """条件区 C/D/G 是动态白名单单元格（表单值覆盖为设计行为）。"""
    for i, cond in enumerate(conditions):
        row = CONDITION_FIRST_ROW + i
        if row > CONDITION_LAST_ROW:
            break
        ws.cell(row=row, column=3, value=cond.get("requirement", ""))
        ws.cell(row=row, column=4, value=cond.get("remark", ""))
        ws.cell(row=row, column=7, value=cond.get("responsible", ""))


def _clear_dynamic_cells(ws, row_start: int, row_end: int):
    """只清动态数据单元格的值，保留模板样式/合并。"""
    for row in ws.iter_rows(min_row=row_start, max_row=row_end, max_col=COLS):
        for cell in row:
            try:
                cell.value = None
            except AttributeError:
                pass


def _clear_dynamic_area(ws):
    """清除动态数据区的值（样式保留）；区标签由调用方预先读取并在写入时恢复。"""
    tool_header = _find_row_by_text(ws, ANCHOR_TOOL_HEADER, start=13)
    new_work = _find_row_by_text(ws, ANCHOR_NEW_WORK, start=20)
    spare_title = _find_row_by_text(ws, ANCHOR_SPARE_TITLE_PREFIX, start=30)
    if tool_header is None or spare_title is None:
        raise RuntimeError(
            "需求单模板结构异常：未找到工具/备用航材区锚点（定检专业（工具）/三、备用航材需求）。"
            "请检查模板固定文字是否被改动。")
    mat_header = _find_row_by_text(ws, ANCHOR_MAT_HEADER, start=tool_header + 1)
    if mat_header is None:
        raise RuntimeError("需求单模板结构异常：未找到航材区锚点")
    # 解除动态区内所有可重建合并（包括 A/H 专业块、B24:I24）；保留固定标题/表头合并。
    for mr in list(ws.merged_cells.ranges):
        if mr.min_row >= tool_header + 1 and mr.min_row not in {
                tool_header, mat_header, new_work or -1, spare_title, spare_title + 1}:
            ws.unmerge_cells(str(mr))
    # 清值但保护固定标签/表头/标题行；样式保留，动态写入时复制参考行。
    protected = {tool_header, mat_header}
    if new_work:
        protected.add(new_work)
    protected |= {spare_title, spare_title + 1}
    for row in ws.iter_rows(min_row=tool_header + 1, max_row=ws.max_row, max_col=COLS):
        if row[0].row in protected:
            continue
        for cell in row:
            try:
                cell.value = None
            except AttributeError:
                pass


def _anchor_tool_data_start(ws) -> int:
    tool_header = _find_row_by_text(ws, ANCHOR_TOOL_HEADER, start=13)
    if tool_header is None:
        raise RuntimeError("需求单模板结构异常：未找到工具区表头锚点")
    return _first_data_row_in_section(ws, tool_header)


def _read_tool_zone_labels(ws, data_start: int) -> dict[str, str]:
    """读取工具区 A 列模板标签原文（发动机工具/机体工具/电子工具），供写回。"""
    labels = {}
    for row in range(data_start, data_start + 12):
        v = str(ws.cell(row=row, column=1).value or "").strip()
        base = v.removesuffix("工具")
        if base in ("发动机", "机体", "电子") and base not in labels:
            labels[base] = v or base
    return labels


def _clear_rows_below(ws, start_row):
    """清除 start_row 起的值（生成末行之后的残留），样式保留。"""
    for mr in list(ws.merged_cells.ranges):
        if mr.min_row >= start_row:
            ws.unmerge_cells(str(mr))
    for row in ws.iter_rows(min_row=start_row, max_row=ws.max_row, max_col=COLS):
        for cell in row:
            try:
                cell.value = None
            except AttributeError:
                pass


def _update_print_area(ws, last_row: int) -> None:
    """打印范围覆盖模板已有行与动态扩展行（至少 I42）。"""
    end_row = max(last_row - 1, 42)
    ws.print_area = f"{SHEET_NAME}!$A$1:${get_column_letter(COLS)}${end_row}"


def _write_tool_section(ws, start_row, tools, cat_labels=None):
    """All tools go here (both must-use and check-use). Min 3 rows per category.
    Tools with usage_type "检查有问题领用" get remark annotation.
    动态行样式复制工具区参考行（表头下一行）；A 列写模板区标签原文。"""
    style_ref = ws.cell(row=start_row, column=2)
    return _write_category_block_min_rows(ws, start_row, tools, 3,
        name_key="device_name", task_key="task_name", style_ref=style_ref,
        cat_labels=cat_labels)


def _write_new_work_row(ws, start_row, new_cards, sub_cards=None):
    """新增工作行：文字动态，A24 标签与边框样式保留模板。"""
    row = start_row
    texts = []
    if sub_cards:
        for card in sub_cards:
            texts.append(f'{card.get("task_code","")} {card.get("task_name","")}（工卡组子卡）')
    if new_cards:
        for card in new_cards:
            texts.append(f'{card.get("task_code","")} {card.get("task_name","")}（未匹配）')
    if texts:
        ws.cell(row=row, column=2, value="; ".join(texts))
        ws.cell(row=row, column=2).font = Font(name="SimSun", size=16, bold=True, color="FF0000")
    else:
        ws.cell(row=row, column=2, value="无")
    return row + 1


def _write_material_section(ws, start_row, materials):
    """"必须使用" materials only. Min 3 rows per category.
    行 25 表头由模板保留，数据从下一行开始。"""
    style_ref = ws.cell(row=start_row + 1, column=2)
    return _write_category_block_min_rows(ws, start_row + 1, materials, 3,
        name_key="material_name", task_key="task_name", style_ref=style_ref)


def _write_spare_section(ws, start_row, spare_auto, spare_manual):
    """"检查有问题领用" materials go here. Min 2 rows per category.

    A35 标题与行 36 表头由模板保留（队名不再硬编码）；
    手动备用航材已弃用，仅写数据库导出的 spare_auto。
    """
    # 标题行与表头行已由模板保留，动态数据从表头下一行开始
    data_start = start_row + 2
    style_ref = ws.cell(row=data_start, column=2)
    return _write_category_block_min_rows(ws, data_start, spare_auto, 2,
        name_key="material_name", task_key="task_name",
        merge_h_col=False, style_ref=style_ref)

"""借用清单生成器 —— 按匹配结果自动生成《零散工具借用清单》与《开封航化借用清单》。

重复判定标准（工具与航化共用）：对两条记录 a、b——
1. 双方件号均非空：件号相同 → 重复；件号不同 → 再比名称，名称相同 → 重复；
2. 任一件号为空：直接比名称，名称相同 → 重复。
（名称/件号均先归一化：strip + 压缩空白 + casefold）

填充规则：
- 工具清单（tools_template.xlsx /「定检工具」）：A 列纵向合并四区——通用 3-18
  （预印 3-15、空白 16-18）、发动机 19-28、机体 29-38、电子 39-48。特检/支援丢弃；
  组内专业数 ≥2 的重复组去重取最大后写通用区空白行；单专业组写对应专业区，
  组内任一行命中通用预印行（同标准）则整组跳过；区满自动插行扩区。
- 航化清单（materials_template.xlsx /「定检航化」）：常用 3-11、外场航化 12-17 预印
  视为已有；remark 含"开封航化"且非"检查有问题领用"的重复组写非例行区 18-24，
  区满自动插行。
- 合并组取最大数量（数字解析 max，全不可解析取第一条非空），件号随最大行。
- 区域定位一律按 A 列区标签实时解析（前区扩行会平移后续区坐标）。
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import MATERIALS_TEMPLATE_FILE, TOOLS_TEMPLATE_FILE
from ..utils.template_cache import load_template

TOOLS_SHEET = "定检工具"
CHEM_SHEET = "定检航化"

# 动态行直接继承模板空行样式；此常量已废弃，仅保留占位避免外部引用（无）。
# （阶段2修复：不再强制统一宋体11/细边框/居中，保留模板区首尾 medium 边框与字号差异。）


def _norm(value) -> str:
    """归一化：strip + 压缩空白 + casefold。"""
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _parse_qty(value) -> float:
    """数量解析：取首个数字（含小数）；不可解析返回 0。"""
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else 0.0


def _same_item(a: dict, b: dict, name_key: str) -> bool:
    """重复判定：件号均非空且相同 → 重复；件号不同 → 再比名称；任一件号空 → 比名称。"""
    pn_a, pn_b = _norm(a.get("part_number")), _norm(b.get("part_number"))
    if pn_a and pn_b and pn_a == pn_b:
        return True
    return _norm(a.get(name_key)) == _norm(b.get(name_key))


def _group_items(items: list[dict], name_key: str) -> list[list[dict]]:
    """顺序分组：新记录归入首个与其判定为重复的组；无命中则新建组（代表=首行）。"""
    groups: list[list[dict]] = []
    for item in items:
        for group in groups:
            if _same_item(item, group[0], name_key):
                group.append(item)
                break
        else:
            groups.append([item])
    return groups


def _merge_group(rows: list[dict]) -> dict:
    """合并组：组代表=首行（名称保留首行），数量与件号随可解析最大行；全不可解析取第一条非空数量。"""
    parseable = [r for r in rows if _parse_qty(r.get("quantity")) > 0]
    if parseable:
        best = max(parseable, key=lambda r: _parse_qty(r.get("quantity")))
    else:
        best = next((r for r in rows if str(r.get("quantity") or "").strip()), rows[0])
    rep = dict(rows[0])
    rep["quantity"] = best["quantity"]
    if str(best.get("part_number") or "").strip():
        rep["part_number"] = best["part_number"]
    return rep


def _zone_bounds(ws, label: str) -> tuple[int, int]:
    """按 A 列区标签实时解析纵向合并区 → (起始行, 结束行)。"""
    for rng in ws.merged_cells.ranges:
        if rng.min_col == 1 and rng.max_col == 1 and \
                str(ws.cell(row=rng.min_row, column=1).value or "").strip() == label:
            return rng.min_row, rng.max_row
    raise RuntimeError(f"模板结构异常：{label} 区")


def _extend_zone(ws, label: str, extra: int = 1) -> None:
    """区满扩行：unmerge 本区与下方合并 → insert_rows → 复制区末行样式与行高 → 平移行高 → re-merge。

    openpyxl insert_rows 不平移合并区与 row_dimensions，均须手动处理。
    """
    start, end = _zone_bounds(ws, label)
    below = [r for r in list(ws.merged_cells.ranges) if r.min_row > end]
    below_heights = [(r + extra, ws.row_dimensions[r].height)
                     for r in range(end + 1, ws.max_row + 2)
                     if r in ws.row_dimensions and ws.row_dimensions[r].height is not None]
    src_height = ws.row_dimensions[end].height if end in ws.row_dimensions else None
    ws.unmerge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
    for rng in below:
        ws.unmerge_cells(str(rng))
    ws.insert_rows(end + 1, extra)
    for r, height in below_heights:
        ws.row_dimensions[r].height = height
    if src_height is not None:
        for r in range(end + 1, end + 1 + extra):
            ws.row_dimensions[r].height = src_height
    for r in range(end + 1, end + 1 + extra):
        for col in range(2, ws.max_column + 1):
            src = ws.cell(row=end, column=col)
            dst = ws.cell(row=r, column=col)
            dst.font = src.font.copy()
            dst.border = src.border.copy()
            dst.fill = src.fill.copy()
            dst.alignment = src.alignment.copy()
            dst.number_format = src.number_format
    ws.merge_cells(start_row=start, start_column=1, end_row=end + extra, end_column=1)
    for rng in below:
        ws.merge_cells(start_row=rng.min_row + extra, start_column=rng.min_col,
                       end_row=rng.max_row + extra, end_column=rng.max_col)


def _row_occupied(ws, row: int, last_col: int) -> bool:
    """整行占用判断：B..last_col 任一列有值即视为已被占用（预印行或人工填写行）。"""
    for col in range(2, last_col + 1):
        if str(ws.cell(row=row, column=col).value or "").strip():
            return True
    return False


def _write_zone_rows(ws, label: str, rows: list[dict], name_key: str,
                     last_col: int = 7) -> None:
    """按行写 B=名称/C=件号/D=数量；从首个整行空白行续写（预印行与人工填写行
    均不覆盖）；区满自动扩行。保留模板空行已有样式（不再强制统一字体/边框）。"""
    start, end = _zone_bounds(ws, label)
    row = start
    while row <= end and _row_occupied(ws, row, last_col):
        row += 1   # 跳过预印行/人工内容行，不覆盖
    for item in rows:
        start, end = _zone_bounds(ws, label)   # 扩行后坐标平移，实时解析
        while row > end:
            _extend_zone(ws, label)
            start, end = _zone_bounds(ws, label)
        for col, value in enumerate(
                (item.get(name_key), item.get("part_number"), str(item.get("quantity") or "").strip()),
                start=2):
            ws.cell(row=row, column=col).value = value
        row += 1


def _zone_names(ws, label: str, name_key: str) -> list[dict]:
    """读取区内已预印记录（B=名称，C=件号），供重复判定。"""
    start, end = _zone_bounds(ws, label)
    names = []
    for row in range(start, end + 1):
        name = str(ws.cell(row=row, column=2).value or "").strip()
        if name:
            names.append({name_key: name,
                          "part_number": str(ws.cell(row=row, column=3).value or "").strip()})
    return names


def _check_tool_template(ws) -> None:
    for label in ("通用", "发动机", "机体", "电子"):
        _zone_bounds(ws, label)


def _check_chem_template(ws) -> None:
    for label in ("常用", "外场航化", "非例行"):
        _zone_bounds(ws, label)


def generate_tool_list(form_data: dict, tools: list[dict]) -> tuple[io.BytesIO, str]:
    """生成《定检中队零散工具借用清单》。

    tools 为匹配后铺平的工具行（含 category/device_name/part_number/quantity）。
    特检/支援与"检查有问题领用"丢弃；重复组（件号→名称 两级判定）按组内专业数分流：
    ≥2 专业 → 通用区空白行，=1 → 对应专业区；任一行命中通用预印（同标准）→ 整组跳过。
    """
    reg = str(form_data.get("reg", "XXXX")).removeprefix("B-")
    date_str = form_data.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    desc = str(form_data.get("description", "") or "").strip()
    filename = f"定检中队零散工具借用清单（B-{reg} {desc}）{date_str}.xlsx"

    buckets: dict[str, list[dict]] = {cat: [] for cat in ("发动机", "机体", "电子")}
    for item in tools:
        if str(item.get("usage_type") or "").strip() == "检查有问题领用":
            continue   # 备用区/检查有问题领用不进借用清单
        cat = str(item.get("category", "")).strip()
        if cat in buckets:
            buckets[cat].append(item)

    wb = load_template(TOOLS_TEMPLATE_FILE)
    ws = wb[TOOLS_SHEET]
    _check_tool_template(ws)
    generic_pre = _zone_names(ws, "通用", "device_name")

    generic_rows: list[dict] = []
    major_rows: dict[str, list[dict]] = {cat: [] for cat in buckets}
    all_rows = [item for items in buckets.values() for item in items]
    for group in _group_items(all_rows, "device_name"):
        best = _merge_group(group)
        if any(_same_item(row, pre, "device_name") for row in group for pre in generic_pre):
            continue   # 任一行命中通用预印（同标准）→ 整组跳过
        cats = {r.get("category") for r in group}
        if len(cats) >= 2:
            generic_rows.append(best)
        else:
            major_rows[next(iter(cats))].append(best)

    _write_zone_rows(ws, "通用", generic_rows, "device_name")
    for cat in ("发动机", "机体", "电子"):
        _write_zone_rows(ws, cat, major_rows[cat], "device_name")

    buffer = io.BytesIO()
    wb.save(buffer)
    wb.close()
    buffer.seek(0)
    return buffer, filename


def generate_chemical_list(form_data: dict, materials: list[dict]) -> tuple[io.BytesIO, str]:
    """生成《定检中队开封航化借用清单》。

    materials 为匹配后铺平的航材行（含 category/material_name/part_number/quantity/remark）。
    仅收 remark 含"开封航化"且非"检查有问题领用"的重复组；任一行命中 常用/外场航化
    预印（同标准）→ 整组排除。
    """
    reg = str(form_data.get("reg", "XXXX")).removeprefix("B-")
    date_str = form_data.get("date", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    desc = str(form_data.get("description", "") or "").strip()
    filename = f"定检中队开封航化借用清单（B-{reg} {desc}）{date_str}.xlsx"

    wb = load_template(MATERIALS_TEMPLATE_FILE)
    ws = wb[CHEM_SHEET]
    _check_chem_template(ws)
    common_pre = _zone_names(ws, "常用", "material_name")
    field_pre = _zone_names(ws, "外场航化", "material_name")
    pre = common_pre + field_pre

    rows = []
    for item in materials:
        remark = str(item.get("remark", ""))
        if "开封航化" not in remark:
            continue
        if str(item.get("usage_type") or "").strip() == "检查有问题领用":
            continue   # 备用区/检查有问题领用不进借用清单
        rows.append(item)

    output = []
    for group in _group_items(rows, "material_name"):
        if any(_same_item(row, pre_row, "material_name") for row in group for pre_row in pre):
            continue   # 命中 常用/外场航化 预印（同标准）→ 整组排除
        output.append(_merge_group(group))

    _write_zone_rows(ws, "非例行", output, "material_name", last_col=8)

    buffer = io.BytesIO()
    wb.save(buffer)
    wb.close()
    buffer.seek(0)
    return buffer, filename

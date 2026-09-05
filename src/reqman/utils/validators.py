"""请求参数验证工具

提供常用验证函数，统一校验错误格式。
"""

from .error_handlers import ValidationError

_INVISIBLE_CHARS = "\u00a0\u3000\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u202f\u205f\u2060\ufeff"


def is_blank(value) -> bool:
    """判断值是否为空白（None/空串/纯空格或不可见字符）。非字符串不算空白。"""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return clean_text(value) == ""


def clean_text(value):
    """剥离字符串首尾空白与不可见字符，保留内部内容；非字符串原样返回。"""
    if value is None or not isinstance(value, str):
        return value
    return value.strip(_INVISIBLE_CHARS + " \t\r\n")


def validate_required(data, field, label=None):
    """验证必填字段（空值判定统一走 is_blank，字符串返回清洗后的值）"""
    value = data.get(field)
    if is_blank(value):
        name = label or field
        raise ValidationError(f"{name}不能为空", field=field)
    return clean_text(value)


def validate_required_fields(data, *fields, labels=None):
    """批量验证多个必填字段，返回字段值元组"""
    labels = labels or {}
    results = []
    for field in fields:
        label = labels.get(field, field)
        value = validate_required(data, field, label=label)
        results.append(value)
    return tuple(results) if len(results) > 1 else results[0]


def validate_str_length(value, field, min_len=1, max_len=None, label=None):
    """验证字符串长度"""
    name = label or field
    if len(value) < min_len:
        raise ValidationError(f"{name}长度不能少于{min_len}个字符")
    if max_len and len(value) > max_len:
        raise ValidationError(f"{name}长度不能超过{max_len}个字符")
    return value


def validate_int(value, field, label=None):
    """验证整数范围"""
    name = label or field
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValidationError(f"{name}必须是数字")


def validate_choice(value, choices, field, label=None):
    """验证字段值必须在允许的选项中"""
    name = label or field
    if value not in choices:
        allowed = ", ".join(str(c) for c in choices)
        raise ValidationError(f"{name}必须是以下值之一: {allowed}")
    return value


def validate_file_extension(filename, allowed_extensions, label=None):
    """验证文件扩展名"""
    name = label or "文件"
    if not filename:
        raise ValidationError(f"{name}不能为空")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_extensions:
        allowed = ", ".join(f".{e}" for e in allowed_extensions)
        raise ValidationError(f"{name}格式不支持，仅支持: {allowed}")
    return ext


def validate_tools_mats(tools, materials, tools_confirmed=False, materials_confirmed=False):
    """验证工具/航材至少有一项或有确认标志"""
    if not tools and not tools_confirmed:
        raise ValidationError("请添加工具或确认无工具")
    if not materials and not materials_confirmed:
        raise ValidationError("请添加航材或确认无航材")

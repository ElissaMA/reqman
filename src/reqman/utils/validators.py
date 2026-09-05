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

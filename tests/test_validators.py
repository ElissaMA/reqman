"""validators 空值校验工具函数单元测试

覆盖任务 #019ff49b 规格：
- is_blank / clean_text 单测
- validate_required 对零宽空格/全角空格等不可见字符必填拒绝
"""
import pytest

from reqman.utils.validators import ValidationError, clean_text, is_blank, validate_required

# 不可见字符集
ZWSP = "\u200b"          # 零宽空格 U+200B
ZWNJ = "\u200c"          # 零宽非连接符
ZWJ = "\u200d"           # 零宽连接符
LRM = "\u200e"           # 左到右标记
RLM = "\u200f"           # 右到左标记
BOM = "\ufeff"           # 字节序标记
FULLWIDTH_SPACE = "\u3000"  # 全角空格
TAB = "\t"
NL = "\n"


class TestIsBlank:
    """is_blank：空值/纯不可见字符 → True；有可见内容 → False"""

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "   ",
            TAB,
            NL,
            "\r\n\t ",
            ZWSP,
            ZWNJ,
            ZWJ,
            LRM,
            RLM,
            BOM,
            FULLWIDTH_SPACE,
            ZWSP * 5,
            f"{ZWSP} \u3000\t{ZWNJ}",
        ],
    )
    def test_is_blank_true(self, value):
        assert is_blank(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "a",
            "abc",
            " a ",
            f"a{ZWSP}b",
            "0",
            0,
            123,
            False,
            ["a"],
        ],
    )
    def test_is_blank_false(self, value):
        assert is_blank(value) is False


class TestCleanText:
    """clean_text：剥离首尾普通空白与不可见字符，保留内部内容"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  abc  ", "abc"),
            ("\tabc\n", "abc"),
            (f"{ZWSP}abc{ZWSP}", "abc"),
            (f"{FULLWIDTH_SPACE}abc{FULLWIDTH_SPACE}", "abc"),
            (f"{ZWSP}{ZWNJ}{ZWJ}\t abc \n{ZWSP}", "abc"),
            ("a  b", "a  b"),                       # 内部空格保留
            (f"a{ZWSP}b", "a\u200bb"),              # 内部零宽保留
            (f"{ZWSP}{FULLWIDTH_SPACE}\t", ""),     # 纯不可见 → 空串
            ("", ""),
            (None, None),                           # 非 str 原样返回
            (0, 0),
            (123.5, 123.5),
        ],
    )
    def test_clean_text(self, raw, expected):
        assert clean_text(raw) == expected


class TestValidateRequired:
    """validate_required：零宽/全角/纯空白必填拒绝"""

    def test_blank_string_rejected(self):
        with pytest.raises(ValidationError, match="名称不能为空"):
            validate_required({"name": ""}, "name", label="名称")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError, match="名称不能为空"):
            validate_required({"name": "   \t\n"}, "name", label="名称")

    @pytest.mark.parametrize("invisible", [ZWSP, ZWNJ, ZWJ, BOM, FULLWIDTH_SPACE, LRM, RLM])
    def test_invisible_chars_rejected(self, invisible):
        """零宽/全角空格等不可见字符不能通过必填校验"""
        with pytest.raises(ValidationError, match="名称不能为空"):
            validate_required({"name": invisible}, "name", label="名称")

    def test_mixed_invisible_rejected(self):
        with pytest.raises(ValidationError, match="名称不能为空"):
            validate_required({"name": f"{ZWSP}\u3000{ZWNJ}"}, "name", label="名称")

    def test_missing_key_rejected(self):
        with pytest.raises(ValidationError, match="名称不能为空"):
            validate_required({}, "name", label="名称")

    def test_none_rejected(self):
        with pytest.raises(ValidationError, match="名称不能为空"):
            validate_required({"name": None}, "name", label="名称")

    def test_normal_value_returns_trimmed(self):
        assert validate_required({"name": "  abc  "}, "name", label="名称") == "abc"

    def test_value_with_inner_space_kept(self):
        assert validate_required({"name": " a b "}, "name", label="名称") == "a b"

    def test_zero_int_valid(self):
        """0 是有效值（数量等场景），不应被当作空"""
        assert validate_required({"qty": 0}, "qty", label="数量") == 0

    def test_default_label_uses_field(self):
        with pytest.raises(ValidationError, match="name不能为空"):
            validate_required({"name": ""}, "name")

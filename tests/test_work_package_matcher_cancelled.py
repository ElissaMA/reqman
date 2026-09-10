"""工作清单通用规范化测试。"""

from reqman.services.work_package_matcher import is_cancelled_item


def test_cancelled_mark_variants_are_consistent():
    for remark in ("撤销", " 已撤销 ", "撤销\u3000", "该工卡（撤销）", "撤销；计划变更"):
        assert is_cancelled_item({"remark": remark}) is True


def test_non_cancelled_remark_is_kept():
    for remark in ("", "正常", "暂不执行", "取消工具"):
        assert is_cancelled_item({"remark": remark}) is False


def test_cancelled_field_does_not_override_remark():
    assert is_cancelled_item({"remark": "撤销", "cancelled": False}) is True
    assert is_cancelled_item({"remark": "正常", "cancelled": True}) is False

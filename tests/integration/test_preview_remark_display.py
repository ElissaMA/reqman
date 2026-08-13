"""预览页 generate/form.html 备注显示统一：三区（工具/航材/备用）remark_display 渲染

验收标准：
- usage_type=检查有问题领用 + 备注 → "检查有问题领用，备注"（中文逗号分隔）
- usage_type=检查有问题领用 + 空备注 → 只显示"检查有问题领用"
- usage_type=必须使用（或其他） → 只显示备注
"""
import datetime

from flask import render_template


class TestPreviewRemarkDisplay:
    """generate/form.html 三区备注渲染验证"""

    def _render(self, app, tool_groups=None, mat_groups=None, spare_groups=None):
        with app.test_request_context("/generate"):
            html = render_template(
                "generate/form.html",
                has_data=True,
                package_id="PKG-TEST",
                aircraft_info={
                    "reg": "B-1234", "type": "A320",
                    "date": "2026-08-13", "description": "测试",
                },
                now=datetime.datetime(2026, 8, 13, tzinfo=datetime.timezone.utc),
                conditions=["定检", "测试"],
                new_cards=[],
                tool_groups=tool_groups or [],
                mat_groups=mat_groups or [],
                spare_groups=spare_groups or [],
                categories=["发动机", "机体", "电子"],
            )
        return html

    def _item(self, name, usage_type="必须使用", remark="", **extra):
        item = {
            "device_name": name, "material_name": name, "part_number": "PN-1",
            "quantity": "1", "task_name": "工卡", "usage_type": usage_type,
            "remark": remark,
        }
        item.update(extra)
        return item

    # ---------- 工具区 ----------

    def test_tools_check_issue_with_remark(self, app):
        """工具区：检查有问题领用+备注 → '检查有问题领用，备注'"""
        html = self._render(app, tool_groups=[("发动机", [
            self._item("扳手", usage_type="检查有问题领用", remark="已磨损"),
        ])])
        assert "检查有问题领用，已磨损" in html

    def test_tools_check_issue_empty_remark(self, app):
        """工具区：检查有问题领用+空备注 → 只显示'检查有问题领用'"""
        html = self._render(app, tool_groups=[("发动机", [
            self._item("扳手", usage_type="检查有问题领用", remark=""),
        ])])
        assert "检查有问题领用" in html
        # 不应出现多余逗号尾巴
        assert "检查有问题领用，" not in html

    def test_tools_must_use_only_remark(self, app):
        """工具区：必须使用 → 只显示备注"""
        html = self._render(app, tool_groups=[("发动机", [
            self._item("扳手", usage_type="必须使用", remark="随机携带"),
        ])])
        assert ">随机携带<" in html  # 备注单元格只渲染备注
        assert "必须使用，随机携带" not in html
        assert "必须使用随机携带" not in html

    # ---------- 航材区 ----------

    def test_materials_check_issue_with_remark(self, app):
        """航材区：检查有问题领用+备注 → '检查有问题领用，备注'"""
        html = self._render(app, mat_groups=[("发动机", [
            self._item("垫片", usage_type="检查有问题领用", remark="数量不足"),
        ])])
        assert "检查有问题领用，数量不足" in html

    def test_materials_check_issue_empty_remark(self, app):
        """航材区：检查有问题领用+空备注 → 只显示'检查有问题领用'"""
        html = self._render(app, mat_groups=[("发动机", [
            self._item("垫片", usage_type="检查有问题领用", remark=""),
        ])])
        assert "检查有问题领用" in html
        assert "检查有问题领用，" not in html

    def test_materials_must_use_only_remark(self, app):
        """航材区：必须使用 → 只显示备注"""
        html = self._render(app, mat_groups=[("发动机", [
            self._item("垫片", usage_type="必须使用", remark="例行消耗"),
        ])])
        assert ">例行消耗<" in html
        assert "必须使用，例行消耗" not in html
        assert "必须使用例行消耗" not in html

    # ---------- 备用区 ----------

    def test_spares_check_issue_with_remark(self, app):
        """备用区：检查有问题领用+备注 → '检查有问题领用，备注'"""
        html = self._render(app, spare_groups=[("电子", [
            self._item("继电器", usage_type="检查有问题领用", remark="备用更换"),
        ])])
        assert "检查有问题领用，备用更换" in html

    def test_spares_check_issue_empty_remark(self, app):
        """备用区：检查有问题领用+空备注 → 只显示'检查有问题领用'"""
        html = self._render(app, spare_groups=[("电子", [
            self._item("继电器", usage_type="检查有问题领用", remark=""),
        ])])
        assert "检查有问题领用" in html
        assert "检查有问题领用，" not in html

    def test_spares_must_use_only_remark(self, app):
        """备用区：必须使用 → 只显示备注"""
        html = self._render(app, spare_groups=[("电子", [
            self._item("继电器", usage_type="必须使用", remark="机上备份"),
        ])])
        assert ">机上备份<" in html
        assert "必须使用，机上备份" not in html
        assert "必须使用机上备份" not in html

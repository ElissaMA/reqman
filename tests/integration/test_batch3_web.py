"""第三批 Web 侧回归（H2 Host 白名单 / 打包注入）。

H1（上传令牌鉴权）已按部署实际撤回：本系统在公司内网/反代后使用，
令牌需同时改造 ProxyFix 与多人令牌分发，收益不抵复杂度；
防外带改由「配置包注入地址白名单」承担（见 H3 与 _resolve_server_url）。
"""
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestUploadNoToken:
    """凭证上传恢复为无令牌（保持多人共用工作流）。"""

    def test_upload_accepted_without_token(self, client):
        import json

        resp = client.post(
            "/inventory/login/upload",
            data={"cookies": json.dumps([{"name": "JSESSIONID", "value": "x"}]),
                  "account": "u1"},
        )
        assert resp.status_code == 200


class TestHostAllowlist:
    def test_rejects_unlisted_host_when_allowlist_configured(self, client, monkeypatch):
        import reqman.blueprints.inventory_bp as bp

        monkeypatch.setattr(bp, "AMRO_PUBLIC_URL", "")
        monkeypatch.setattr(bp, "AMRO_ALLOWED_HOSTS", ["reqman.example.com"])
        # 非 AJAX 走 flash+redirect（302），AJAX 直接 400；两者都不产出配置包
        resp = client.get("/inventory/setup-package",
                          headers={"Host": "evil.example.com"})
        assert resp.status_code in (302, 400)
        assert "zip" not in (resp.headers.get("Content-Type") or "").lower()

        ajax = client.get("/inventory/setup-package",
                          headers={"Host": "evil.example.com",
                                   "X-Requested-With": "XMLHttpRequest"})
        assert ajax.status_code == 400

    def test_unconfigured_allowlist_trusts_current_host(self, client, monkeypatch):
        """未配白名单时不阻断多人使用：按当前 Host 注入（内网/反代场景）。"""
        import reqman.blueprints.inventory_bp as bp

        monkeypatch.setattr(bp, "AMRO_PUBLIC_URL", "")
        monkeypatch.setattr(bp, "AMRO_ALLOWED_HOSTS", [])
        resp = client.get("/inventory/setup-package", headers={"Host": "8.137.15.167"})
        assert resp.status_code == 200

    def test_allows_listed_host(self, client, monkeypatch):
        import reqman.blueprints.inventory_bp as bp

        monkeypatch.setattr(bp, "AMRO_PUBLIC_URL", "")
        monkeypatch.setattr(bp, "AMRO_ALLOWED_HOSTS", ["reqman.example.com"])
        resp = client.get("/inventory/setup-package", headers={"Host": "reqman.example.com"})
        assert resp.status_code == 200

    def test_public_url_always_used(self, client, monkeypatch):
        import reqman.blueprints.inventory_bp as bp

        monkeypatch.setattr(bp, "AMRO_PUBLIC_URL", "http://8.137.15.167")
        resp = client.get("/inventory/setup-package", headers={"Host": "anything.invalid"})
        assert resp.status_code == 200


class TestPackageInjection:
    def test_package_carries_allowed_hosts(self, client, monkeypatch):
        import reqman.blueprints.inventory_bp as bp

        monkeypatch.setattr(bp, "AMRO_PUBLIC_URL", "http://8.137.15.167")
        monkeypatch.setattr(bp, "AMRO_ALLOWED_HOSTS", ["extra.example.com"])
        resp = client.get("/inventory/setup-package")
        src = zipfile.ZipFile(io.BytesIO(resp.data)).read("amro_login.py").decode("utf-8")

        assert "8.137.15.167" in src
        assert "extra.example.com" in src
        # 令牌已撤回，不应再出现在打包产物里
        assert "UPLOAD_TOKEN" not in src


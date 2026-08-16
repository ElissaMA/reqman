"""库存查询接口集成测试（mock AMRO）"""
import io
import zipfile
from pathlib import Path

import openpyxl
import pytest


@pytest.fixture(autouse=True)
def isolated_inventory(app, tmp_path, monkeypatch):
    """隔离登录凭证缓存与输出目录到临时目录，避免污染 data/cookie/ 与 output/。"""
    from reqman.services.connectors.session import LoginSessionStore
    from reqman.services.inventory_service import InventoryService

    app.extensions["inventory_service"] = InventoryService(
        LoginSessionStore(tmp_path / "session.json", ttl_seconds=7200)
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    import reqman.blueprints.inventory_bp as bp_mod
    monkeypatch.setattr(bp_mod, "OUTPUT_DIR", out_dir)
    import reqman.services.inventory_service as inv_mod
    monkeypatch.setattr(inv_mod, "OUTPUT_DIR", out_dir)
    yield out_dir


def _build_demand(tmp_path: Path) -> Path:
    src = tmp_path / "demand.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A14"] = "定检专业\n（航材）"
    ws["A15"] = "发动机"; ws["B15"] = "螺钉"; ws["C15"] = "PN-001"; ws["E15"] = "2"
    wb.save(src)
    return src


def _mock_amro_query(monkeypatch, app):
    """预置登录并 mock 探活 + AMRO 查询。"""
    svc = app.extensions["inventory_service"]
    svc.session_store.save([{"name": "JSESSIONID", "value": "abc"}])
    monkeypatch.setattr(svc, "check_login", lambda: True)

    async def fake_query(client, cookies, pn):
        from reqman.services.connectors.amro import KunmingStock
        return KunmingStock(1.0, "EA", "螺钉")

    import reqman.services.connectors.amro as amro_mod
    monkeypatch.setattr(amro_mod, "query_kunming_stock", fake_query)


class TestInventoryPage:
    def test_page_accessible(self, client):
        resp = client.get("/inventory")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # ZIP 配置包下载确认弹窗结构
        assert 'id="zipModal"' in html
        assert 'id="zipConfirmBtn"' in html
        assert "确认下载" in html
        # 「新建配置」为按钮（触发确认弹窗），非直接跳转链接
        assert 'id="setupPackageBtn"' in html


class TestSession:
    def test_not_ready(self, client):
        resp = client.get("/inventory/session", headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["ready"] is False

    def test_cache_probe_ok_ready(self, app, client, monkeypatch):
        """缓存存在 + 探活成功 → P5 登录有效。"""
        svc = app.extensions["inventory_service"]
        svc.session_store.save([{"name": "JSESSIONID", "value": "abc"}])
        monkeypatch.setattr(svc, "check_login", lambda: True)
        resp = client.get("/inventory/session", headers={"X-Requested-With": "XMLHttpRequest"})
        data = resp.get_json()
        assert data["data"]["ready"] is True
        assert "登录有效" in data["data"]["message"]

    def test_cache_probe_fail_expired(self, app, client, monkeypatch):
        """缓存存在 + 探活失败 → P7 登录已过期。"""
        svc = app.extensions["inventory_service"]
        svc.session_store.save([{"name": "JSESSIONID", "value": "abc"}])
        monkeypatch.setattr(svc, "check_login", lambda: False)
        resp = client.get("/inventory/session", headers={"X-Requested-With": "XMLHttpRequest"})
        data = resp.get_json()
        assert data["data"]["ready"] is False
        assert "重新运行登录脚本" in data["data"]["message"]


class TestSetupPackage:
    def test_downloads_zip(self, client):
        resp = client.get("/inventory/setup-package")
        assert resp.status_code == 200
        assert resp.mimetype in ("application/zip", "application/x-zip-compressed")
        content = resp.data
        zf = zipfile.ZipFile(io.BytesIO(content))
        names = zf.namelist()
        assert any("amro_login.py" in n for n in names)
        assert any("start_login.bat" in n for n in names)
        assert any("README" in n for n in names)

    def _py_source(self, resp) -> str:
        zf = zipfile.ZipFile(io.BytesIO(resp.data))
        return zf.read("amro_login.py").decode("utf-8")

    def test_injects_fallback_host_url(self, client, monkeypatch):
        """未配置 AMRO_PUBLIC_URL → 回退当前访问地址（host_url）。"""
        import reqman.blueprints.inventory_bp as bp_mod
        monkeypatch.setattr(bp_mod, "AMRO_PUBLIC_URL", "")
        resp = client.get("/inventory/setup-package")
        assert resp.status_code == 200
        src = self._py_source(resp)
        assert 'SERVER_URL = "http://localhost"' in src
        assert 'UPLOAD_URL = "http://localhost/inventory/login/upload"' in src
        assert "trust_env=False" in src

    def test_injects_configured_public_url(self, client, monkeypatch):
        """配置 AMRO_PUBLIC_URL → 注入配置的公网地址。"""
        import reqman.blueprints.inventory_bp as bp_mod
        monkeypatch.setattr(bp_mod, "AMRO_PUBLIC_URL", "http://8.137.15.167")
        resp = client.get("/inventory/setup-package")
        assert resp.status_code == 200
        src = self._py_source(resp)
        assert 'SERVER_URL = "http://8.137.15.167"' in src
        assert 'UPLOAD_URL = "http://8.137.15.167/inventory/login/upload"' in src
        assert "trust_env=False" in src


class TestCheckConfig:
    def test_rejects_wrong_content(self, client):
        resp = client.post(
            "/inventory/check-config",
            data={"file": (io.BytesIO(b"not a script"), "foo.txt")},
            headers={"X-Requested-With": "XMLHttpRequest"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False


class TestLoginUpload:
    def test_upload_saves(self, client):
        cookies_json = '[{"name":"JSESSIONID","value":"abc123"}]'
        resp = client.post(
            "/inventory/login/upload",
            data={"cookies": cookies_json},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_upload_invalid_json(self, client):
        resp = client.post(
            "/inventory/login/upload",
            data={"cookies": "not json"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400


class TestQuery:
    def test_query_requires_login(self, client, tmp_path):
        src = _build_demand(tmp_path)
        with src.open("rb") as f:
            resp = client.post(
                "/inventory/query",
                data={"file": (f, "demand.xlsx")},
                headers={"X-Requested-With": "XMLHttpRequest"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "重新运行登录脚本" in data["message"]

    def test_query_success_returns_stats_and_file(self, app, client, tmp_path, monkeypatch, isolated_inventory):
        """成功路径：JSON 统计 + 文件名保留原名 + 输出落盘 output/。"""
        _mock_amro_query(monkeypatch, app)
        out_dir = isolated_inventory

        src = _build_demand(tmp_path)
        with src.open("rb") as f:
            resp = client.post(
                "/inventory/query",
                data={"file": (f, "demand.xlsx")},
                headers={"X-Requested-With": "XMLHttpRequest"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["success"] == 1
        assert data["data"]["shortage"] == 1
        assert data["data"]["filename"].startswith("demand_库存已填_")
        # 文件已写入 output/
        saved = list(out_dir.glob("demand_库存已填_*.xlsx"))
        assert len(saved) == 1
        wb = openpyxl.load_workbook(saved[0])
        assert wb.active["G15"].value == 1
        wb.close()

    def test_query_clears_old_staging(self, app, client, tmp_path, monkeypatch, isolated_inventory):
        """上传新需求单查询 → 旧的 *_库存已填_* 暂存被清除，output/ 仅存最新。"""
        _mock_amro_query(monkeypatch, app)
        out_dir = isolated_inventory
        (out_dir / "旧需求单_库存已填_20260101_000000.xlsx").write_bytes(b"old")
        (out_dir / "无关文件.txt").write_bytes(b"keep")

        src = _build_demand(tmp_path)
        with src.open("rb") as f:
            resp = client.post(
                "/inventory/query",
                data={"file": (f, "demand.xlsx")},
                headers={"X-Requested-With": "XMLHttpRequest"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        staged = [p.name for p in out_dir.glob("*_库存已填_*.xlsx")]
        assert len(staged) == 1  # 旧暂存已清
        assert "旧需求单_库存已填_" not in staged[0]
        assert (out_dir / "无关文件.txt").exists()  # 未误删其他文件


class TestDownload:
    def test_download_ok(self, client, tmp_path, isolated_inventory):
        out_dir = isolated_inventory
        f = out_dir / "需求单A_库存已填_20260101_000000.xlsx"
        f.write_bytes(b"xlsx-bytes")
        resp = client.get("/inventory/download?file=" + f.name)
        assert resp.status_code == 200
        assert resp.data == b"xlsx-bytes"

    def test_download_rejects_path_traversal(self, client, isolated_inventory):
        resp = client.get(
            "/inventory/download?file=..%2F..%2Fsecret.txt",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400
        resp2 = client.get(
            "/inventory/download?file=..%5Csecret.txt",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp2.status_code == 400

    def test_download_not_exists(self, client, isolated_inventory):
        resp = client.get(
            "/inventory/download?file=nonexist_库存已填_1.xlsx",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400


class TestLatestOutput:
    def test_no_output(self, client, isolated_inventory):
        resp = client.get("/inventory/latest-output", headers={"X-Requested-With": "XMLHttpRequest"})
        data = resp.get_json()
        assert data["data"]["exists"] is False

    def test_has_latest(self, client, isolated_inventory):
        out_dir = isolated_inventory
        (out_dir / "A_库存已填_1.xlsx").write_bytes(b"a")
        (out_dir / "B_库存已填_2.xlsx").write_bytes(b"b")
        resp = client.get("/inventory/latest-output", headers={"X-Requested-With": "XMLHttpRequest"})
        data = resp.get_json()
        assert data["data"]["exists"] is True
        assert data["data"]["filename"] == "B_库存已填_2.xlsx"

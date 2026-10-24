"""跨站写防护（CSRF）集成测试 — before_request Origin/Referer 同源校验。"""


class TestCsrfGuard:
    def test_cross_origin_post_blocked(self, client):
        """异源 Origin 的写请求 403 拦截"""
        resp = client.post("/card/new",
                           data={"task_code": "X", "task_name": "x", "category": "机体"},
                           headers={"Origin": "http://evil.example.com"})
        assert resp.status_code == 403
        assert resp.get_json()["success"] is False

    def test_cross_site_referer_blocked(self, client):
        """无 Origin 但异源 Referer 的写请求同样 403"""
        resp = client.post("/card/new",
                           data={"task_code": "X", "task_name": "x", "category": "机体"},
                           headers={"Referer": "http://evil.example.com/attack"})
        assert resp.status_code == 403

    def test_same_origin_post_allowed(self, client):
        """同源 Origin 放行（进入正常业务校验，非 403）"""
        resp = client.post("/card/new",
                           data={"task_code": "", "task_name": "", "category": ""},
                           headers={"Origin": "http://localhost"})
        assert resp.status_code != 403

    def test_no_origin_allowed(self, client):
        """无 Origin/Referer 的非浏览器客户端（curl/脚本/测试）不受影响"""
        resp = client.post("/card/new",
                           data={"task_code": "", "task_name": "", "category": ""})
        assert resp.status_code != 403

    def test_get_unaffected(self, client):
        """读请求不受 Origin 影响"""
        resp = client.get("/card/list", headers={"Origin": "http://evil.example.com"})
        assert resp.status_code == 200

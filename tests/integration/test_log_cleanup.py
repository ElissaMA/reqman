"""日志API测试"""


class TestLogsAPI:
    def test_list_logs_page(self, prefilled_client):
        """日志列表页面"""
        resp = prefilled_client.get("/card/logs")
        assert resp.status_code == 200

    def test_delete_logs(self, prefilled_client, ajax_headers):
        """删除日志API"""
        resp = prefilled_client.post("/card/logs/delete",
                                      data={"log_ids[]": ["1"]},
                                      headers=ajax_headers)
        assert resp.status_code in (200, 302)

    def test_delete_logs_empty_selection(self, prefilled_client, ajax_headers):
        """未选择日志返回错误"""
        resp = prefilled_client.post("/card/logs/delete",
                                      data={},
                                      headers=ajax_headers)
        assert resp.status_code in (200, 400)

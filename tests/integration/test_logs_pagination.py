"""日志分页与序号显示测试（任务 #019fe5d2）"""
import re


class TestPageWindow:
    """分页按钮窗口生成逻辑"""

    def test_small_total(self):
        from reqman.blueprints.logs_bp import _build_page_window
        assert _build_page_window(1, 1) == [1]
        assert _build_page_window(1, 3) == [1, 2, 3]

    def test_large_total(self):
        from reqman.blueprints.logs_bp import _build_page_window
        # 10 页时窗口保留首尾 + 当前页附近（page=1 时 1..6 连续，无前省略号）
        assert _build_page_window(1, 10) == [1, 2, 3, 4, 5, 6, None, 10]
        assert _build_page_window(5, 10) == [1, None, 3, 4, 5, 6, 7, None, 10]
        assert _build_page_window(9, 10) == [1, None, 5, 6, 7, 8, 9, 10]


class TestParsePageArgs:
    """页码/每页条数解析"""

    def test_valid(self):
        from reqman.blueprints.logs_bp import _parse_page_args
        assert _parse_page_args({"page": "2", "page_size": "50"}) == (2, 50)

    def test_invalid(self):
        from reqman.blueprints.logs_bp import _parse_page_args
        assert _parse_page_args({"page": "abc", "page_size": "999"}) == (1, 20)
        assert _parse_page_args({"page": "0", "page_size": "7"}) == (1, 20)
        assert _parse_page_args({}) == (1, 20)


class TestLogsPaginationPage:
    """日志页面分页渲染"""

    def test_pagination_metadata(self, prefilled_client, store):
        """分页元数据（总数/页码/每页条数）正确"""
        for i in range(20):
            store.add(task_code=f"PG-{i:03d}", task_name=f"分页测试{i}",
                      category="发动机", task_type="A", remark="")

        page, page_size = 2, 10
        resp = prefilled_client.get("/card/logs",
                                     query_string={"page": page, "page_size": page_size})
        data = resp.get_data(as_text=True)
        assert resp.status_code == 200

        total = len(store.get_logs(limit=None))
        total_pages = (total + page_size - 1) // page_size
        assert f'共 <span class="fw-bold">{total}</span> 条' in data
        assert f'<span class="fw-bold">{page}/{total_pages}</span> 页' in data
        # 展示序号：全局编号跨页连续，第2页显示 (page-1)*page_size+1 起
        tbody = data.split("<tbody>")[1].split("</tbody>")[0]
        rows = re.findall(r'<tr\b[^>]*>.*?</tr>', tbody, re.DOTALL)
        assert len(rows) == page_size
        start_idx = (page - 1) * page_size
        for display_id in range(start_idx + 1, start_idx + page_size + 1):
            assert f"<td class=\"text-muted small\">{display_id}</td>" in tbody

    def test_page_size_options(self, prefilled_client):
        """每页条数选择器生效"""
        resp = prefilled_client.get("/card/logs", query_string={"page_size": "50"})
        data = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'value="50" selected' in data

    def test_filter_operation(self, prefilled_client, store):
        """操作类型筛选为服务端筛选"""
        for i in range(3):
            store.add(task_code=f"FILT-{i:03d}", task_name=f"筛选测试{i}",
                      category="发动机", task_type="A", remark="")
        resp = prefilled_client.get("/card/logs", query_string={"operation": "add"})
        data = resp.get_data(as_text=True)
        assert resp.status_code == 200
        total_add = sum(1 for l in store.get_logs(limit=None) if l["operation"] == "add")
        assert f'共 <span class="fw-bold">{total_add}</span> 条' in data

    def test_empty_state(self, prefilled_client):
        """无匹配日志时显示空状态"""
        resp = prefilled_client.get("/card/logs", query_string={"keyword": "不存在的关键词XYZ"})
        data = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert '共 <span class="fw-bold">0</span> 条' in data
        assert "暂无日志记录" in data

    def test_keyword_filter_server_side(self, prefilled_client):
        """关键词筛选在服务端生效（不再全量传前端）"""
        resp = prefilled_client.get("/card/logs", query_string={"keyword": "ENG-001"})
        data = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "ENG-001" in data
        # 不包含 logData 全量 JSON（确认已移除客户端数据传递）
        assert "logData" not in data

    def test_filter_date_range(self, prefilled_client, store):
        """日期区间筛选：仅起始=该日起至今；起止同值=单日；区间=含两端。

        向 store 注入 09-01/09-02/09-03 三天的日志，验证路由筛选与直接计数一致
        （prefilled_client 自带日志不影响断言，因期望值由同一 store 实时计算）。
        """
        def inject(ts_day: str) -> None:
            db = store._read()
            logs = db.setdefault("card_logs", [])
            log_id = db.get("card_log_next_id", 1)
            db["card_log_next_id"] = log_id + 1
            logs.append({
                "id": log_id, "operation": "add", "target_type": "card",
                "target_id": log_id, "target_identifier": ts_day,
                "target_name": ts_day, "changes": [],
                "timestamp": f"{ts_day}T10:00:00",
            })
            store._write(db)

        for d in ("2026-09-01", "2026-09-02", "2026-09-03"):
            inject(d)

        all_logs = store.get_logs(limit=None)

        def expected(df=None, dt=None) -> int:
            n = 0
            for l in all_logs:
                d = (l.get("timestamp") or "")[:10]
                if df and d < df:
                    continue
                if dt and d > dt:
                    continue
                n += 1
            return n

        def route_total(q: dict) -> int:
            resp = prefilled_client.get("/card/logs", query_string=q)
            assert resp.status_code == 200
            data = resp.get_data(as_text=True)
            m = re.search(r'共 <span class="fw-bold">(\d+)</span> 条', data)
            return int(m.group(1)) if m else -1

        # 表单已渲染「结束日期」输入（含 name=date_to 与标签）
        html = prefilled_client.get("/card/logs").get_data(as_text=True)
        assert 'name="date_to"' in html
        assert "结束日期" in html

        # 仅填起始：该日(09-02)起至今（含 09-02、09-03）
        assert route_total({"date_from": "2026-09-02"}) == expected(df="2026-09-02")
        # 起止同值：仅单日 09-02
        assert route_total({"date_from": "2026-09-02", "date_to": "2026-09-02"}) == expected(df="2026-09-02", dt="2026-09-02")
        # 区间：09-01 ~ 09-02（含两端，不含 09-03）
        assert route_total({"date_from": "2026-09-01", "date_to": "2026-09-02"}) == expected(df="2026-09-01", dt="2026-09-02")

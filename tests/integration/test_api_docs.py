"""api_docs 端点注册表防漂移 — 文档中的每个 (path, method) 必须真实存在于路由表。

曾出现文档化不存在的 /card/api/list（幽灵端点）：文档与路由各自演化导致误导。"""


def test_documented_paths_exist_in_url_map(app):
    from reqman.api_docs import ENDPOINTS

    registered = {(rule.rule, method)
                  for rule in app.url_map.iter_rules()
                  for method in (rule.methods or set())
                  if method not in ("HEAD", "OPTIONS")}
    documented = [
        (ep["path"], ep["method"].upper())
        for group in ENDPOINTS.values()
        for ep in group.get("endpoints", [])
    ]
    assert documented, "ENDPOINTS 注册表为空，防漂移检查失去意义"

    ghosts = [f"{method} {path}" for path, method in documented
              if (path, method) not in registered]
    assert not ghosts, f"api_docs 文档化了不存在的端点: {ghosts}"

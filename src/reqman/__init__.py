"""定检需求单管理系统 V3 — Flask 应用工厂"""

import logging
import time
from pathlib import Path
from flask import Flask, jsonify, render_template

from .config import DB_FILE, SECRET_KEY, MAX_CONTENT_LENGTH, BASE_DIR
from .utils.openpyxl_patch import apply_patches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------- 请求日志中间件（增强版） ----------
class RequestLogMiddleware:
    """记录每次请求的方法、路径、状态码和耗时，标记慢请求"""

    def __init__(self, app):
        self.app = app
        self.slow_threshold = 2.0  # 超过 2 秒标记为慢请求

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "")
        path = environ.get("PATH_INFO", "")

        # 跳过静态资源
        if path.startswith("/static/"):
            return self.app(environ, start_response)

        start = time.time()
        response_size = [0]

        def _start_response(status, headers, *args):
            elapsed = time.time() - start
            status_code = status.split()[0] if status else "?"
            size_info = ""
            if response_size[0]:
                size_info = f" [{response_size[0]:,}B]"
            log_msg = "[%.3fs]%s %s %s -> %s" % (
                elapsed, size_info, method, path, status_code
            )
            if elapsed >= self.slow_threshold:
                logger.warning("SLOW [%.3fs] %s %s -> %s", elapsed, method, path, status_code)
            else:
                logger.info(log_msg)
            return start_response(status, headers, *args)

        def _write_data(data):
            response_size[0] += len(data)
            return data

        original_write = None

        # 包装 start_response 以拦截 Content-Length
        def _start_response_with_size(status, headers, *args):
            nonlocal original_write
            for h_name, h_val in headers or []:
                if h_name.lower() == "content-length":
                    try:
                        response_size[0] = int(h_val)
                    except (ValueError, TypeError):
                        pass
                    break
            result = _start_response(status, headers, *args)
            if result and hasattr(result, '__iter__'):
                original_write = result
            return result

        wsgi_iter = self.app(environ, _start_response_with_size)
        try:
            for data in wsgi_iter:
                yield _write_data(data)
        finally:
            if hasattr(wsgi_iter, 'close'):
                wsgi_iter.close()


def create_app():
    """应用工厂"""
    app = Flask(__name__, template_folder="templates", static_folder=None)
    app.secret_key = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    # openpyxl 猴子补丁
    apply_patches(BASE_DIR)

    # 依赖注入
    from .models.json_store import JsonStore
    from .services.card_service import CardService

    app.extensions["store"] = JsonStore(str(DB_FILE))
    app.extensions["card_service"] = CardService(app.extensions["store"])
    logger.info("依赖注入完成：store + card_service")

    # 蓝图
    from .blueprints.cards_bp import cards_bp
    from .blueprints.packages_bp import packages_bp
    from .blueprints.generate_bp import generate_bp

    app.register_blueprint(cards_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(generate_bp)

    # 根路由
    @app.route("/")
    def index():
        from flask import redirect
        return redirect("/upload")

    # API 规范文档端点
    @app.route("/api/spec")
    def api_spec():
        from .api_docs import get_openapi_spec
        return jsonify(get_openapi_spec())

    # API 文档说明页（简易 HTML）
    @app.route("/api/docs")
    def api_docs_page():
        from .api_docs import ENDPOINTS
        return render_template("api_docs.html", endpoint_groups=ENDPOINTS)

    # 统一错误处理（支持 JSON 和 HTML 两种模式）
    from .utils.error_handlers import register_error_handlers
    register_error_handlers(app)

    # 请求日志中间���
    app.wsgi_app = RequestLogMiddleware(app.wsgi_app)

    logger.info("应用初始化完成")
    return app

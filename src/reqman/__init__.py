"""定检需求单管理系统 V3 — Flask 应用工厂"""

import logging
import time
from pathlib import Path
from flask import Flask, render_template

from .config import DB_FILE, SECRET_KEY, MAX_CONTENT_LENGTH, BASE_DIR
from .utils.openpyxl_patch import apply_patches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- 请求日志中间件 ----------
class RequestLogMiddleware:
    """记录每次请求的方法、路径、状态码和耗时"""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "")
        path = environ.get("PATH_INFO", "")

        # 跳过静态资源
        if path.startswith("/static/"):
            return self.app(environ, start_response)

        start = time.time()

        def _start_response(status, headers, *args):
            elapsed = time.time() - start
            status_code = status.split()[0] if status else "?"
            logger.info("[%.3fs] %s %s -> %s", elapsed, method, path, status_code)
            return start_response(status, headers, *args)

        return self.app(environ, _start_response)


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
        return redirect("/card/list")

    # 统一错误处理（支持 JSON 和 HTML 两种模式）
    from .utils.error_handlers import register_error_handlers
    register_error_handlers(app)

    # 请求日志中间件
    app.wsgi_app = RequestLogMiddleware(app.wsgi_app)

    logger.info("应用初始化完成")
    return app

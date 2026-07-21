"""定检需求单管理系统 V3 — Flask 应用工厂"""

import logging
from pathlib import Path
from flask import Flask, render_template

from .config import DB_FILE, SECRET_KEY, MAX_CONTENT_LENGTH, BASE_DIR
from .utils.openpyxl_patch import apply_patches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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

    # 错误处理
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message="请求参数无效"), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="页面不存在"), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413, message="上传文件过大，最大允许 16 MB"), 413

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("服务器内部错误")
        return render_template("error.html", code=500, message="服务器内部错误，请稍后重试"), 500

    logger.info("应用初始化完成")
    return app

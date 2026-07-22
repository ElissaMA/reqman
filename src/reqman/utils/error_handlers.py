"""错误处理中间件 —— 全局异常处理器、错误日志记录、自定义错误页面"""

import logging
import traceback

from flask import render_template, request, flash, redirect
from werkzeug.exceptions import HTTPException

from .response import api_error, ApiException

logger = logging.getLogger(__name__)


# ===================== 自定义异常类（按业务分类） =====================

class ValidationError(ApiException):
    """参数校验失败"""
    def __init__(self, message="请求参数无效", error_code="VALIDATION_ERROR", status_code=400):
        super().__init__(message, error_code, status_code)


class NotFoundError(ApiException):
    """资源不存在"""
    def __init__(self, message="请求的资源不存在", error_code="NOT_FOUND", status_code=404):
        super().__init__(message, error_code, status_code)


class ConflictError(ApiException):
    """资源冲突（如重复创建）"""
    def __init__(self, message="资源冲突", error_code="CONFLICT", status_code=409):
        super().__init__(message, error_code, status_code)


class ServerError(ApiException):
    """服务器内部错误"""
    def __init__(self, message="服务器内部错误", error_code="SERVER_ERROR", status_code=500):
        super().__init__(message, error_code, status_code)


# ===================== 辅助函数 =====================


def _wants_json():
    """判断请求是否期望 JSON 响应"""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    return request.accept_mimetypes.best == "application/json"


def raise_or_flash(exception_class, message, error_code=None, referer=None):
    """在蓝图操作中统一处理错误。

    AJAX 请求 -> 抛出异常（由全局处理器返回 JSON）
    表单请求 -> flash 消息并重定向到来源页
    """
    if _wants_json():
        kwargs = {"message": message}
        if error_code:
            kwargs["error_code"] = error_code
        raise exception_class(**kwargs)
    flash(message, "error")
    return redirect(referer or request.headers.get("Referer", "/"))


# ===================== 注册函数 =====================


def register_error_handlers(app):
    """在 Flask app 上注册所有错误处理器"""

    # ---------- HTTPException（如 404/405/403 等�� ----------
    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        logger.warning("HTTP %s: %s %s", error.code, request.method, request.path)
        if _wants_json():
            return api_error(
                message=error.description or str(error),
                error_code=f"HTTP_{error.code}",
                status_code=error.code,
            )
        return render_template(
            "error.html",
            code=error.code,
            message=error.description or str(error)
        ), error.code

    # ---------- ApiException（自定义业务异常） ----------
    @app.errorhandler(ApiException)
    def handle_api_exception(error):
        if error.status_code >= 500:
            logger.exception("ApiException [%s]: %s", error.error_code, error.message)
        else:
            logger.warning(
                "ApiException [%s]: %s (path=%s)",
                error.error_code, error.message, request.path,
            )
        if _wants_json():
            return error.to_response()
        # 非 AJAX 请求：flash 消息后重定向
        flash(error.message, "error")
        referrer = request.headers.get("Referer", "/")
        return redirect(referrer)

    # ---------- 通用 500（未捕获异常兜底） ----------
    @app.errorhandler(Exception)
    def handle_unhandled_exception(error):
        logger.exception("未捕获异常: %s %s", request.method, request.path)
        if _wants_json():
            return api_error(
                message="服务器内部错误���请稍后重试",
                error_code="INTERNAL_ERROR",
                status_code=500,
            )
        if app.debug:
            tb = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
            return render_template(
                "error.html", code=500, message=str(error), detail=tb
            ), 500
        return render_template(
            "error.html", code=500, message="服务器内部错误，请稍后重试"
        ), 500

"""统一 API 响应格式工具

定义项目统一的 JSON 响应格式：
- 成功: {"success": true, "data": {...}, "message": "..."}
- ��误: {"success": false, "message": "...", "error_code": "..."}
"""

from flask import jsonify


def api_success(data=None, message="操作成功"):
    """返回统一成功响应"""
    resp = {"success": True, "data": data, "message": message}
    return jsonify(resp)


def api_error(message="操作失败", error_code="UNKNOWN_ERROR", status_code=400):
    """返回统一错误响应

    Args:
        message: 用户可读的错误消息
        error_code: 机器可读的错误代码（用于前端判断错误类型）
        status_code: HTTP 状态码（默认 400）
    """
    resp = {"success": False, "message": message, "error_code": error_code}
    return jsonify(resp), status_code


class ApiException(Exception):
    """API 异常 —— 可在任意层抛��，由全局异常处理器捕获并转换为统一错误响应"""

    def __init__(self, message="操作失败", error_code="UNKNOWN_ERROR", status_code=400):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code

    def to_response(self):
        return api_error(self.message, self.error_code, self.status_code)

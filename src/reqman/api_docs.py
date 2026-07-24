"""API 规范文档 —— 为 AJAX 端点生成 OpenAPI 兼容的规范描述

遵循 YAGNI 原则：项目以服务端渲染为主，仅对纯 AJAX 数据端点提供文档。
不引入 flask-restx/flask-smorest 等重型依赖。
"""

from datetime import datetime

# ===================== 端点注册表 =====================

ENDPOINTS = {
    "cards": {
        "description": "工卡管理 API",
        "endpoints": [
            {
                "path": "/card/api/list",
                "method": "GET",
                "summary": "工具列表（分页+搜索+分类过滤）",
                "parameters": [
                    {"name": "search", "in": "query", "required": False, "schema": {"type": "string"}, "description": "搜索关键词（工卡号/名称）"},
                    {"name": "category", "in": "query", "required": False, "schema": {"type": "string"}, "description": "专业分类"},
                    {"name": "page", "in": "query", "required": False, "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "required": False, "schema": {"type": "integer", "default": 20, "maximum": 100}},
                ],
                "responses": {
                    "200": {
                        "description": "成功返回工卡列表",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "data": {
                                            "type": "object",
                                            "properties": {
                                                "items": {"type": "array", "items": {"$ref": "#/components/schemas/Card"}},
                                                "pagination": {
                                                    "type": "object",
                                                    "properties": {
                                                        "page": {"type": "integer"},
                                                        "per_page": {"type": "integer"},
                                                        "total": {"type": "integer"},
                                                        "total_pages": {"type": "integer"},
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            {
                "path": "/card/list-json",
                "method": "GET",
                "summary": "工卡列表 JSON（工卡组选择器使用）",
                "responses": {
                    "200": {
                        "description": "成功返回工卡数组",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "data": {"type": "array", "items": {"$ref": "#/components/schemas/CardSimple"}}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            {
                "path": "/card/<int:card_id>",
                "method": "GET",
                "summary": "工卡详情",
                "parameters": [
                    {"name": "card_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {"description": "返回工卡详情对象"},
                    "404": {"description": "工卡不存在"},
                }
            },
        ]
    },
    "packages": {
        "description": "工作包上传和匹配 API",
        "endpoints": [
            {
                "path": "/upload",
                "method": "POST",
                "summary": "上传工作清单（支持 AJAX）",
                "request_body": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "routine_file": {"type": "string", "format": "binary", "description": "例行工作清单 Excel"},
                                    "other_file": {"type": "string", "format": "binary", "description": "其他工作清单 Excel"},
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "上传成功"},
                    "400": {"description": "上传失败（无文件/格式错误/解析失败）"},
                }
            },
            {
                "path": "/packages/<package_id>/rematch",
                "method": "POST",
                "summary": "重新匹配工作包",
                "parameters": [
                    {"name": "package_id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {"description": "重新匹配完成"},
                    "404": {"description": "工作包不存在"},
                }
            },
        ]
    },
    "generate": {
        "description": "需求单生成 API",
        "endpoints": [
            {
                "path": "/generate",
                "method": "GET",
                "summary": "获取需求单预览（支持 AJAX）",
                "parameters": [
                    {"name": "package_id", "in": "query", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {"description": "返回预览数据"},
                    "400": {"description": "缺少 package_id"},
                    "404": {"description": "工作包不存在"},
                }
            },
            {
                "path": "/generate",
                "method": "POST",
                "summary": "生成并下载需求单 Excel",
                "parameters": [
                    {"name": "package_id", "in": "formData", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {"description": "返回 Excel 文件下载"},
                    "400": {"description": "参数错误"},
                }
            },
        ]
    }
}


# ===================== OpenAPI 组件定义 =====================

COMPONENTS = {
    "schemas": {
        "Card": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "task_code": {"type": "string", "description": "工卡号"},
                "task_name": {"type": "string", "description": "工卡名称"},
                "category": {"type": "string", "enum": ["发动机", "机体", "电子"]},
                "task_type": {"type": "string"},
                "set_id": {"type": "integer", "nullable": True, "description": "所属工卡组 ID"},
                "set_name": {"type": "string", "nullable": True},
                "tools": {"type": "array", "items": {"$ref": "#/components/schemas/ToolItem"}},
                "materials": {"type": "array", "items": {"$ref": "#/components/schemas/MaterialItem"}},
                "tools_confirmed": {"type": "boolean"},
                "materials_confirmed": {"type": "boolean"},
                "remark": {"type": "string"},
            }
        },
        "CardSimple": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "task_code": {"type": "string"},
                "task_name": {"type": "string"},
                "category": {"type": "string"},
            }
        },
        "ToolItem": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "工具名称"},
                "part_number": {"type": "string", "description": "件号"},
                "quantity": {"type": "string", "description": "数量"},
                "specification": {"type": "string", "description": "规格"},
            }
        },
        "MaterialItem": {
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "航材名称"},
                "part_number": {"type": "string", "description": "件号"},
                "quantity": {"type": "string", "description": "数量"},
                "usage_type": {"type": "string", "description": "用途类型"},
                "unit": {"type": "string", "description": "单位"},
            }
        },
    }
}


def get_openapi_spec():
    """生成 OpenAPI 3.0 规范 JSON"""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "需求单管理系统 API",
            "description": "工卡管理、工作包上传、需求单生成的 AJAX API 接口",
            "version": "1.0.0",
            "contact": {
                "name": "需求单管理团队",
            },
        },
        "servers": [
            {"url": "", "description": "当前服务器"},
        ],
        "paths": _build_paths(),
        "components": COMPONENTS,
        "tags": [
            {"name": "cards", "description": "工卡管理"},
            {"name": "packages", "description": "工作包管理"},
            {"name": "generate", "description": "需求单生成"},
        ],
    }


def _build_paths():
    """构建 OpenAPI paths 对象"""
    paths = {}
    for group in ENDPOINTS.values():
        for ep in group["endpoints"]:
            path_key = ep["path"]
            method = ep["method"].lower()
            path_item = paths.setdefault(path_key, {})
            path_item[method] = {
                "tags": [group["description"]],
                "summary": ep.get("summary", ""),
                "parameters": ep.get("parameters", []),
                "responses": ep.get("responses", {"200": {"description": "操作成功"}}),
            }
            if "request_body" in ep:
                path_item[method]["requestBody"] = ep["request_body"]
    return paths

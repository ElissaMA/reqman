"""AMRO 三域同步编排 — 飞机 / 工作包 / 工卡版本（只读、零快照）

所有 AMRO 调用经 connectors.amro.query_plugin（只读白名单 + 限速 + JSONL 审计）；
长任务由 run_query 包成 daemon 线程并写 QUERY_STATUS 内存态（running/done/error）；
全局查询互斥（try_begin_query）保证一次只跑一个 AMRO 查询，不排队。
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

# OUTPUT_DIR 通过包级属性运行时取值，以便测试 monkeypatch amro_sync.OUTPUT_DIR 生效
from reqman.services import amro_sync

logger = logging.getLogger(__name__)

BJ = ZoneInfo("Asia/Shanghai")

_query_lock = threading.Lock()
_running_query: dict | None = None
_query_token: str | None = None  # 持有者令牌：仅持令牌者能释放，防误释放/跨任务串扰
QUERY_STATUS: dict[str, dict] = {}

def _now() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")



def try_begin_query(label: str) -> str | None:
    """占用全局查询槽。成功返回令牌（释放时回传），失败返回 None（已有查询在跑，不排队）。"""
    global _running_query, _query_token
    got = _query_lock.acquire(blocking=False)
    if got:
        _query_token = secrets.token_hex(8)
        _running_query = {"label": label, "started_at": _now()}
        return _query_token
    return None



def end_query(token: str | None = None) -> None:
    """释放全局查询槽（仅持有者令牌可释放；无令牌调用兼容旧路径但需与当前令牌一致）。"""
    global _running_query, _query_token
    if token is not None and token != _query_token:
        return
    _running_query = None
    _query_token = None
    if _query_lock.locked():
        _query_lock.release()



def query_busy_message() -> str | None:
    """有查询在跑时返回统一提示文案；空闲返回 None。"""
    if _running_query:
        return (f"已有查询任务进行中：{_running_query['label']}"
                f"（{_running_query['started_at']}），请等待完成后再查询")
    return None


@contextmanager

def query_slot(label: str):
    """同步请求的查询槽上下文：进入时占用，退出时释放（持有令牌）。"""
    token = try_begin_query(label)
    if token is None:
        raise QueryBusyError(query_busy_message() or "已有查询任务进行中")
    try:
        yield
    finally:
        end_query(token)



class QueryBusyError(RuntimeError):
    """全局查询互斥冲突（已有查询在跑）。"""





def run_query(key: str, label: str, job, extra: dict | None = None) -> bool:
    """daemon 线程执行 job（占全局查询槽全程），QUERY_STATUS：running → done/error。

    extra 透传进每条状态记录（如 package_id），便于前端按标识恢复轮询。
    返回 False = 已有查询在跑（未启动）。
    """
    token = try_begin_query(label)
    if token is None:
        return False
    extra = extra or {}

    def runner():
        try:
            summary = job()
            QUERY_STATUS[key] = {"status": "done", "label": label,
                                 "finished_at": _now(), "summary": summary, **extra}
        except Exception as exc:
            logger.exception("AMRO 查询任务失败: %s", label)
            QUERY_STATUS[key] = {"status": "error", "label": label,
                                 "finished_at": _now(), "error": str(exc), **extra}
        finally:
            end_query(token)

    QUERY_STATUS[key] = {"status": "running", "label": label, "started_at": _now(), **extra}
    threading.Thread(target=runner, daemon=True, name=f"amro-{key}").start()
    return True



def get_query_status(key: str) -> dict:
    """读取某查询任务的内存状态（无记录返回空 dict）。"""
    return QUERY_STATUS.get(key, {})


# 最近一次查询结果简述持久化（output/last_query_<key>.json，重启保留）——
# 学习库存查询模式：每次查询结果可恢复显示在页面状态栏，报告类附下载链接。

def save_last_query_result(key: str, label: str, summary: str, download_url: str = "",
                           output_dir=None) -> None:
    """写入最近一次查询结果简述（只留最新一份）。"""
    out = output_dir or amro_sync.OUTPUT_DIR
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"last_query_{key}.json").write_text(json.dumps(
            {"label": label, "finished_at": _now(),
             "summary": summary, "download_url": download_url},
            ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.warning("查询结果简述写入失败: last_query_%s", key)



def get_last_query_result(key: str, output_dir=None) -> dict:
    """读取最近一次查询结果简述（无记录返回空 dict）。"""
    out = output_dir or amro_sync.OUTPUT_DIR
    path = out / f"last_query_{key}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}



def require_amro_session() -> bool:
    """AMRO 功能前置检查：仅 无凭证/明确失效 阻断；网络未知（probe_error）放行，
    避免偶发网络抖动/限流被误判未登录（真实失效由查询自身的 AMRO 调用暴露并 401）。"""
    from flask import current_app
    svc = current_app.extensions["inventory_service"]
    return svc.check_login_state() in ("valid", "probe_error")


# ---------- 飞机域 ----------

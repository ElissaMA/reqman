"""单实例锁 — 存储正确性依赖进程内 RLock，禁止多进程共写同一 JSON 库。

SERVER_README 约定 1 worker × 4 threads；误配多 worker gunicorn 或双开
start.bat 时，进程内锁失效会产生静默丢更新。本模块在 JsonStore 初始化时
对数据库路径加锁文件（含持有者 pid），检测到异进程持锁且存活即拒绝启动。

接管规则（覆盖以下情况不误伤）：
- 同进程重复创建 store：引用计数，不重复占锁
- 锁文件残留但持有进程已退出（崩溃遗留）：接管
- 锁文件损坏（非 JSON / 缺 pid）：视为无主，接管
- werkzeug debug reloader 子进程：接管（父进程是 watcher，不再触碰数据）
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_refs: dict[str, int] = {}          # db_path -> 本进程引用计数
_reg = threading.Lock()
_release_registered = False

_STILL_ACTIVE = 259                  # Windows GetExitCodeProcess 的存活哨兵


class InstanceLockError(RuntimeError):
    """数据库已被其他存活进程持有，拒绝启动。"""


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == _STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True    # 进程存在但属其他用户
    except OSError:
        return False


def _read_holder(lock_file: Path):
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        pid = data.get("pid")
        return pid if isinstance(pid, int) else None
    except (OSError, ValueError):
        return None


def _write_lock_exclusive(lock_file: Path, pid: int) -> bool:
    """排他创建锁文件；已存在返回 False（不覆盖）。

    用 O_CREAT|O_EXCL 让「创建」本身成为原子竞争点：并发启动时只有一方能成功，
    避免 exists→read→write 三步之间的 TOCTOU 窗口让两个进程都认为自己抢到锁。
    """
    payload = json.dumps(
        {"pid": pid, "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


def acquire(db_path: str) -> None:
    """对数据库路径加单实例锁；异进程持锁且存活时抛 InstanceLockError。"""
    global _release_registered
    with _reg:
        if _refs.get(db_path):
            _refs[db_path] += 1
            return
        lock_file = Path(db_path + ".lock")
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        current = os.getpid()
        reloader_child = bool(os.environ.get("WERKZEUG_RUN_MAIN"))

        # 最多重试 3 次：仅当旧锁持有者已死（可安全接管）时才删锁重抢。
        for _ in range(3):
            if _write_lock_exclusive(lock_file, current):
                break
            holder = _read_holder(lock_file)
            if (holder is not None and holder != current
                    and not reloader_child and _pid_alive(holder)):
                raise InstanceLockError(
                    f"数据库 {db_path} 已被进程 {holder} 使用。存储依赖单进程锁，"
                    f"请先停止另一实例；确认无实例运行时可删除 {lock_file} 后重启")
            # 同进程重入（holder == current）或僵尸锁：清掉后重试
            try:
                lock_file.unlink()
            except OSError:
                pass
        else:
            # 三轮都被他人抢占（且对方非存活进程，如反复创建失败）
            raise InstanceLockError(
                f"无法取得数据库 {db_path} 的单实例锁（{lock_file}）。"
                "请确认无其他实例运行后删除该文件再重启")

        _refs[db_path] = 1
        if not _release_registered:
            atexit.register(_release_all)
            _release_registered = True


def _release_all() -> None:
    with _reg:
        for path in list(_refs):
            _release(path)


def _release(db_path: str) -> None:
    lock_file = Path(db_path + ".lock")
    try:
        # 只清理自己持有且未被他人接管的锁
        if _read_holder(lock_file) == os.getpid():
            lock_file.unlink()
    except OSError:
        pass
    _refs.pop(db_path, None)


if __name__ == "__main__":  # pragma: no cover - 手工诊断用
    target = sys.argv[1] if len(sys.argv) > 1 else "data/reqman_db.json"
    lock_file = Path(target + ".lock")
    holder = _read_holder(lock_file) if lock_file.exists() else None
    if holder is None:
        print(f"{lock_file}: 无有效锁")
    else:
        print(f"{lock_file}: pid={holder} alive={_pid_alive(holder)}")

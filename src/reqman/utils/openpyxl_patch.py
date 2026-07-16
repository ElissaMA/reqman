"""openpyxl 猴子补丁 — 临时目录重定向 + 权限错误兜底

Windows 上杀软扫描可能导致 openpyxl 关闭工作簿时无法删除内部临时文件，
抛出 PermissionError 中断保存流程。此模块：
1. 将 tempfile.tempdir 指向项目内隐藏目录 .opxltmp/
2. 猴子补丁 WorksheetWriter.cleanup，吞掉清理异常
3. 每次启动时自动清空上次遗留的临时文件
"""

import os
import glob as _glob
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def apply_patches(base_dir: Path) -> None:
    """应用 openpyxl 临时目录重定向与清理异常补丁。

    Args:
        base_dir: 项目根目录（需求单v1.0/），.opxltmp 在此创建。
    """
    tmp_dir = base_dir / ".opxltmp"
    tmp_dir.mkdir(exist_ok=True)
    tempfile.tempdir = str(tmp_dir)

    # 启动时清空上次运行残留的临时文件
    for f in _glob.glob(str(tmp_dir / "*")):
        try:
            os.remove(f)
        except (PermissionError, OSError):
            pass

    # 猴子补丁：openpyxl WorksheetWriter.cleanup 吞掉清理异常
    try:
        import openpyxl.worksheet._writer as _oxl_writer

        _orig_cleanup = _oxl_writer.WorksheetWriter.cleanup

        def _patched_cleanup(self):
            try:
                _orig_cleanup(self)
            except (PermissionError, OSError):
                try:
                    self.out.close()
                except Exception:
                    pass
                _path = getattr(self.out, "name", None)
                if _path and os.path.exists(_path):
                    try:
                        os.remove(_path)
                    except (PermissionError, OSError):
                        pass
                try:
                    _oxl_writer.ALL_TEMP_FILES.remove(self.out)
                except (ValueError, AttributeError):
                    pass

        _oxl_writer.WorksheetWriter.cleanup = _patched_cleanup

        _orig_shutdown = _oxl_writer._openpyxl_shutdown

        def _patched_shutdown():
            try:
                _orig_shutdown()
            except (PermissionError, OSError):
                try:
                    _oxl_writer.ALL_TEMP_FILES.clear()
                except AttributeError:
                    pass

        _oxl_writer._openpyxl_shutdown = _patched_shutdown
    except Exception:
        pass

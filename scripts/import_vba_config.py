"""VBA 配置文件迁移入口：python scripts/import_vba_config.py <配置文件.xlsx>

用法：先停止服务，运行后启动服务在工卡管理页人工确认提醒类型。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reqman.config import DB_FILE
from reqman.models.json_store import JsonStore
from scripts.lib.import_vba_config import import_vba_config


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/import_vba_config.py <VBA配置文件.xlsx>")
        sys.exit(1)
    store = JsonStore(str(DB_FILE))
    result = import_vba_config(sys.argv[1], store)
    print(f"一般提醒更新: {result.general}")
    print(f"重点提醒更新: {result.key}")
    print(f"飞机新增/更新: {result.aircraft_added}/{result.aircraft_updated}")
    print(f"弃用工卡: {len(result.discarded)} 条 → output/vba_discard.txt")
    if result.discarded:
        for d in result.discarded[:20]:
            print(f"  {d}")
        if len(result.discarded) > 20:
            print(f"  ... 共 {len(result.discarded)} 条")


if __name__ == "__main__":
    main()
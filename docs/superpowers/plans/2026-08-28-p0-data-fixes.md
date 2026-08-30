# P0 数据修复实施计划（v3.4.5）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复双文件 JSON 存储层的 4 个数据级缺陷（next_id 落后静默覆盖、code_index 悬挂脏映射、原子写失败毁好文件、save_work_package 无锁）及 6 个中优缺陷，不改任何业务数据结构。

**Architecture:** 全部修复收敛在 `JsonStore` 读写路径上：`_read()` 每次调用时做派生自愈（next_id / code_index，µs 级），`_next_id()` 分配时跳过已存在 ID，`_write()` 失败即抛绝不覆盖好文件。并发模型改为服务器单进程（gunicorn -w1 -t4），现有 threading.Lock 即足够。

**Tech Stack:** Python 3.10 / Flask 3.1 / pytest（现有 37 个 store 用例为回归保障）

**Spec:** 本文档即规格；基线数据经 2026-08-28 服务器最新数据实证（用户已将本地数据替换为服务器最新数据，后续以本地数据+代码更新服务器）。

## Global Constraints

- 零迁移：不改实体键名/结构，cards/card_sets/aircraft/card_logs/work_packages 内容不变
- 自愈幂等，修复前后核心文件逐项 diff 仅允许 runtime 文件的 next_id/code_index 两键变化
- 版本 3.4.5；提交风格 `fix: v3.4.5 ...`；每任务独立 commit
- 遵循项目 ponytail 原则：不加新文件（无 filelock/atomic/repair 模块），根因单点修复

## 基线（实证于替换后的服务器数据）

| 项 | 值 |
|---|---|
| runtime `next_id` | 1032（实体已占 1028-1036 → 落后，下次创建覆盖 1032） |
| code_index 脏映射 | `CSCA320-783200-W1-1-1 → 1023`，而卡 1023 = `EOJC-A320-57-2025-002-B`（原卡已删，索引悬挂） |
| card_logs | 264 条 > 裁剪阈值 200（启动将删 64 条） |
| `next_ac_id` | 134 死键，全库唯一引用点是其定义（json_store.py:57） |

---

### Task 1: next_id 自愈 + 分配守卫

**Files:**
- Modify: `src/reqman/models/json_store.py`（`_read`、`_next_id`、add/add_set/add_aircraft 调用点不变）
- Test: `tests/test_json_store.py`

- [x] **Step 1: 写失败测试**

```python
class TestNextIdHeal:
    def test_next_id_lag_does_not_overwrite(self, tmp_path):
        """next_id 落后于现存实体时，新增不得覆盖现有实体"""
        import json
        db_path = str(tmp_path / "lag.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({
                "next_id": 1032,
                "cards": {str(i): {"id": i, "task_code": f"C-{i}"} for i in range(1028, 1033)},
                "card_sets": {str(i): {"id": i, "name": f"S-{i}"} for i in range(1033, 1037)},
                "aircraft": {},
            }, f)
        store = JsonStore(db_path)
        r = store.add("NEW-001", "新卡", "机体", "", "")
        assert r["id"] == 1037
        # 现有实体原样保留
        assert store.get(1032)["task_code"] == "C-1032"
        assert store.get_set(1036)["name"] == "S-1036"
```

- [x] **Step 2: 跑红** `pytest tests/test_json_store.py::TestNextIdHeal -v`（预期 FAIL：返回 id=1032 覆盖现有卡）
- [x] **Step 3: 最小实现**：`_read()` 末尾加计数器自愈（重算 max）；`_next_id(db)` 内部跳过 cards/card_sets/aircraft 已占 ID
- [x] **Step 4: 跑绿** + 全量 pytest
- [x] **Step 5: Commit** `fix: v3.4.5 next_id落后自愈+分配跳过已占ID，杜绝静默覆盖`

### Task 2: code_index 双向校验自愈

**Files:** Modify `json_store.py`（`_read/_write` 的条数检查 → `_index_ok()`；`_rebuild_index` 容错缺码卡）; Test `tests/test_json_store.py`

- [x] **Step 1: 失败测试**

```python
class TestIndexHeal:
    def test_dirty_index_heals_on_read(self, tmp_path):
        """悬挂索引（指向 task_code 不匹配的卡）读取即自愈"""
        import json
        db_path = str(tmp_path / "dirty.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({
                "next_id": 2,
                "cards": {"1": {"id": 1, "task_code": "REAL-CODE"}},
                "code_index": {"GHOST-CODE": 1, "REAL-CODE": 1},
            }, f)
        store = JsonStore(db_path)
        assert store.find_by_code("GHOST-CODE") is None
        assert store.find_by_code("REAL-CODE")["id"] == 1
        store.update(1, task_name="触发写入")   # 写后索引自愈持久化
        with open(str(tmp_path / "dirty_runtime.json"), encoding="utf-8") as f:
            assert "GHOST-CODE" not in json.load(f).get("code_index", {})

    def test_index_missing_rebuilt(self, tmp_path):
        import json
        db_path = str(tmp_path / "noidx.json")
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump({"cards": {"1": {"id": 1, "task_code": "C-001"}}}, f)
        store = JsonStore(db_path)
        assert store.find_by_code("C-001")["id"] == 1
```

- [x] **Step 2: 跑红**（GHOST-CODE 命中错误卡；runtime 中仍含 GHOST-CODE）
- [x] **Step 3: 实现 `_index_ok()` 双向校验替换两处 `len(ci) < len(cards)`；`_rebuild_index` 用 `.get("task_code")` 跳过缺码卡并对重复码 warning**
- [x] **Step 4: 跑绿 + 全量**
- [x] **Step 5: Commit** `fix: v3.4.5 code_index双向校验自愈，清除悬挂/错映射`

### Task 3: 原子写失败不毁好文件

**Files:** Modify `json_store.py:25-39`、`session.py:17-30`（删直接覆盖 fallback → 抛原异常）

- [x] **Step 1: 失败测试**

```python
class TestAtomicWriteFailure:
    def test_write_failure_keeps_target(self, json_store, monkeypatch):
        """os.replace 失败时目标文件必须原样保留且抛异常（而非被截断覆盖）"""
        import json as _json
        import pytest
        import reqman.models.json_store as jsm
        r = json_store.add("SAFE-001", "卡", "发动机", "A", "")
        db_path = json_store._path
        good = _json.load(open(db_path, encoding="utf-8"))

        def boom(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(jsm.os, "replace", boom)
        with pytest.raises(OSError):
            json_store.add("SAFE-002", "卡2", "发动机", "A", "")
        monkeypatch.undo()
        after = _json.load(open(db_path, encoding="utf-8"))
        assert after["cards"] == good["cards"]  # 好文件未被截断/覆盖
```

- [x] **Step 2: 跑红**（当前 fallback 直接覆盖目标 → 文件内容变化且不抛错）
- [x] **Step 3: 两处 `_atomic_write` 删除 fallback，失败清理 .tmp 后 `raise`**
- [x] **Step 4: 跑绿 + 全量**
- [x] **Step 5: Commit** `fix: v3.4.5 原子写失败不再覆盖目标文件(json_store+session)`

### Task 4: save_work_package 加锁 + 编辑撞号查重

**Files:** Modify `json_store.py`（save_work_package 加 `with self._lock`；`update()` 撞号 raise ValueError）、`card_service.py`（update_card 捕获 ValueError → ServiceError）; Test `tests/test_json_store.py`、`tests/integration/test_card_api.py`

- [x] **Step 1: 失败测试**

```python
class TestWriteConsistency:
    def test_save_work_package_threaded_no_loss(self, tmp_path):
        import threading
        from reqman.models.json_store import JsonStore
        store = JsonStore(str(tmp_path / "wp.json"))
        def save(i):
            store.save_work_package({"reg": f"B-{i:04d}", "description": "d", "date": "2026.08.28"})
        ts = [threading.Thread(target=save, args=(i,)) for i in range(10)]
        [t.start() for t in ts]; [t.join() for t in ts]
        assert len(store.get_work_packages()) == 10

    def test_update_duplicate_code_rejected(self, json_store):
        import pytest
        a = json_store.add("CODE-A", "卡A", "机体", "", "")
        b = json_store.add("CODE-B", "卡B", "机体", "", "")
        with pytest.raises(ValueError):
            json_store.update(b["id"], task_code="CODE-A")
        assert json_store.get(b["id"])["task_code"] == "CODE-B"  # 拒绝且无副作用
```

集成用例（`tests/integration/test_card_api.py` 追加）：POST `/card/<id>/edit` 提交已存在的 task_code → 响应含 "已存在"，库中两卡 task_code 不变。

- [x] **Step 2: 跑红**
- [x] **Step 3: 实现**（update(): 变更索引前检查 `code_index.get(new_code)` 属于其他卡则 raise；card_service.update_card 包装为 ServiceError）
- [x] **Step 4: 跑绿 + 全量**
- [x] **Step 5: Commit** `fix: v3.4.5 work_package加锁+编辑工卡号查重(堵脏索引源头)`

### Task 5: 备份补齐 runtime 文件

**Files:** Modify `json_store.py`（.bak 双文件）、`app.py`（atexit 双文件+项目根绝对路径）、`scripts/auto_backup.sh`、`scripts/db.sh`

- [x] Step 1: `json_store._write` 备份段改为对 `_path` 与 `_runtime_path` 各留 `.bak`
- [x] Step 2: `app.py:_backup_on_exit` 改为基于 `Path(__file__)` 的项目根绝对路径，备份 core+runtime 两个 gzip，清理 glob 同时覆盖两模式
- [x] Step 3: `auto_backup.sh` 增加 runtime 行；`db.sh` backup/restore/safety 覆盖 runtime（按时间戳配对恢复，缺 runtime 备份则告警跳过——计数器/索引可自愈）
- [x] Step 4: 本地手工跑 `bash scripts/db.sh backup && bash scripts/db.sh list` 核对 4 个文件产物
- [x] Step 5: Commit `fix: v3.4.5 备份体系补齐runtime文件(计数器回退根因闭环)`

### Task 6: 读损坏拒绝写

**Files:** Modify `json_store.py`（`_read` 置 `_corrupt` 标志；`_write` 检查即 raise；`_init_db` 紧急重建路径先清标志）

- [x] **Step 1: 失败测试**

```python
class TestCorruptRefuseWrite:
    def test_corrupt_runtime_refuses_write(self, json_store):
        import json as _json
        import pytest
        json_store.add("CORR-001", "卡", "机体", "", "")
        rt = json_store._runtime_path
        open(rt, "w", encoding="utf-8").write("{corrupted")
        with pytest.raises(RuntimeError):
            json_store.add("CORR-002", "卡2", "机体", "", "")
        # 核心文件未被半张库覆盖
        core = _json.load(open(json_store._path, encoding="utf-8"))
        assert "CORR-002" not in [c["task_code"] for c in core["cards"].values()]
```

- [x] **Step 2: 跑红**（当前只 warning，写入把残缺库合法化）
- [x] **Step 3: 实现**（`_read` 开头清标志、读失败置位；`_write` 开头检查 raise RuntimeError；`_init_db` 两个 `_write(_EMPTY_DB)` 紧急路径前 `self._corrupt = False`）
- [x] **Step 4: 跑绿 + 全量**
- [x] **Step 5: Commit** `fix: v3.4.5 读损坏时拒绝写入，防止残缺库被合法化`

### Task 7: 中优快修打包

**Files:** Modify `packages_bp.py:157`、`json_store.py get_all/next_ac_id`、`card_service.py` 飞机校验、`__init__.py:113`

- [x] Step 1: 失败测试：`test_get_all_missing_key_safe`（手工写缺 task_code 的卡文件 → get_all 不 500）、`test_aircraft_reg_dup_and_required`（service 层：reg 重复/空 → ServiceError）、集成：上传工作包 AJAX 响应 `data.package_id` 非空（沿用 test_workflow 的 xlsx 构造）
- [x] Step 2: 跑红
- [x] Step 3: 实现：`package_data.get("package_id")`；`get_all` 两处 `card["task_code"]` → `.get("task_code", "")`；`_RUNTIME_KEYS` 删 `next_ac_id` + `_read` 中 `db.pop("next_ac_id", None)`；`add_aircraft`/`update_aircraft` 加 reg 空与重复校验（ServiceError）；`trim_logs(max_count=200)` → `2000`
- [x] Step 4: 跑绿 + 全量
- [x] Step 5: Commit `fix: v3.4.5 中优快修(包ID回传/get_all容错/死键清理/机号查重/日志阈值)`

### Task 8: 部署配置单进程化

**Files:** Modify `config/reqman.service`

- [x] Step 1: `--workers 4 --threads 2` → `--workers 1 --threads 4`（`# ponytail:` 注释写入 CHANGELOG：单进程下 threading.Lock 即够；未来确需多 worker 再加 fcntl/msvcrt 文件锁）
- [x] Step 2: Commit `chore: v3.4.5 服务器gunicorn单进程化，消除跨进程写竞争`

### Task 9: 版本号统一 + CHANGELOG

**Files:** Modify `pyproject.toml`（3.4.3→3.4.5）、`README.md` 标题、`app.py:162`、`start.bat`、`start.sh` 横幅（V3.2.5→V3.4.5）、`CHANGELOG.md` 新条目

- [x] Step 1: CHANGELOG v3.4.5：Fixed 清单（T1-T7）+ Changed（T8）+ **服务器更新步骤**（本地自愈验证 → scp data/*.json → git pull + 重启 gunicorn → 核对自愈日志）+ 遗留问题清单 ≤10 行
- [x] Step 2: 全部版本字符串统一 3.4.5
- [x] Step 3: Commit `chore: v3.4.5 版本号统一+变更记录`

## 收尾验证

1. `pytest` 全量（37 旧 + ~10 新）+ `ruff check .` 通过
2. 启动 `python src/reqman/app.py`：日志出现自愈信息（next_id 1032→1037、索引重建），264 条日志完整
3. 数据零变化 diff：自愈前后核心文件 cards/sets/aircraft/logs 键数一致，runtime 仅 next_id/code_index 变化
4. 冒烟：新建工卡 id=1037 不覆盖、编辑撞号 400 提示、上传 AJAX 返回 package_id

## 明确不做（各留一行升级路径）

- 文件锁模块：确需多 worker 时加 fcntl/msvcrt
- repair 脚本：自愈已随 _read 生效，无需独立脚本
- 状态判定三处收敛重构：下次触碰匹配逻辑时顺手收敛到 work_package_matcher
- 版本动态机制 / 日志配置化：字符串再改一次的成本低于机制维护
- 大规模爬取架构、工卡版本(revision)提醒：未来专项

## Self-Review

- 规格覆盖：基线 4 个 P0 + 6 个中优 → T1-T7 一一对应；T8/T9 为配套。✓
- 占位符扫描：无 TBD/TODO；所有测试代码已具名。✓
- 类型一致性：`_next_id(db)` 保持原签名（内部固定检查三类集合）；`_index_ok(db)` 仅被 `_read/_write` 调用；ServiceError 包装链 json_store.ValueError → card_service.ServiceError → cards_bp 400。✓

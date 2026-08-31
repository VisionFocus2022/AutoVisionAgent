# SAM3 权重约定目录自动发现 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 无 `AVA_SAM3_DIR` 环境变量时，SAM 标注自动加载仓库约定目录 `weights/sam3` 的 SAM3 权重，不再弹权重选择框。

**Architecture:** 扩展纯函数 `resolve_sam3_model_dir` 增第三优先级参数 `conventional_dir`（判断序 env → conventional → picked）；`core/constants.py` 新增公开常量 `WEIGHTS_DIR`；`sam_session._ensure_sam` 两处调用传入约定路径并记日志。UI 层状态文案与弹窗兜底零改动。

**Tech Stack:** Python 3.12 / PySide6 / pytest（单测 + uiautomation 真窗）

**Spec:** `docs/superpowers/specs/2026-08-31-sam3-auto-discovery-design.md`

**注记:** 计划含 git commit 步骤（superpowers 流程惯例）；实际执行时须先获用户对提交的显式确认（项目规则：不自动 commit）。

---

### Task 1: `core/constants.py` 新增 WEIGHTS_DIR

**Files:**
- Modify: `core/constants.py:24-37`（CONFIG_DIR 之后 + __all__）

- [ ] **Step 1: 加常量与导出**

在 `core/constants.py` 的 `CONFIG_DIR = _PROJECT_ROOT / "configs"` 之后插入：

```python
# 权重目录（SAM3 约定发现基准：源码=仓库根/weights，frozen exe=_internal/weights）
WEIGHTS_DIR = _PROJECT_ROOT / "weights"
```

并把 `__all__` 列表补一行（按字母序插在 `"IMG_EXTS"` 前）：

```python
__all__ = [
    "IMG_EXTS",
    "ANN_EXTS",
    "CONFIG_DIR",
    "WEIGHTS_DIR",
    "DEFAULT_PROJECT_ROOT",
    "DEFAULT_PROJECT_ROOT_TILDE",
]
```

- [ ] **Step 2: 验证可导入**

Run: `.venv/Scripts/python.exe -c "from core.constants import WEIGHTS_DIR; print(WEIGHTS_DIR)"`
Expected: 输出 `<仓库根>\weights`（绝对路径）

- [ ] **Step 3: Commit**

```bash
git add core/constants.py
git commit -m "feat: WEIGHTS_DIR 公开常量（SAM3 约定发现基准）"
```

---

### Task 2: `resolve_sam3_model_dir` 增 conventional_dir 第三优先级（TDD）

**Files:**
- Modify: `gui/pages/label/sam_session.py:28-45`
- Test: `tests/test_sam3_adapter.py`（TestResolveSam3Dir 类内追加，L275-306 区域）

- [ ] **Step 1: 写失败测试（先跑见红）**

在 `tests/test_sam3_adapter.py` 的 `TestResolveSam3Dir` 类内（`test_picked_pth_is_not_sam3` 之后）追加 6 个用例：

```python
    def test_conventional_valid_dir(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / "model.safetensors").write_bytes(b"x")
        assert resolve_sam3_model_dir(
            None, None, conventional_dir=tmp_path
        ) == str(tmp_path)

    def test_conventional_missing_safetensors_skipped(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        # 无 model.safetensors → 不命中
        assert resolve_sam3_model_dir(
            None, None, conventional_dir=tmp_path
        ) is None

    def test_conventional_missing_config_skipped(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        (tmp_path / "model.safetensors").write_bytes(b"x")
        assert resolve_sam3_model_dir(
            None, None, conventional_dir=tmp_path
        ) is None

    def test_env_overrides_conventional(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        env_dir = tmp_path / "env_dir"
        conv_dir = tmp_path / "conv_dir"
        for d in (env_dir, conv_dir):
            d.mkdir()
            (d / "config.json").write_text("{}", encoding="utf-8")
            (d / "model.safetensors").write_bytes(b"x")
        assert resolve_sam3_model_dir(
            str(env_dir), None, conventional_dir=conv_dir
        ) == str(env_dir)

    def test_conventional_overrides_picked(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        conv_dir = tmp_path / "conv_dir"
        conv_dir.mkdir()
        (conv_dir / "config.json").write_text("{}", encoding="utf-8")
        (conv_dir / "model.safetensors").write_bytes(b"x")
        # picked 指向另一个有效 config.json，但 conventional 优先
        other = tmp_path / "other"
        other.mkdir()
        (other / "config.json").write_text("{}", encoding="utf-8")
        (other / "model.safetensors").write_bytes(b"x")
        assert resolve_sam3_model_dir(
            None, other / "config.json", conventional_dir=conv_dir
        ) == str(conv_dir)

    def test_conventional_none_keeps_two_arg_behavior(self, tmp_path):
        from gui.pages.label.sam_session import resolve_sam3_model_dir

        # conventional_dir=None（缺省）→ 行为与两参版完全一致
        picked = tmp_path / "config.json"
        picked.write_text("{}", encoding="utf-8")
        (tmp_path / "model.safetensors").write_bytes(b"x")
        assert resolve_sam3_model_dir(None, picked) == str(tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sam3_adapter.py -k "conventional or overrides" -o addopts= -q`
Expected: **6 failed**（`TypeError: resolve_sam3_model_dir() got an unexpected keyword argument 'conventional_dir'`）

- [ ] **Step 3: 实现——重构 resolve 与提取 helper**

`gui/pages/label/sam_session.py` 中，将现有 `resolve_sam3_model_dir`（L28-45）整体替换为：

```python
def _is_sam3_dir(p: Path) -> bool:
    """SAM3 模型目录有效性（config.json + model.safetensors 同目录）。"""
    return (
        p.is_dir()
        and (p / "config.json").is_file()
        and (p / "model.safetensors").is_file()
    )


def resolve_sam3_model_dir(
    env_value: str | None,
    picked_path: str | Path | None,
    conventional_dir: str | Path | None = None,
) -> str | None:
    """SAM3 模型目录解析（纯函数，W46；2026-08-31 增约定目录第三优先级）。

    判断顺序（参数序保持 env/picked 原位不动）：
    - AVA_SAM3_DIR 指向有效目录 → 该目录（显式指定，可指向微调版）；
    - conventional_dir（约定目录，如 WEIGHTS_DIR/sam3）有效 → 该目录；
    - picked 为 config.json 且同目录有 model.safetensors → 其父目录；
    - 其余 → None（回落弹窗）。
    """
    if env_value and Path(env_value).is_dir():
        return str(Path(env_value))
    if conventional_dir is not None and _is_sam3_dir(Path(conventional_dir)):
        return str(Path(conventional_dir))
    if picked_path is not None and Path(picked_path).name == "config.json":
        parent = Path(picked_path).parent
        if _is_sam3_dir(parent):
            return str(parent)
    return None
```

- [ ] **Step 4: 跑全类测试确认全绿**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sam3_adapter.py -o addopts= -q`
Expected: **全 passed**（既有 5 用例 + 新 6 用例；既有 `test_picked_config_json_with_safetensors` 走 `_is_sam3_dir` 等价路径不红）

- [ ] **Step 5: Commit**

```bash
git add gui/pages/label/sam_session.py tests/test_sam3_adapter.py
git commit -m "feat: resolve_sam3_model_dir 增约定目录第三优先级（env→conventional→picked）"
```

---

### Task 3: `_ensure_sam` 接线约定目录 + 来源日志

**Files:**
- Modify: `gui/pages/label/sam_session.py:15-27`（imports）、`L51-83`（_ensure_sam）

- [ ] **Step 1: 加 imports 与模块级约定路径**

文件顶部（`from gui.widgets.file_dialog import pick_open_file` 之后）加：

```python
import logging

from core.constants import WEIGHTS_DIR

_logger = logging.getLogger(__name__)

# SAM3 约定发现目录（源码=仓库根/weights/sam3；frozen exe=_internal/weights/sam3）
_SAM3_CONVENTIONAL_DIR = WEIGHTS_DIR / "sam3"
```

（`import logging` 并入现有 import 区按 isort 顺序放置。）

- [ ] **Step 2: 两处调用传入 conventional 并记日志**

`_ensure_sam` 中第一处（原 L61-63）：

```python
        sam3_dir = resolve_sam3_model_dir(
            os.environ.get("AVA_SAM3_DIR"), None, _SAM3_CONVENTIONAL_DIR
        )
        if sam3_dir:
            _logger.info("SAM3 权重来源: %s", sam3_dir)
            self._load_sam3(sam3_dir)
            return
```

第二处（原 L80-83，弹窗选中后）：

```python
        sam3_dir = resolve_sam3_model_dir(
            None, Path(ckpt), _SAM3_CONVENTIONAL_DIR
        )
        if sam3_dir:
            _logger.info("SAM3 权重来源: %s", sam3_dir)
            self._load_sam3(sam3_dir)
            return
```

（第二处日志在弹窗路径冗余但统一——来源追踪一条格式。）

- [ ] **Step 3: 语法 + lint 验证**

Run: `.venv/Scripts/python.exe -m ruff check gui/pages/label/sam_session.py && .venv/Scripts/python.exe -m py_compile gui/pages/label/sam_session.py`
Expected: `All checks passed!`

- [ ] **Step 4: resolve 单测回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sam3_adapter.py -o addopts= -q`
Expected: 全 passed

- [ ] **Step 5: Commit**

```bash
git add gui/pages/label/sam_session.py
git commit -m "feat: _ensure_sam 接线 WEIGHTS_DIR/sam3 约定发现——无 env 时静默加载不弹窗"
```

---

### Task 4: UIA 真窗用例——无 env 自动发现

**Files:**
- Modify: `tests/uia/test_sam3_labeling_deep.py`（追加第 4 用例）

**前置说明（关键坑）:** exe 模式下 `_PROJECT_ROOT` 指向 `dist/AutoVisionAgent/_internal`，约定目录 `_internal/weights/sam3` 当前**不存在**（exe 分发不带权重）→ 自动发现不命中会落弹窗卡死用例。故本用例：python 源码模式实跑；exe 模式在无 `_internal/weights/sam3` 时 skip（权重随包分发后自然放开——与既有模块级探测同款先例）。另外 env 必须在 `ava_app` 启动**前**删除（子进程继承 os.environ，启动后删无效）——用自定义夹具放参数首位（W25 实例化序教训）。

- [ ] **Step 1: 追加夹具与用例**

在 `tests/uia/test_sam3_labeling_deep.py` 的 `sam3_weights_env` 夹具之后加：

```python
@pytest.fixture()
def no_sam3_env(monkeypatch):
    """删除 AVA_SAM3_DIR（须先于 ava_app 实例化——子进程启动时继承 env）。"""
    monkeypatch.delenv("AVA_SAM3_DIR", raising=False)
```

在文件末尾（`test_sam3_next_image_rewarm_and_roundtrip` 之后）追加：

```python
def test_sam3_auto_discovery_no_env(
    no_sam3_env, ava_app, pole_subset_dir, workspace_dir
):
    """约定目录自动发现：unset AVA_SAM3_DIR + weights/sam3 在场 → 交互式
    直接就绪（不弹权重选择框）→ 点击提交产 polygon（真窗铁证）。

    exe 模式需 _internal/weights/sam3（权重随包分发后放开）；python 源码
    模式约定目录=仓库根/weights/sam3。
    """
    if os.environ.get("AVA_UIA_SOURCE", "exe").lower() != "python":
        exe_conv = (
            _REPO_ROOT / "dist" / "AutoVisionAgent" / "_internal"
            / "weights" / "sam3"
        )
        if not (exe_conv / "model.safetensors").is_file():
            pytest.skip(
                f"exe 模式约定目录无权重: {exe_conv}"
                "（权重随包分发后放开；本用例请用 AVA_UIA_SOURCE=python 跑）"
            )
    if not (_SAM3_WEIGHTS / "model.safetensors").is_file():
        pytest.skip(f"约定目录无 SAM3 权重: {_SAM3_WEIGHTS}")

    win = ava_app
    _ensure_logged_in(win)
    _open_label_folder(win, pole_subset_dir)
    _set_label_edit(win, "sam3auto")
    # 无 env 也不弹窗——直接走约定目录加载并就绪
    base = _enter_interactive_ready(win)

    assert _canvas_click(win, 0.5, 0.5), "画布单击失败（find timeout）"
    time.sleep(T_INFER)
    _canvas_commit(win)
    assert _wait_count(win, base + 1, timeout=8.0), (
        f"自动发现会话提交应 +1（base={base}，最后='{_last_status(win)}'）"
    )

    doc = _save_and_read_json(
        win, workspace_dir / "labels", "sam3_auto_discovery.json"
    )
    shapes = doc.get("shapes", [])
    assert len(shapes) >= 1, f"应 ≥1 shape，实际 {len(shapes)}"
    assert all(s.get("label") == "sam3auto" for s in shapes), (
        f"label 应为 'sam3auto': {[s.get('label') for s in shapes]}"
    )
    _assert_min_geometry(doc, "自动发现")
    logger.info("约定目录自动发现铁证通过: %d shapes", len(shapes))
```

- [ ] **Step 2: lint + 语法**

Run: `.venv/Scripts/python.exe -m ruff check tests/uia/test_sam3_labeling_deep.py`
Expected: `All checks passed!`

- [ ] **Step 3: python 源码模式实跑该用例**

Run: `AVA_UIA_SOURCE=python .venv/Scripts/python.exe -m pytest tests/uia/test_sam3_labeling_deep.py::test_sam3_auto_discovery_no_env -o addopts= --timeout=600 -v`
（Git Bash 语法；PowerShell 用 `$env:AVA_UIA_SOURCE='python'; ...`）
Expected: **PASSED**（~80-120s：启动+约定目录加载+点击+保存）

- [ ] **Step 4: exe 模式确认 skip 行为**

Run: `.venv/Scripts/python.exe -m pytest tests/uia/test_sam3_labeling_deep.py::test_sam3_auto_discovery_no_env -o addopts= -v`
Expected: **SKIPPED**（exe 模式且 `_internal/weights/sam3` 不存在）

- [ ] **Step 5: Commit**

```bash
git add tests/uia/test_sam3_labeling_deep.py
git commit -m "test: UIA 自动发现真窗用例（无 env 直接就绪 + polygon 铁证）"
```

---

### Task 5: 全量回归 + 手动验收

**Files:** 无新改动（验证任务）

- [ ] **Step 1: 主门禁全量**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 全 passed（≈1216+，tests/uia 默认排除不受影响）

- [ ] **Step 2: UIA 既有 SAM3 用例回归（exe 模式，env 注入路径不红）**

Run: `.venv/Scripts/python.exe -m pytest tests/uia/test_sam3_labeling.py -o addopts= --timeout=900 -v`
Expected: 3 passed（既有三用例走 sam3_weights_env 注入，不受接线影响）

- [ ] **Step 3: 手动验收（用户原始场景闭环）**

启动 `dist/AutoVisionAgent/AutoVisionAgent.exe` → 标注页 → 打开任意图像 → 点"交互式"：
- **当前 exe（_internal 无 weights）**：仍弹权重选择框（与今天一致，无回归）
- 验证 python 源码路径已由 Step 3 of Task 4 的 UIA 用例闭环

（exe 侧静默加载需权重随包分发——将 `weights/sam3` 复制到 `dist/AutoVisionAgent/_internal/weights/sam3` 后同样生效，属后续发布决策，不在本计划内。）

- [ ] **Step 4: 若有修复则 commit**

```bash
git status   # 确认无意外改动
```

---

## Self-Review 记录

1. **Spec 覆盖**：§3 变更清单 4 行 ↔ Task 1（constants）/ Task 2（resolve+单测）/ Task 3（接线+日志）/ Task 4（UIA 用例）一一对应；§5 回归 ↔ Task 5。§6 风险（exe 落弹窗）在 Task 4 前置说明与 Task 5 Step 3 显式承接。✓
2. **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码。✓
3. **类型一致性**：`resolve_sam3_model_dir(env_value, picked_path, conventional_dir)` 三参与 Task 2 实现/测试、Task 3 调用一致；`_is_sam3_dir(Path)` 一致；`WEIGHTS_DIR`/`_SAM3_CONVENTIONAL_DIR` 命名统一。✓

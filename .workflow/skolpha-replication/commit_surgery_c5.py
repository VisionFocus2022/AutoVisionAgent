# -*- coding: utf-8 -*-
"""C5 (W58) 前向重建。一次性使用。"""
from pathlib import Path


def rep(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == count, f"{path}: old 出现 {s.count(old)} 次（预期 {count}）"
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("OK", path)


# 1. binding.py → W58 版（回退复核 mkstemp——固定 tmp 名版本）
rep("project/binding.py",
    '''def write_binding(project_root: str | Path, binding: ProjectBinding) -> None:
    """原子写入项目绑定（mkstemp + os.replace；失败上抛 OSError 由调用方处理）。

    复核 LOW 修正：临时文件用 mkstemp 随机名（固定 .tmp 名在并发
    create_project/update_binding 下互踩——batch_tools.atomic_write_json
    已论证并升为全仓单源纪律，此处对齐）。
    """
    import tempfile

    path = binding_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_file": binding.model_file,
        "threshold": binding.threshold,
        "transfer_type": binding.transfer_type,
        "data_path": binding.data_path,
    }
    fd, tmp = tempfile.mkstemp(
        prefix="binding.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            _logger.warning("绑定临时文件清理失败: %s", tmp, exc_info=True)
        raise''',
    '''def write_binding(project_root: str | Path, binding: ProjectBinding) -> None:
    """原子写入项目绑定（temp + os.replace；失败上抛 OSError 由调用方处理）。"""
    path = binding_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_file": binding.model_file,
        "threshold": binding.threshold,
        "transfer_type": binding.transfer_type,
        "data_path": binding.data_path,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)''')

# 2. predict/page.py → W58 态（+_load_model_from 抽取，void 版）
rep("gui/pages/predict/page.py",
    '''    def _load_model(self) -> None:
        """加载模型权重。"""
        path = pick_open_file(
            self, "选择模型权重",
            "Weights (*.pt *.pth *.onnx *.ckpt)"
        )
        if not path:
            return
        self._model_path = path
        task = self.cmb_task.currentData()''',
    '''    def _load_model(self) -> None:
        """加载模型权重（对话框入口）。"""
        path = pick_open_file(
            self, "选择模型权重",
            "Weights (*.pt *.pth *.onnx *.ckpt)"
        )
        if not path:
            return
        self._load_model_from(path)

    def _load_model_from(self, path: str) -> None:
        """从指定路径加载模型权重（W58-A：工程绑定「从项目带入」共用入口）。"""
        self._model_path = path
        task = self.cmb_task.currentData()''')

# 3. batch_actions.py → W58 版（W56 版 + 绑定接线；无复核 bool）
rep("gui/pages/predict/batch_actions.py",
    '''        # W58-A（工程绑定）接线位：predictionParams{modelFile, threshold} 带入
        self.btn_from_project = QPushButton(tr("从项目带入"), bar)
        self.btn_from_project.setProperty("tool", True)
        self.btn_from_project.setEnabled(False)
        self.btn_from_project.setToolTip(tr("工程绑定后启用（预测参数带入）"))
        h.addWidget(self.btn_from_project)

    def batch_mode_value(self) -> str:''',
    '''        # W58-A（工程绑定 FR-005）：带入 predictionParams{modelFile, threshold}
        # 按钮常启——无项目时点击走「请先选择项目」诚实报错（不玩 MRO 遮蔽）
        self.btn_from_project = QPushButton(tr("从项目带入"), bar)
        self.btn_from_project.setProperty("tool", True)
        self.btn_from_project.clicked.connect(self._bring_from_project)
        h.addWidget(self.btn_from_project)

        self.btn_save_binding = QPushButton(tr("保存绑定"), bar)
        self.btn_save_binding.setProperty("tool", True)
        self.btn_save_binding.clicked.connect(self._save_binding)
        h.addWidget(self.btn_save_binding)

    def _bring_from_project(self) -> None:
        """从项目绑定带入模型与阈值（predictionParams 对标）。"""
        import os as _os

        from project.binding import read_binding

        if not self._project_dir:
            self.status_changed.emit(tr("请先选择项目"), "!")
            return
        binding = read_binding(self._project_dir)
        if not binding.model_file or not _os.path.exists(binding.model_file):
            self.status_changed.emit(
                tr("工程未绑定模型"),
                tr("请先在项目中训练模型或手动保存绑定"),
            )
            return
        self._load_model_from(binding.model_file)
        if binding.threshold is not None:
            self.spin_threshold.setValue(binding.threshold)
        self.status_changed.emit(
            tr("已从项目带入"), _os.path.basename(binding.model_file)
        )

    def _save_binding(self) -> None:
        """把当前模型+阈值存入项目绑定（读改写保留 transferType/dataPath）。"""
        from project.binding import update_binding

        if not self._project_dir:
            self.status_changed.emit(tr("请先选择项目"), "!")
            return
        try:
            update_binding(
                self._project_dir,
                model_file=self._model_path or "",
                threshold=self._threshold(),
            )
        except OSError as exc:
            self.status_changed.emit(tr("保存绑定失败"), str(exc)[:40])
            return
        self.status_changed.emit(tr("已保存绑定"), self._project_dir[-40:])

    def batch_mode_value(self) -> str:''')

# 4. label/page.py → 最终态（+set_project_dir + import）
rep("gui/pages/label/page.py",
    "from labeling.controller import AnnotationController\n",
    "from labeling.controller import AnnotationController\n"
    "from project.binding import read_binding  # W58-A：transferType 联动\n")
rep("gui/pages/label/page.py",
    '''    # ------------------------------ 标注模式 ------------------------------ #
    def set_default_shape_mode(self, mode: AnnotationMode) -> None:''',
    '''    # ------------------------------ 标注模式 ------------------------------ #
    @Slot(str)
    def set_project_dir(self, path: str) -> None:
        """项目打开联动（W58-A）：transferType → 默认标注形态。

        binding.json 缺失/无 transferType = 不干预（保持当前模式）。
        """
        self._project_dir: str | None = path
        binding = read_binding(path)
        if binding.transfer_type == "Rect":
            self.set_default_shape_mode(AnnotationMode.RECTANGLE)
        elif binding.transfer_type == "Polygon":
            self.set_default_shape_mode(AnnotationMode.POLYGON)

    def set_default_shape_mode(self, mode: AnnotationMode) -> None:''')

# 5. data_manage → 最终态（恢复 W58 统计显示/签名）
rep("gui/pages/data_manage/page.py",
    '''        text = "\\n".join(f"{k}: {v}" for k, v in stats.items())''',
    '''        text = "\\n".join(f"{k}: {v['count']} ·均{v['avg_area']:.0f}px²" for k, v in stats.items())''')
rep("gui/pages/data_manage/workers.py",
    '''def label_statistics(ann_dir: str) -> dict[str, int]:
    """标注数据统计（各类别数量分布）。"""''',
    '''def label_statistics(ann_dir: str) -> dict[str, dict[str, float]]:
    """标注数据统计（各类别数量 + 尺寸分布：count/total_area/avg_area）。"""''')

# 6. batch_tools.py → W58 版（回退复核 stats try 重定位）
rep("labeling/batch_tools.py",
    '''        for s in doc.get("shapes", []):
            label = s.get("label", "unknown")
            entry = stats.setdefault(label, {"count": 0, "total_area": 0.0})
            # 复核 MEDIUM 修正：坏 points 不得击穿整次统计（一坏文件不
            # 连坐）——转换与计算同入 try，失败按面积 0 计数
            try:
                pts = [
                    (float(p[0]), float(p[1]))
                    for p in (s.get("points") or [])
                ]
                if s.get("shape_type") == "rectangle" and len(pts) >= 2:
                    (x1, y1), (x2, y2) = pts[0], pts[1]
                    area: float = abs(x2 - x1) * abs(y2 - y1)
                else:
                    area = polygon_area(pts)
            except (TypeError, ValueError, IndexError):
                area = 0.0
            entry["count"] += 1
            entry["total_area"] += float(area)''',
    '''        for s in doc.get("shapes", []):
            label = s.get("label", "unknown")
            entry = stats.setdefault(label, {"count": 0, "total_area": 0.0})
            pts = [(float(p[0]), float(p[1])) for p in (s.get("points") or [])]
            if s.get("shape_type") == "rectangle" and len(pts) >= 2:
                (x1, y1), (x2, y2) = pts[0], pts[1]
                area = abs(x2 - x1) * abs(y2 - y1)
            else:
                try:
                    area = polygon_area(pts)
                except (TypeError, ValueError, IndexError):
                    area = 0.0
            entry["count"] += 1
            entry["total_area"] += float(area)''')

# 7. i18n → +W58 键块（锚定 W56 块内「从项目带入」，替换占位 tooltip 行）
rep("gui/core/i18n.py",
    '''    "从项目带入": "Load From Project",
    "工程绑定后启用（预测参数带入）": "Enabled after project binding (prediction params)",''',
    '''    "从项目带入": "Load From Project",
    # W58：工程绑定三段（SKolpha 复刻 FR-005）
    "保存绑定": "Save Binding",
    "工程未绑定模型": "Project has no model binding",
    "请先在项目中训练模型或手动保存绑定": "Train a model in the project or save a binding first",
    "已从项目带入": "Loaded from project",
    "已保存绑定": "Binding saved",
    "保存绑定失败": "Failed to save binding",''')

# 8. w58 测试 → W58 版
rep("tests/test_w58_project_binding.py",
    '''    called = {}
    monkeypatch.setattr(
        predict_page, "_load_model_from",
        lambda path: called.update(path=path) or True,
    )''',
    '''    called = {}
    monkeypatch.setattr(
        predict_page, "_load_model_from",
        lambda path: called.update(path=path),
    )''')
p = Path("tests/test_w58_label_tools.py")
s = p.read_text(encoding="utf-8")
marker = "\n\n@pytest.mark.unit\ndef test_statistics_bad_points_do_not_break_run"
if marker in s:
    p.write_text(s[:s.index(marker)] + "\n", encoding="utf-8")
    print("trimmed w58_label_tools")

print("C5 done")

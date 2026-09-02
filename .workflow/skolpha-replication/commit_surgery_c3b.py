# -*- coding: utf-8 -*-
"""C3 (W56) 第二部分：predict/page 回退 + i18n/spec/测试 W56 版。一次性使用。"""
from pathlib import Path


def rep(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == count, f"{path}: old 出现 {s.count(old)} 次（预期 {count}）"
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("OK", path)


# predict/page.py → W56 态（去 W59 api 接线 + 去复核 bool + 合回 _load_model）
rep("gui/pages/predict/page.py",
    'from gui.pages.predict.api_actions import ApiInferActionsMixin  # W59\n'
    'from gui.pages.predict.batch_actions import BatchModeActionsMixin  # W56\n',
    'from gui.pages.predict.batch_actions import BatchModeActionsMixin  # W56\n')
rep("gui/pages/predict/page.py",
    "class PredictPage(ApiInferActionsMixin, BatchModeActionsMixin, VideoSuperActionsMixin, QWidget):",
    "class PredictPage(BatchModeActionsMixin, VideoSuperActionsMixin, QWidget):")
rep("gui/pages/predict/page.py",
    '''        # W56：批量模式/并发选项（FR-003，控件构建在 BatchModeActionsMixin）
        self._add_batch_options(h, bar)
        # W59：API 推理源（FR-007，控件构建在 ApiInferActionsMixin）
        self._add_api_source(h, bar)''',
    '''        # W56：批量模式/并发选项（FR-003，控件构建在 BatchModeActionsMixin）
        self._add_batch_options(h, bar)''')
rep("gui/pages/predict/page.py",
    '''    def _load_model(self) -> None:
        """加载模型权重（对话框入口）。"""
        path = pick_open_file(
            self, "选择模型权重",
            "Weights (*.pt *.pth *.onnx *.ckpt)"
        )
        if not path:
            return
        self._load_model_from(path)

    def _load_model_from(self, path: str) -> bool:
        """从指定路径加载模型权重（W58-A 带入共用入口；失败文案已发，调用方勿覆盖）。"""
        self._model_path = path
        task = self.cmb_task.currentData()''',
    '''    def _load_model(self) -> None:
        """加载模型权重。"""
        path = pick_open_file(
            self, "选择模型权重",
            "Weights (*.pt *.pth *.onnx *.ckpt)"
        )
        if not path:
            return
        self._model_path = path
        task = self.cmb_task.currentData()''')
rep("gui/pages/predict/page.py",
    '''            else:
                self._engine = None
                self.status_changed.emit(tr("引擎未注册"), task.value)
                self.lbl_model.setText(tr("引擎未注册"))
                return False
            self.lbl_model.setText(os.path.basename(path))
            self.status_changed.emit(tr("模型已加载"), task.value)
            return True
        except (RuntimeError, OSError, ValueError,
                SupervisedEngineError) as exc:
            # W28 审计折入：坏 checkpoint 时引擎 load 抛 SupervisedEngineError
            # （AppError 子类）——旧元组漏收则逃出槽函数且引擎残留半加载态
            self.lbl_model.setText(tr("加载失败"))
            self.status_changed.emit(tr("模型加载失败"), str(exc)[:40])
            return False''',
    '''            else:
                self._engine = None
                self.status_changed.emit(
                    tr("引擎未注册"), task.value
                )
                self.lbl_model.setText(tr("引擎未注册"))
                return
            self.lbl_model.setText(os.path.basename(path))
            self.status_changed.emit(tr("模型已加载"), task.value)
        except (RuntimeError, OSError, ValueError,
                SupervisedEngineError) as exc:
            # W28 审计折入：坏 checkpoint 时引擎 load 抛 SupervisedEngineError
            # （AppError 子类）——旧元组漏收则逃出槽函数且引擎残留半加载态
            self.lbl_model.setText(tr("加载失败"))
            self.status_changed.emit(tr("模型加载失败"), str(exc)[:40])''')

# i18n → +W56 键块
rep("gui/core/i18n.py",
    '''    "多边形": "Polygon",
    "矩形": "Rectangle",''',
    '''    "多边形": "Polygon",
    "矩形": "Rectangle",
    # W56：工业标注形态（SKolpha 复刻 FR-001/002）
    "切割线": "Cut Line",
    "操作标注": "Operation",
    # W56：批量预测模式（SKolpha 复刻 FR-003）
    "批量模式": "Batch Mode",
    "整批完成": "Full Batch",
    "逐张即时": "Incremental",
    "并发数": "Concurrency",
    "仅整批模式生效：并行渲染/产物写（需引擎支持批量推理）": "Full-batch only: parallel post-processing (batch-infer engine required)",
    "从项目带入": "Load From Project",
    "工程绑定后启用（预测参数带入）": "Enabled after project binding (prediction params)",
    "已逐张落盘": "Incremental results saved:",''')

# spec → +2 hiddenimports
rep("autovisionagent.spec",
    '''        "labeling.modes.interactive",
        "labeling.modes.polygon",''',
    '''        "labeling.modes.cut_line",
        "labeling.modes.interactive",
        "labeling.modes.operation",
        "labeling.modes.polygon",''')

# 探针 → W56 版（无全集断言）
Path("tests/test_w56_consumers_probe.py").write_text('''"""W56-0 前置探针（RED 基线）——AnnotationMode 工业形态成员存在性。

任务链：tasks-skolpha-replication.md Task 1 步骤 3。本文件在 W56-A 实现
前必须红（证明守卫先于实现存在）；实现落地（Task 2）后转绿并长期驻留
——成员存在性探针是后续 io/工厂/页面链路的最低层哨兵。
"""
import pytest

from labeling.base import AnnotationMode


@pytest.mark.unit
def test_probe_cut_line_mode_member_exists():
    """CUT_LINE（对标 SKolpha cut_line_label）枚举成员必须存在。"""
    assert hasattr(AnnotationMode, "CUT_LINE"), (
        "AnnotationMode.CUT_LINE 缺失——W56-A 切割线形态未落地"
    )


@pytest.mark.unit
def test_probe_operation_mode_member_exists():
    """OPERATION（对标 SKolpha operation_label）枚举成员必须存在。"""
    assert hasattr(AnnotationMode, "OPERATION"), (
        "AnnotationMode.OPERATION 缺失——W56-A 操作标注形态未落地"
    )
''', encoding="utf-8")
print("probe W56 version written")

# label_modes 测试 → W56 版（EDIT 边界测试原版 + 无 keypoint 用例 + 无 labelme_to_shapes 导入）
rep("tests/test_w56_label_modes_industrial.py",
    '''from labeling import (  # noqa: E402
    AnnotationMode,
    Shape,
    labelme_to_shapes,
    load_labelme_shapes,
    save_labelme,
    shape_from_labelme,
    shape_to_labelme,
)''',
    '''from labeling import (  # noqa: E402
    AnnotationMode,
    Shape,
    load_labelme_shapes,
    save_labelme,
    shape_from_labelme,
    shape_to_labelme,
)''')
p = Path("tests/test_w56_label_modes_industrial.py")
s = p.read_text(encoding="utf-8")
start = s.index("# ============================== EDIT 模式顶点微调（W59 扩展）")
end = s.index("# ============================== 页面接线 ==============================")
s = s[:start] + '''# ============================== EDIT 模式边界 ============================== #


@pytest.mark.unit
def test_edit_mode_rejects_cut_line_vertex_edit(qapp):
    """W55 顶点编辑仅多边形——切割线选中后 move_vertex 拒绝（边界留档）。"""
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    canvas.add_shape(
        mode=AnnotationMode.CUT_LINE, label="c",
        points=[(10.0, 10.0), (60.0, 20.0), (100.0, 80.0)],
    )
    canvas.select_shape(0)
    assert canvas.move_vertex(0, (5.0, 5.0)) is False


''' + s[end:]
p.write_text(s, encoding="utf-8")
print("label_modes W56 version written")
print("C3 part2 done")

# -*- coding: utf-8 -*-
"""C6 (W59) 前向重建。一次性使用。"""
from pathlib import Path
import shutil


def rep(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == count, f"{path}: old 出现 {s.count(old)} 次（预期 {count}）"
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("OK", path)


# 1. api_client.py → W59 版（回退复核契约 try）
rep("inference/api_client.py",
    '''    try:
        task = TaskType(str(payload.get("task", "det")))
        boxes = tuple(
            tuple(float(v) for v in box) for box in payload.get("boxes") or []
        )
        scores = tuple(float(s) for s in payload.get("scores") or [])
        labels = tuple(str(lb) for lb in payload.get("labels") or [])
    except (TypeError, ValueError) as exc:
        # 复核 MEDIUM 修正：契约值非法也收进 ApiInferError——裸异常会把
        # 服务端响应片段漏进用户文案，且 TypeError 绕过页面 except 元组
        raise ApiInferError(
            f"远端响应契约不符（task/boxes/scores 值非法）: {endpoint}",
            endpoint=endpoint,
        ) from exc
    return DetectionResult(''',
    '''    task = TaskType(str(payload.get("task", "det")))
    boxes = tuple(
        tuple(float(v) for v in box) for box in payload.get("boxes") or []
    )
    scores = tuple(float(s) for s in payload.get("scores") or [])
    labels = tuple(str(lb) for lb in payload.get("labels") or [])
    return DetectionResult(''')

# 2. api_actions.py → W59 版（回退复核互斥守卫）
rep("gui/pages/predict/api_actions.py",
    '''        # 复核 LOW 修正：与单张推理互斥（共享 _pending_single，两路并发
        # 会互相覆盖结果）——单张进行中时诚实拒绝
        if not self.btn_single.isEnabled():
            self.status_changed.emit(
                tr("推理进行中"), tr("请等待当前推理完成")
            )
            return
        path = pick_open_file(''',
    '''        path = pick_open_file(''')
rep("gui/pages/predict/api_actions.py",
    '''        self.btn_api_infer.setEnabled(False)
        self.btn_api_infer.setText(tr("推理中..."))
        self.btn_single.setEnabled(False)  # 反向互斥（单张入口见此状态）''',
    '''        self.btn_api_infer.setEnabled(False)
        self.btn_api_infer.setText(tr("推理中..."))''')
rep("gui/pages/predict/api_actions.py",
    '''        self.btn_api_infer.setEnabled(True)
        self.btn_api_infer.setText(tr("API 推理"))
        self.btn_single.setEnabled(True)
        self._single_done(basename, score)''',
    '''        self.btn_api_infer.setEnabled(True)
        self.btn_api_infer.setText(tr("API 推理"))
        self._single_done(basename, score)''')
rep("gui/pages/predict/api_actions.py",
    '''        self.btn_api_infer.setEnabled(True)
        self.btn_api_infer.setText(tr("API 推理"))
        self.btn_single.setEnabled(True)
        self.status_changed.emit(tr("API 推理失败"), err[:60])''',
    '''        self.btn_api_infer.setEnabled(True)
        self.btn_api_infer.setText(tr("API 推理"))
        self.status_changed.emit(tr("API 推理失败"), err[:60])''')

# 3. predict/page.py → W59 态（+api mixin 接线）
rep("gui/pages/predict/page.py",
    'from gui.pages.predict.batch_actions import BatchModeActionsMixin  # W56\n',
    'from gui.pages.predict.api_actions import ApiInferActionsMixin  # W59\n'
    'from gui.pages.predict.batch_actions import BatchModeActionsMixin  # W56\n')
rep("gui/pages/predict/page.py",
    "class PredictPage(BatchModeActionsMixin, VideoSuperActionsMixin, QWidget):",
    "class PredictPage(ApiInferActionsMixin, BatchModeActionsMixin, VideoSuperActionsMixin, QWidget):")
rep("gui/pages/predict/page.py",
    '''        # W56：批量模式/并发选项（FR-003，控件构建在 BatchModeActionsMixin）
        self._add_batch_options(h, bar)''',
    '''        # W56：批量模式/并发选项（FR-003，控件构建在 BatchModeActionsMixin）
        self._add_batch_options(h, bar)
        # W59：API 推理源（FR-007，控件构建在 ApiInferActionsMixin）
        self._add_api_source(h, bar)''')

# 4. canvas.py → 最终态（W59 顶点编辑面扩展——5 处）
rep("labeling/canvas.py",
    '''    def _editable_polygon(self) -> tuple[int, Shape] | None:
        """当前选中且为可编辑 POLYGON 的 (索引, 形状)；否则 None。"""
        idx = self._selected_index
        if idx is None or not 0 <= idx < len(self._shapes):
            return None
        shape = self._shapes[idx]
        if shape.mode is not AnnotationMode.POLYGON or len(shape.points) < 3:
            return None
        return idx, shape''',
    '''    def _editable_polygon(self) -> tuple[int, Shape] | None:
        """当前选中且可顶点编辑的 (索引, 形状)；否则 None。

        W59（AC-002）：可编辑面扩展——POLYGON（≥3 点，闭合语义）/
        CUT_LINE（≥2 点，开放折线）/ OPERATION（2 点，矩形角点=改尺寸）。
        """
        idx = self._selected_index
        if idx is None or not 0 <= idx < len(self._shapes):
            return None
        shape = self._shapes[idx]
        if shape.mode is AnnotationMode.POLYGON and len(shape.points) >= 3:
            return idx, shape
        if shape.mode is AnnotationMode.CUT_LINE and len(shape.points) >= 2:
            return idx, shape
        if shape.mode is AnnotationMode.OPERATION and len(shape.points) == 2:
            return idx, shape
        return None''')
rep("labeling/canvas.py",
    '''        n = len(pts)
        # 闭合判定须在改点前（首点被改后与收尾副本必然不等）
        closed = n >= 4 and pts[0] == pts[-1]
        pts[vertex_idx] = (float(pt[0]), float(pt[1]))''',
    '''        n = len(pts)
        # 闭合判定须在改点前（首点被改后与收尾副本必然不等）；闭合同步
        # 仅多边形语义（W59：折线/矩形无首尾闭合副本）
        closed = (
            shape.mode is AnnotationMode.POLYGON
            and n >= 4 and pts[0] == pts[-1]
        )
        pts[vertex_idx] = (float(pt[0]), float(pt[1]))''')
rep("labeling/canvas.py",
    '''    def insert_vertex(self, pos: int, pt) -> bool:
        """在选中多边形 pos 处插入顶点（一步 undo）。"""
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        pts = list(shape.points)''',
    '''    def insert_vertex(self, pos: int, pt) -> bool:
        """在选中形状 pos 处插入顶点（一步 undo）。

        W59：OPERATION 拒绝插点（矩形保持两点语义——角点拖拽即改尺寸）。
        """
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        if shape.mode is AnnotationMode.OPERATION:
            return False
        pts = list(shape.points)''')
rep("labeling/canvas.py",
    '''    def remove_vertex(self, vertex_idx: int) -> bool:
        """删除选中多边形顶点（一步 undo）；删除后不足 3 点则拒绝。

        闭合多边形删除首/尾顶点=删同一逻辑顶点，两份副本一并移除
        （剩余须 ≥3 点：闭合 4 点三角形拒绝删端点）。
        """
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        pts = list(shape.points)
        if not 0 <= vertex_idx < len(pts):
            return False
        n = len(pts)
        closed = n >= 4 and pts[0] == pts[-1]''',
    '''    def remove_vertex(self, vertex_idx: int) -> bool:
        """删除选中形状顶点（一步 undo）。

        下限：POLYGON 剩余 ≥3 点；CUT_LINE 剩余 ≥2 点（W59）；OPERATION
        拒绝删点（矩形不能只剩一角）。闭合多边形删除首/尾顶点=删同一
        逻辑顶点，两份副本一并移除。
        """
        got = self._editable_polygon()
        if got is None:
            return False
        idx, shape = got
        if shape.mode is AnnotationMode.OPERATION:
            return False
        pts = list(shape.points)
        if not 0 <= vertex_idx < len(pts):
            return False
        if shape.mode is AnnotationMode.CUT_LINE:
            if len(pts) <= 2:
                return False
            self._save_state()
            pts.pop(vertex_idx)
            self._replace_points(idx, pts)
            self._redraw()
            self.shapes_changed.emit(self.shapes)
            return True
        n = len(pts)
        closed = n >= 4 and pts[0] == pts[-1]''')
rep("labeling/canvas.py",
    '''            if selected and shape.mode is AnnotationMode.POLYGON:
                # W55 顶点手柄：白边蓝心小方块，命中半径同 VERTEX_HIT_RADIUS 量级
                hp = QPen(QColor(255, 255, 255), 1)''',
    '''            if selected and shape.mode in (
                AnnotationMode.POLYGON, AnnotationMode.CUT_LINE,
                AnnotationMode.OPERATION,
            ):
                # W55 顶点手柄：白边蓝心小方块，命中半径同 VERTEX_HIT_RADIUS 量级
                # W59：手柄面扩至折线/操作角点（拖拽即微调/改尺寸）
                hp = QPen(QColor(255, 255, 255), 1)''')

# 5. controller.py → 最终态
rep("labeling/controller.py",
    '''    def _selected_polygon(self) -> Shape | None:
        idx = self._canvas.selected_index
        if idx is None:
            return None
        shape = self._canvas.shapes[idx]
        if shape.mode is not AnnotationMode.POLYGON or len(shape.points) < 3:
            return None
        return shape''',
    '''    def _selected_polygon(self) -> Shape | None:
        idx = self._canvas.selected_index
        if idx is None:
            return None
        shape = self._canvas.shapes[idx]
        # W59（AC-002）：顶点编辑面与 canvas._editable_polygon 同口径
        # （POLYGON≥3 / CUT_LINE≥2 / OPERATION=2 点矩形角点）
        if shape.mode is AnnotationMode.POLYGON and len(shape.points) >= 3:
            return shape
        if shape.mode is AnnotationMode.CUT_LINE and len(shape.points) >= 2:
            return shape
        if shape.mode is AnnotationMode.OPERATION and len(shape.points) == 2:
            return shape
        return None''')

# 6. 探针 → 最终态（全集断言）——从备份恢复
shutil.copy(
    Path(r"C:/Users/888/AppData/Local/Temp/w56-w59-final-backup")
    / "tests/test_w56_consumers_probe.py",
    "tests/test_w56_consumers_probe.py")
print("probe final restored")

# 7. label_modes → W59 版（EDIT 测试替换；无复核 keypoint 用例）
p = Path("tests/test_w56_label_modes_industrial.py")
s = p.read_text(encoding="utf-8")
old_section = '''# ============================== EDIT 模式边界 ============================== #


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


'''
new_section = '''# ============================== EDIT 模式顶点微调（W59 扩展） ============================== #


@pytest.mark.unit
def test_edit_mode_supports_cut_line_vertex_edit(qapp):
    """W59（AC-002）：切割线选中后顶点可拖拽微调；下限保 2 点。"""
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    canvas.add_shape(
        mode=AnnotationMode.CUT_LINE, label="c",
        points=[(10.0, 10.0), (60.0, 20.0), (100.0, 80.0)],
    )
    canvas.select_shape(0)
    assert canvas.move_vertex(1, (55.0, 25.0)) is True
    assert canvas.shapes[0].points[1] == (55.0, 25.0)

    # 2 点折线拒绝删点（下限）；删 1 点先成功
    assert canvas.remove_vertex(0) is True
    assert len(canvas.shapes[0].points) == 2
    assert canvas.remove_vertex(0) is False


@pytest.mark.unit
def test_edit_mode_operation_corner_drag(qapp):
    """W59（AC-002）：操作区域角点拖拽=改尺寸；插点/删点拒绝（两点语义）。"""
    canvas = AnnotationCanvas()
    canvas.set_blank(200, 200)
    canvas.add_shape(
        mode=AnnotationMode.OPERATION, label="op",
        points=[(10.0, 10.0), (60.0, 80.0)],
    )
    canvas.select_shape(0)
    assert canvas.move_vertex(1, (90.0, 120.0)) is True
    assert canvas.shapes[0].points[1] == (90.0, 120.0)
    assert canvas.insert_vertex(1, (50.0, 50.0)) is False
    assert canvas.remove_vertex(0) is False


'''
assert old_section in s, "EDIT 边界段未找到"
p.write_text(s.replace(old_section, new_section), encoding="utf-8")
print("label_modes W59 version written")

# 8. i18n → +W59 键块
rep("gui/core/i18n.py",
    '''    "当前引擎忽略增强参数": "Current engine ignores augmentation params",''',
    '''    "当前引擎忽略增强参数": "Current engine ignores augmentation params",
    # W59：API 推理源（SKolpha 复刻 FR-007）
    "API endpoint（http://…）": "API endpoint (http://…)",
    "API 推理": "API Infer",
    "请输入有效 endpoint": "Enter a valid endpoint",
    "须以 http:// 或 https:// 开头": "Must start with http:// or https://",
    "API 推理失败": "API inference failed",''')

# 9. .gitignore → +凭据防呆
gi = Path(".gitignore")
s = gi.read_text(encoding="utf-8")
if "configs/api_key.txt" not in s:
    gi.write_text(s + "\n# W59-A：API 推理凭据文件（env AVA_API_KEY 优先；勿提交）\nconfigs/api_key.txt\n", encoding="utf-8")
    print("gitignore updated")

# 10. w59 测试 → W59 版（去复核 badtask）
p = Path("tests/test_w59_api_client.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''        if _Handler.mode == "badcontract":
            body = json.dumps({"foo": 1}).encode()
        elif _Handler.mode == "badtask":
            body = json.dumps({"boxes": [[1, 2, 3, 4]], "labels": ["x"],
                               "scores": [0.5], "task": "notatask"}).encode()''',
'''        if _Handler.mode == "badcontract":
            body = json.dumps({"foo": 1}).encode()''')
marker = "\n\n@pytest.mark.unit\ndef test_infer_remote_bad_task_value_is_contract_error"
if marker in s:
    s = s[:s.index(marker)] + "\n"
p.write_text(s, encoding="utf-8")
print("w59 W59 version written")

print("C6 done")

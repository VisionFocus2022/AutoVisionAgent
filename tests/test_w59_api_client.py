"""W59-A（FR-007）：HTTP API 推理路径（对标 deploymentParams{endpoint, apiKey}）。

覆盖：infer_remote 契约（multipart POST→JSON boxes）/ 503 / 超时 /
契约缺键四分支 / resolve_api_key（env > 凭据文件 > None）/ .gitignore
防呆 / 预测页 API 源 UI（空 endpoint 诚实报错、成功路径复用单张完成链）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.exceptions import ApiInferError  # noqa: E402
from core.interfaces_supervised import TaskType  # noqa: E402

# ============================== 本地 mock server ============================== #


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self):  # noqa: N802  # http.server 接口名
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # 消费请求体（图像字节）
        if _Handler.mode == "503":
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"unavailable")
            return
        if _Handler.mode == "slow":
            time.sleep(1.5)
        if _Handler.mode == "badcontract":
            body = json.dumps({"foo": 1}).encode()
        else:
            body = json.dumps({
                "boxes": [[1.0, 2.0, 3.0, 4.0]],
                "labels": ["crack"],
                "scores": [0.9],
                "task": "det",
            }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音访问日志
        pass


@pytest.fixture(scope="module")
def api_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/predict"
    server.shutdown()


@pytest.fixture()
def png_path(tmp_path):
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((12, 16, 3), np.uint8))
    assert ok
    p = tmp_path / "img.png"
    p.write_bytes(buf.tobytes())
    return str(p)


# ============================== infer_remote ============================== #


@pytest.mark.unit
def test_infer_remote_happy_path(api_server, png_path):
    from inference.api_client import infer_remote

    _Handler.mode = "ok"
    result = infer_remote(api_server, png_path)
    assert result.task is TaskType.DET
    assert result.boxes == ((1.0, 2.0, 3.0, 4.0),)
    assert result.labels == ("crack",)
    assert abs(result.scores[0] - 0.9) < 1e-9
    assert abs(result.score - 0.9) < 1e-9


@pytest.mark.unit
def test_infer_remote_http_error_mentions_endpoint(api_server, png_path):
    from inference.api_client import infer_remote

    _Handler.mode = "503"
    with pytest.raises(ApiInferError) as exc_info:
        infer_remote(api_server, png_path)
    assert "503" in str(exc_info.value)
    assert api_server in str(exc_info.value)


@pytest.mark.unit
def test_infer_remote_timeout(api_server, png_path):
    from inference.api_client import infer_remote

    _Handler.mode = "slow"
    with pytest.raises(ApiInferError, match="超时"):
        infer_remote(api_server, png_path, timeout=0.3)


@pytest.mark.unit
def test_infer_remote_bad_contract_lists_missing_keys(api_server, png_path):
    from inference.api_client import infer_remote

    _Handler.mode = "badcontract"
    with pytest.raises(ApiInferError) as exc_info:
        infer_remote(api_server, png_path)
    msg = str(exc_info.value)
    assert "boxes" in msg  # 缺键点名


@pytest.mark.unit
def test_infer_remote_invalid_endpoint_scheme(png_path):
    from inference.api_client import infer_remote

    with pytest.raises(ApiInferError, match="endpoint"):
        infer_remote("ftp://x", png_path)


# ============================== resolve_api_key ============================== #


@pytest.mark.unit
def test_resolve_api_key_env_first(tmp_path, monkeypatch):
    from inference.api_client import API_KEY_ENV, resolve_api_key

    key_file = tmp_path / "k.txt"
    key_file.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv(API_KEY_ENV, "env-key")
    assert resolve_api_key(path=key_file) == "env-key"


@pytest.mark.unit
def test_resolve_api_key_file_fallback(tmp_path, monkeypatch):
    from inference.api_client import API_KEY_ENV, resolve_api_key

    monkeypatch.delenv(API_KEY_ENV, raising=False)
    key_file = tmp_path / "k.txt"
    key_file.write_text("  file-key\n", encoding="utf-8")
    assert resolve_api_key(path=key_file) == "file-key"


@pytest.mark.unit
def test_resolve_api_key_none(tmp_path, monkeypatch):
    from inference.api_client import API_KEY_ENV, resolve_api_key

    monkeypatch.delenv(API_KEY_ENV, raising=False)
    assert resolve_api_key(path=tmp_path / "nope.txt") is None


# ============================== .gitignore 防呆 ============================== #


@pytest.mark.unit
def test_gitignore_covers_api_key_file():
    """凭据文件必须被忽略（W23 initial_credentials 同型防呆）。"""
    from pathlib import Path

    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    assert "configs/api_key.txt" in gitignore.read_text(encoding="utf-8")


# ============================== 预测页 API 源 UI ============================== #


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def predict_page(qapp):
    from gui.pages.predict.page import PredictPage

    page = PredictPage()
    yield page
    page.deleteLater()


@pytest.mark.unit
def test_api_source_widgets_exist(predict_page):
    assert hasattr(predict_page, "edit_api_endpoint")
    assert hasattr(predict_page, "btn_api_infer")


@pytest.mark.unit
def test_api_infer_empty_endpoint_honest(predict_page):
    msgs: list[tuple[str, str]] = []
    predict_page.status_changed.connect(lambda t, a: msgs.append((t, a)))
    predict_page._api_infer()  # 空 endpoint
    assert any("endpoint" in t or "endpoint" in a for t, a in msgs)


@pytest.mark.unit
def test_api_infer_success_reuses_single_done_chain(
        predict_page, monkeypatch, png_path, qapp):
    """monkeypatch infer_remote 成功 → 行入表（复用单张完成链）。"""
    from gui.pages.predict import api_actions
    from inference import api_client

    predict_page.edit_api_endpoint.setText("http://mock/predict")
    monkeypatch.setattr(api_actions, "pick_open_file", lambda *a, **k: png_path)

    def _fake_infer(endpoint, image_path, timeout=30.0, api_key=None):
        from core.interfaces_supervised import DetectionResult

        return DetectionResult(
            task=TaskType.DET, score=0.8, scores=(0.8,), labels=("crack",),
            boxes=np.array([[1, 1, 20, 20]], dtype=float),
        )

    monkeypatch.setattr(api_client, "infer_remote", _fake_infer)

    predict_page._api_infer()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predict_page.table.rowCount() == 1:
            break
        time.sleep(0.005)
    assert predict_page.table.rowCount() == 1
    assert predict_page.btn_api_infer.isEnabled()


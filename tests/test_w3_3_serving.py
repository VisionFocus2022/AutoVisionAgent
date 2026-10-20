"""W3-3 gRPC serving 产品化测试（PRD docs/prd-w3-3-serving.md）。

- AC-1 页面启停：启动→运行中；重复启动拒；停止→已停止；未运行停止提示
- AC-2 健康检查：运行时 Ping 回显；未运行明确失败
- AC-3 真线上往返：ephemeral 端口真 server+真 socket，客户端
  Ping/ListTasks 字段正确 + 端口真监听
- AC-4 权限：operator 不可见 serving 页
"""
from __future__ import annotations

import socket
import time

import pytest

pytestmark = [pytest.mark.unit]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _pump(qapp, seconds: float):
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.05)


class _WireServer:
    """ephemeral 端口真 gRPC server（真 socket 生命周期由 with 管理）。"""

    def __init__(self):
        from serving.server import create_server

        self.port = _free_port()
        self.srv = create_server("127.0.0.1", self.port)
        self.srv.start()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.srv.stop(None)


class TestAc3WireRoundtrip:
    def test_ping_and_listtasks_over_real_socket(self):
        import grpc

        from serving.proto import autovisionagent_pb2 as pb
        from serving.proto import autovisionagent_pb2_grpc as pbg

        with _WireServer() as ws:
            # 端口真监听（TCP connect 探测）
            with socket.create_connection(("127.0.0.1", ws.port), timeout=3):
                pass
            with grpc.insecure_channel(f"127.0.0.1:{ws.port}") as ch:
                stub = pbg.AutoVisionAgentServiceStub(ch)
                pong = stub.Ping(pb.PingRequest(), timeout=5)
                assert pong.server_version
                assert pong.dispatcher_ready is True
                tasks = stub.ListTasks(pb.ListTasksRequest(), timeout=5)
                names = [t.task for t in tasks.tasks]
                assert "det" in names and "seg" in names, (
                    f"注册表任务应含 det/seg: {names}"
                )

    def test_ping_after_stop_unreachable(self):
        import grpc

        from serving.proto import autovisionagent_pb2 as pb
        from serving.proto import autovisionagent_pb2_grpc as pbg

        ws = _WireServer()
        port = ws.port
        ws.__exit__()

        with grpc.insecure_channel(f"127.0.0.1:{port}") as ch,                 pytest.raises(grpc.RpcError):  # 停服后不可达=RpcError 族
            pbg.AutoVisionAgentServiceStub(ch).Ping(
                pb.PingRequest(), timeout=2)


class TestAc1Ac2Page:
    def _page(self, qapp):
        from gui.pages.serving import ServingPage

        page = ServingPage()
        msgs: list = []
        page.status_changed.connect(lambda t, a: msgs.append(t))
        page._msgs = msgs
        return page

    def test_start_running_and_double_start_rejected(self, qapp):
        page = self._page(qapp)
        page._port_spin.setValue(_free_port())
        page._start_service()
        _pump(qapp, 8)
        assert page._server is not None, "服务应已启动"
        assert "运行中" in page._state_label.text()
        assert not page._start_btn.isEnabled()
        # 重复启动：引用仍在=拒（按钮禁用下直接调法）
        page._start_service()
        assert any("已在运行" in m for m in page._msgs)
        # 停止
        page._stop_service()
        _pump(qapp, 8)
        assert page._server is None
        assert "已停止" in page._state_label.text()
        assert page._start_btn.isEnabled()

    def test_stop_when_not_running_warns(self, qapp):
        page = self._page(qapp)
        page._stop_service()
        assert any("未运行" in m for m in page._msgs)

    def test_ping_when_running_and_not(self, qapp):
        page = self._page(qapp)
        page._health_check()
        assert any("请先启动" in m or "未运行" in m for m in page._msgs)
        # 启动后 Ping 真往返
        page._port_spin.setValue(_free_port())
        page._start_service()
        _pump(qapp, 8)
        page._health_check()
        deadline = time.time() + 10
        while time.time() < deadline:
            qapp.processEvents()
            if any("健康检查通过" in m for m in page._msgs):
                break
            time.sleep(0.1)
        assert any("健康检查通过" in m for m in page._msgs), (
            f"Ping 未在时限内通过: {page._msgs[-6:]}"
        )
        page._stop_service()
        _pump(qapp, 8)


class TestAc4Permission:
    def test_operator_cannot_see_serving(self):
        from gui.core.permissions import ROLE_ADMIN, ROLE_OPERATOR, page_allowed

        assert page_allowed(ROLE_ADMIN, "serving") is True
        assert page_allowed(ROLE_OPERATOR, "serving") is False

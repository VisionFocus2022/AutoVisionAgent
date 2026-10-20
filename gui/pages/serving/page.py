"""服务页（W3-3，roadmap Wave3 gRPC 产品化 3a）。

GUI 内启停 AutoVisionAgent gRPC 服务（in-process：create_server+
start 非阻塞；stop(None) 停止）+「健康检查」真线上 Ping 往返回显
server_version/dispatcher_ready/loaded_tasks。

并发模型（L3 必答，docs/threading-contract.md 同源）：
- server 引用仅主线程持有（启停按钮经 run_job worker 执行动作但
  结果经 invoke_main 回主线程写引用——与启停互斥由按钮态保证：
  运行中启动按钮禁用，杜绝并发 start/stop 交错）；
- 页面销毁不主动杀服务：gRPC server 随进程退出回收（daemon 线程
  池语义），页面仅是控制面。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.core.i18n import tr
from gui.core.jobs import run_job
from gui.core.thread_bridge import invoke_main, ui_on_error

logger = logging.getLogger(__name__)


class ServingPage(QWidget):
    """gRPC 服务启停与健康检查页（W3-3）。"""

    status_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageBody")
        self._server = None  # 主线程持有；None=未运行
        self._endpoint = ""
        self._build_ui()

    # ------------------------------ UI ------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(14)

        self._title = QLabel(tr("模型服务"))
        self._title.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #FFFFFF;"
        )
        root.addWidget(self._title)

        box = QFrame()
        form = QFormLayout(box)
        form.setSpacing(10)
        self._host_edit = QLineEdit("127.0.0.1")
        form.addRow(tr("监听地址"), self._host_edit)
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(50051)
        form.addRow(tr("端口"), self._port_spin)
        root.addWidget(box)

        btns = QHBoxLayout()
        self._start_btn = QPushButton(tr("启动服务"))
        self._start_btn.setProperty("role", "accent")
        self._start_btn.clicked.connect(self._start_service)
        btns.addWidget(self._start_btn)
        self._stop_btn = QPushButton(tr("停止服务"))
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_service)
        btns.addWidget(self._stop_btn)
        self._ping_btn = QPushButton(tr("健康检查"))
        self._ping_btn.clicked.connect(self._health_check)
        btns.addWidget(self._ping_btn)
        btns.addStretch()
        root.addLayout(btns)

        self._state_label = QLabel(tr("已停止"))
        self._state_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        root.addWidget(self._state_label)
        self._detail_label = QLabel("-")
        self._detail_label.setStyleSheet(
            "color: #94a3b8; font-size: 12px; padding: 4px;"
        )
        self._detail_label.setWordWrap(True)
        root.addWidget(self._detail_label)
        root.addStretch()

    # ------------------------------ 启停 ------------------------------ #
    def _start_service(self) -> None:
        """启动 gRPC 服务（worker 执行，引用回主线程写）。"""
        if self._server is not None:
            self.status_changed.emit(tr("服务已在运行"), self._endpoint)
            return
        host = self._host_edit.text().strip() or "127.0.0.1"
        # CodeRabbit 审查修复：仅放行回环地址——默认安全姿态，防误输入
        # 0.0.0.0/内网地址把无鉴权服务暴露到网络
        if host not in ("127.0.0.1", "localhost"):
            self.status_changed.emit(tr("服务启动失败"), f"{tr('仅允许本机地址')}: {host}")
            return
        port = self._port_spin.value()
        self._start_btn.setEnabled(False)
        self.status_changed.emit(tr("服务启动中..."), f"{host}:{port}")

        def _work():
            try:
                from serving.server import create_server

                # invoke_main 不支持重对象载荷——worker 写暂存属性，
                # 主线程槽经原语唤起后取回（thread_bridge 报错信息指引的模式）
                self._pending_server = create_server(host, port)
                self._pending_server.start()
                invoke_main(self, "_on_started", f"{host}:{port}")
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                invoke_main(self, "_on_start_failed", str(exc))

        run_job(_work, name="serving.start",
                on_error=ui_on_error(self, "_on_start_failed"))

    @Slot(str)
    def _on_started(self, endpoint: str) -> None:
        """启动完成（主线程）：取回暂存引用+按钮态+状态。"""
        srv = getattr(self, "_pending_server", None)
        self._pending_server = None
        self._server = srv
        self._endpoint = endpoint
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._state_label.setText(f"{tr('运行中')} · {endpoint}")
        self.status_changed.emit(tr("服务已启动"), endpoint)
        logger.info("gRPC 服务已启动（GUI）: %s", endpoint)

    @Slot(str)
    def _on_start_failed(self, msg: str) -> None:
        """启动失败（主线程）：复位+显式错误（常见=端口占用）。"""
        self._start_btn.setEnabled(True)
        self._state_label.setText(tr("已停止"))
        self.status_changed.emit(tr("服务启动失败"), msg[:80])
        logger.warning("gRPC 服务启动失败（GUI）: %s", msg)

    def _stop_service(self) -> None:
        """停止服务（worker 执行 stop(None)，引用清空回主线程）。"""
        if self._server is None:
            self.status_changed.emit(tr("服务未运行"), "!")
            return
        self._stop_btn.setEnabled(False)
        srv, self._server = self._server, None  # 主线程先摘引用

        def _work():
            try:
                srv.stop(None).wait(timeout=5)
            except Exception:  # noqa: BLE001  # 停止超时/already stopped 容忍
                logger.warning("gRPC stop 返回异常（容忍）", exc_info=True)
            invoke_main(self, "_on_stopped")

        run_job(_work, name="serving.stop",
                on_error=ui_on_error(self, "_on_stopped"))

    @Slot()
    def _on_stopped(self) -> None:
        """停止完成（主线程）。"""
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._state_label.setText(tr("已停止"))
        self._detail_label.setText("-")
        self.status_changed.emit(tr("服务已停止"), self._endpoint)
        logger.info("gRPC 服务已停止（GUI）")

    # ------------------------------ 健康检查 ------------------------------ #
    def _health_check(self) -> None:
        """真线上 Ping 往返（worker；未运行=明确失败提示）。"""
        if self._server is None:
            self.status_changed.emit(tr("服务未运行"), tr("请先启动服务"))
            return
        endpoint = self._endpoint

        def _work():
            try:
                import grpc

                from serving.proto import autovisionagent_pb2 as pb
                from serving.proto import autovisionagent_pb2_grpc as pbg

                with grpc.insecure_channel(endpoint) as ch:
                    stub = pbg.AutoVisionAgentServiceStub(ch)
                    pong = stub.Ping(pb.PingRequest(), timeout=3)
                # invoke_main 仅支持原语载荷——loaded 拼逗号串；ready 以
                # int 传（bool 属原语但 PySide6 信号 marshal 取 int 更稳）
                invoke_main(
                    self, "_on_ping_ok",
                    pong.server_version, ",".join(pong.loaded_tasks or []),
                    int(pong.dispatcher_ready),
                )
            except Exception as exc:  # noqa: BLE001  # grpc 各类超时/不可达
                invoke_main(self, "_on_ping_failed", str(exc))

        run_job(_work, name="serving.ping",
                on_error=ui_on_error(self, "_on_ping_failed"))

    @Slot(str, str, int)
    def _on_ping_ok(self, version: str, loaded_csv: str, ready: int) -> None:
        """Ping 往返回显（主线程；CodeRabbit 修复：ready 未置=显式未就绪）。"""
        if ready:
            self._detail_label.setText(
                f"v{version} · {tr('就绪')} · {tr('已加载')}: "
                f"{loaded_csv or '-'}"
            )
            self.status_changed.emit(tr("健康检查通过"), f"v{version}")
        else:
            self._detail_label.setText(f"v{version} · {tr('未就绪')}")
            self.status_changed.emit(tr("健康检查失败"), tr("调度器未就绪"))

    @Slot(str)
    def _on_ping_failed(self, msg: str) -> None:
        """Ping 失败显式提示（主线程）。"""
        self._detail_label.setText(tr("健康检查失败"))
        self.status_changed.emit(tr("健康检查失败"), msg[:80])


__all__ = ["ServingPage"]

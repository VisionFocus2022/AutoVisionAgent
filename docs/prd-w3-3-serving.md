# PRD-lite：W3-3 gRPC serving 产品化（3a 服务启停 UI + 3b 客户端往返）

- **版本**: v1.0（2026-10-15）
- **档位声明**: 🔴L3 ｜ 确定性：高（后端 create_server/serve 皆在且有 12 项单测；in-process 线程模型=gRPC server.start() 非阻塞）｜ 影响半径：大（新页面+权限矩阵+页数钉+网络监听面——仅 127.0.0.1 默认）｜ 规模：中（新页 ~200+main/permissions/i18n+测试）｜ 可逆性：双向门
- **上游**: roadmap Wave3 W3-3；serving/server.py 既有 create_server 缝
- **门禁**: 探索 ✅（用户指令"继续"=W3-3）｜ PRD ✅（S2 预裁决：roadmap DoD 3a/3b）｜ 收尾 ◐（2026-10-20：单测 6 绿含 ephemeral 端口真线上 Ping/ListTasks 往返+停服 RpcError 不可达+页面启停四态+operator 不可见；.NET 一例=dotnet 9.0.316 实跑 Ping 测试 1/1 通过；主门禁绿；exe 重打包；**AC-5 UIA 链未验证=开放债务**——本时段会话级 window-find 漂移，见实施纪要）

## FR

- **FR-1 服务页**（新 `gui/pages/serving/page.py`）：host（默认 127.0.0.1）+
  port spin（1024-65535，默认 50051）+「启动服务」（worker 线程调
  create_server+start，持 server 引用；已运行拒绝重复启动）+
  「停止服务」（server.stop(None) 引用清空；未运行提示）+ 状态标签
  （运行中 host:port / 已停止）+「健康检查」（gRPC 客户端 Ping 真线上
  往返——server_version/dispatcher_ready/loaded_tasks 回显）。
- **FR-2 并发/生命周期**（L3 必答）：server 引用主线程持有，启停按钮
  worker 化避免 UI 卡顿；start 后按钮态互斥（启动禁用/停止启用）；
  页面关闭不杀服务（服务随进程退出回收——QThread 非持有语义，文档化）。
- **FR-3 注册与权限**：main.py 注册「服务」页（deploy 后）；ALL_PAGES+1；
  可见性 admin/engineer（推理对外暴露面，operator 不可见）；页数钉
  12→13（test_gui/test_m2_e2e）+ w29 矩阵 +1。
- **FR-4 真线上往返测试**：ephemeral 端口真 gRPC server（真 socket）→
  客户端 stub Ping/ListTasks 断言往返（区别于既有 servicer 直调单测）。
- **FR-5 .NET 一例**：dotnet SDK 可用则跑 dotnet_client Tests 一例；
  不可用=显式 skip 登记债务（不假装）。

## AC

- AC-1 页面：启动→状态运行中；重复启动被拒；停止→已停止；未运行停止
  →提示不炸。〔非 happy〕
- AC-2 健康检查：服务运行时 Ping 回显 version/loaded；未运行时 Ping
  →明确失败提示。〔非 happy〕
- AC-3 真线上：ephemeral server 上 Ping/ListTasks 客户端往返字段正确；
  端口真监听（connect 探测）。
- AC-4 权限：operator 不可见服务页；admin/engineer 可见。
- AC-5 UIA 最小链：exe→服务页→启动→状态运行中→健康检查→回显。
- AC-6 主门禁全绿+ruff 0+行数守卫（新页 ≤300；受影响页内）。

## 范围

新：gui/pages/serving/{__init__,page}.py、tests/test_w3_3_serving.py、
tests/uia/test_serving_w3_3.py。改：gui/main.py、gui/core/permissions.py、
gui/core/i18n.py、tests/test_gui.py+test_m2_e2e（页数 13）、
tests/test_w29_permissions.py（矩阵）。
Out of scope：TLS/鉴权、远程 host 暴露（默认仅本机）、.NET 完整回归、
GUI 内模型加载管理（RPC 客户端自管）。

## 实施纪要（2026-10-20）

- **invoke_main 重对象载荷限制实证**：grpc server/_Event 不可作 Queued
  Connection 载荷——worker 暂存页面属性 + 原语唤起（thread_bridge 报错
  信息指引的模式）；loaded_tasks 列表拼逗号串同因。
- **.NET 一例**：dotnet restore（首次需 solution 根还原）→ `dotnet test
  --filter Ping` 1/1 通过（grpc.AspNetCore CPM 还原路径修正后）。
- **UIA 服务链会话级阻断（对照实验定性）**：本时段 exe 主窗口 UIA 查找
  全局失效——对照运行此前全绿的 pole 用例同样 window-find 超时；独立
  探针枚举桌面顶层窗（微信/bilibili 可见=桌面交互正常）但 exe 窗不在
  树中，python 源码模式同样不可见，offscreen build_window 正常（13 页）
  ——结合日志 user=system access_denied，定性=会话/窗口站关联漂移
  （W64 类）。**债务：交互会话恢复后复跑本链 + 全 UIA 套件**。
- 旁证发现：QLockFile 强杀后陈旧锁未自动恢复的疑似 case（手工清除后
  新实例正常启动）——登记观察。

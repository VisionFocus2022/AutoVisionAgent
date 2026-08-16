# PRD — 第七波：.NET bool_rle 解码 + 默认开启压缩 + 覆盖棘轮推进（wave7-dotnet-rle）

> 依据：用户 2026-08-17 指令"把 .NET SharedMemoryReader 补上 bool_rle 解码后默认开启
> 压缩（跨语言小改）、和覆盖棘轮继续向 serving/server 与 gui 各页推进"。
> 基线：W6 终态 375 passed / 0 failed / 1 skipped，门禁 71.97%。

## FR-001 .NET bool_rle 解码 + 掩码压缩默认开启

- C# `SharedMemoryReader.ReadMasks` 支持 `dtype=bool_rle`（与 Python
  `serving/mask_codec` 契约一致：int32 小端交替游程、False 起始、C 序展平；
  负游程/游程和不等/载荷截断显式报错）。
- 前置修复（实测发现）：C# 项目残缺四件套——csproj 无测试框架（dotnet test
  静默 0 条）、`Protos/` 目录缺失（项目从未构建成功）、`Models/Vision` 与
  `Enums/Vision` 类型缺失、CPM 版本管理缺失（Google.Protobuf 解析到 3.0.0，
  含 GHSA-77rm-9x9h-xj3g / GHSA-jwvw-v7c5-m82h 高危 CVE）。
- Python 侧默认开启压缩（原 AVA_SHM_MASK_RLE=1 开关翻转为默认，=0 显式退回
  raw 逃生门）；proto dtype 注释同步。

## FR-002 覆盖棘轮推进（serving/server + gui 各页）

- serving：`__main__` 入口（runpy 驱动）、`serve()` 优雅停机、
  `_build_arg_parser` 默认/环境/CLI 覆盖。
- gui：data_manage workers 纯函数全测（move/list 划分、替换/删除/统计、
  翻转坐标、瓦片切割）、settings 保存/重置（json 落盘+语言即时生效+auto 主题）、
  predict 结果表/CSV 导出（公式注入防护锚定）、login 错误密码/离线模式
  （有 license 直入、无 license 拒绝不入）。

## 验收标准

- AC-001（FR-001）：`dotnet test` 全绿（45+ 条，含 5 条 bool_rle 契约锚测试，
  锚字节来自 Python 编码器实测输出）；Python 默认路径 dtype=bool_rle 且读回
  逐位相等；AVA_SHM_MASK_RLE=0 退回 bool。
- AC-002（FR-002）：新增页面/入口测试全绿；顺带修复的潜在 bug 有测试锚定
  （numpy boxes 真值判断）。
- AC-003：门禁全量 rc=0，覆盖率棘轮自 71 升门（实测地板）。

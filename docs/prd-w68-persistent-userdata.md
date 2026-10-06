# PRD-Lite：W68 用户数据持久化（重建/升级不再重置密码）

- 版本：v1.0（2026-09-28）
- 档位：🟡L2（命中硬触发器 3 安全关键路径——凭据存储位置；三门禁：探索✅/PRD 并入✅/收尾待批）
- 用户原话：「为什么每次重新生成软件，登录密码就变了，这不合理」

## 1. 背景与目标

根因（单点）：`core/constants.py` 的 `CONFIG_DIR` 在冻结态解析为
`_internal\configs`（按源码文件位置回溯），而 PyInstaller 重建清空整个
dist 目录 → users.json/initial_credentials.txt 销毁 → 首启重新生成随机
密码。**同一缺陷波及**：审计日志（`CONFIG_DIR.parent/logs/audit`）、检测
历史（logs/history）、用户设置（settings_io）——每次重建历史清零。

真实任务：升级/重建软件后，密码与一切用户数据保持不变。

## 2. FR 与 AC

| FR | AC | 验证 |
|---|---|---|
| FR-1 冻结态持久目录 | `sys.frozen` → `%APPDATA%/AutoVisionAgent/configs`（用户裁决 APPDATA 按用户）；APPDATA 缺失回退 `~/AppData/Roaming` | 3 解析用例 ✅ |
| FR-2 源码模式不变 | 非冻结 → 仓根 configs（开发/测试现状零扰动） | `test_resolve_config_dir_dev_unchanged` ✅ |
| FR-3 旧数据迁移 | 冻结首启把 `_internal/configs` 的 users.json/initial_credentials.txt/user_settings.json/license.key 搬到新家；**目标已存在不覆盖**（幂等，保护新数据） | `test_migrate_legacy_configs` ✅ |
| FR-4 全消费方跟随 | 审计/历史/设置/登录全走 CONFIG_DIR 单点——改一处全修（零逐页改动） | 架构既定 ✅ |
| FR-5 测试基建同步 | UIA conftest `_uia_config_dirs` 增补 APPDATA 目录（exe 模式凭据预置落新家） | conftest 更新 ✅ |

## 3. 范围与实现

- `core/constants.py`：`_resolve_config_dir()` + `migrate_legacy_configs()`
  （main.py 启动早期调用，迁移结果写日志）。
- `gui/main.py`：main() 入口调迁移。
- `tests/uia/conftest.py`：`_uia_config_dirs` + APPDATA 目录。
- 测试：`tests/test_w68_persistent_userdata.py` 5 用例（RED 5 败→GREEN）。

**Out of Scope**：PROGRAMDATA 按机器共享（门禁裁决不采用）；配置文件加密
（现状 PBKDF2 哈希已可）。

## 4. 风险与假设

- 假设：单 Windows 账号工位（APPDATA 按用户够用，用户裁决确认）。
- 兼容：现网 exe 用户升级后首启自动迁移 `_internal/configs/users.json`
  → 当前密码无缝衔接；审计/历史从新版起在新位置累积（旧日志不迁，仅
  四个用户态文件迁移——历史文件体积不可控，非本次诉求）。
- 首启后 `_internal/configs` 的旧文件保留不删（迁移源只读）。

## 5. 门禁记录

- 门禁 1（探索）：出示即答——**APPDATA 按用户（推荐）** ✅
- 门禁 2（PRD）：并入门禁 1。
- 门禁 3（收尾）：主门禁 1269 绿 + ruff 0；**exe 重打包因用户正在运行
  软件而挂后台等待进程退出（构建产物验证随后补）**；commit 待批。

## 6. AC 核验回填

| AC | 结果 |
|---|---|
| W68 5 用例 | ✅ 0.06s |
| 主门禁（首轮） | ❌ ruff I001/F401（新测试文件导入序）——--fix 后复跑 |
| 主门禁（复跑） | ✅ 1269 passed + 6 skipped / ruff 0 |
| exe 重建 | ⏸ 后台等待用户关闭软件后自动执行 |

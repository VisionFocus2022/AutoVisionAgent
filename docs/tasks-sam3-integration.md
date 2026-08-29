# Tasks：SAM3 集成到标注（W46 · lite）

关联：[prd-sam3-integration.md](prd-sam3-integration.md)（FR/AC 编号同源）

| # | 任务 | 依赖 | 规模 | 验证方式 | 状态 |
|---|------|------|------|----------|------|
| T1 | 权重下载：跑 `scripts/download_sam3.py`，校验 REQUIRED_FILES 齐备；`.gitignore` 补 `weights/`+`*.safetensors` | — | S | 脚本 rc=0 + 文件清单 | ✅ |
| T2 | `labeling/sam3_adapter.py`：Sam3Adapter 全方法面，延迟导入 transformers，点→盒映射 + 掩码∩矩形 + instance→ε折点多边形 | T1(仅真权重冒烟依赖；单测可先行 Fake) | M | TDD：tests/test_sam3_adapter.py RED(2 helper 自伤修复)→GREEN | ✅ |
| T3 | 装配分支：`sam_session.py` AVA_SAM3_DIR 优先 + config.json 对话框分支（回落 SAM1 原路径）；零新增 i18n 键 | T2 | S | resolve_sam3_model_dir 纯函数 5 用例 | ✅ |
| T4 | opt-in 真权重冒烟：AVA_SAM3_DIR 门控用例 + 真极柱图实测 | T1+T2+T3 | S | 冒烟 1 passed（15.6s 含加载）+ 实测见下 | ✅ |
| T5 | 集成验证：全量 pytest 门禁 + 总检 11 项 + AC 回填 | T2+T3 | M | **1178 passed / 5 skipped / rc=0 / cov 92.84%** | ✅ |

## 真机实测证据（RTX 3060 Laptop 12GB · torch 2.5.1+cu121 · transformers 5.12.1）

- **加载** 9.8-23s（首启冷盘 23s，二次 9.8s）；**VRAM 峰值 4.05GB**（12GB 卡宽裕）
- **几何提示**：点击 1.49s→12 折点 / 区域 1.46s→105 折点 / 笔刷 1.41s→97 折点（每交互一次全图前向，无 SAM1 式 embedding 缓存——PRD §5 假设成立，延迟可接受）
- **文本概念**（缺陷图 100_*.bmp）：`hole`→13 实例（分数 0.53-0.76）、`metal surface`→2（0.90/0.34）、`scratch`→3（0.79+）；`pole`/`metal pole`/`defect` 零命中——**概念词贴域问题非代码缺陷**（微距表面图对 "pole" 无锚定），已写入 build_amg_detector docstring
- 分数带实测推动 `iou_thresh` 默认 0.5→**0.3**（0.3-0.5 带含大量真实例）

## AC 核验

- AC-1 ✅ `weights/sam3/` 10 文件 3.45GB 齐备；`git status` 零权重可见（`weights/` 整目录已忽略）
- AC-2 ✅ 真权重冒烟 1 passed（AVA_SAM3_DIR 门控）；概念分割 ≥1 Shape 以真极柱图 `hole`→13 实例实证（数据集在仓外不可入 CI，证据记录于此）
- AC-3 ✅ 四模式方法面全通（28 单测 + 真机点击/区域/笔刷抽查）
- AC-4 ✅ 不设 AVA_SAM3_DIR/不选 json 时 `_ensure_sam` SAM1 分支逐字节保持（test_sam_wiring/test_sam_modes/test_sam_adapter 41+1skip 全绿未动）
- AC-5 ✅ 1178 passed/5 skipped/rc=0/cov 92.84%（基线 1150 + 28 新用例）

## 偏差与后续

1. **首轮门禁 1 红**：operator 把工作日志写进 `logs/` 撞 W23 日志隔离守卫（`tests\test_` 签名）——非代码缺陷，工作日志移 %TEMP% 后复跑全绿。教训已沉淀。
2. **UIA 复跑未做**（Phase 4.5）：改动路径 `_ensure_sam` 仅 SAM 模式触发，UIA 12 用例走手动多边形/矩形流不经过；且需新 exe 重打包。建议下个打包波次一并复跑（机器空闲时 `.venv/Scripts/python.exe -m pytest tests/uia -o addopts=`）。
3. **exe 集成留待打包波次**：`_load_sam3` 已加 ImportError 诚实报错（冻结态缺模块不裸穿 Qt 槽）；正式支持需 spec 补 hidden import（labeling.sam3_adapter + transformers 栈）+ 体积评估（lite 距 2GiB 限仅余 30.8MiB，transformers 全家进 lite 不可行，full 版评估）。
4. 不自动 commit（执行铁律 7）——建议提交信息见收尾报告。

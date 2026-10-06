# PRD-lite：W1-1 训练逐轮进度与曲线（真训练可观测 + 可中断）

- **版本**: v1.0（2026-10-06）
- **档位声明**: 🟡L2 ｜ 确定性：高（ultralytics add_callback/on_fit_epoch_end + QMetaObject.invokeMain 既有模式）｜ 影响半径：中（并发/线程模型：回调在工作线程→invokeMain 主线程，遵守 docs/threading-contract.md）｜ 规模：中（2 生产文件 +~70 行 + 测试）
- **上游**: roadmap Wave1 W1-1；W71 F-4（真训练全程无进度无中断，用户黑盒等待）
- **门禁**: 探索 ✅（用户指令 W1-3+W1-1 连做）｜ PRD ✅（S2 预裁决：roadmap DoD 锁定）｜ 收尾 ✅（2026-10-06：单测 7 绿；UIA DoD 真训练采样 ≥2 进度点+强制结束复位 44.6s 过；wizard 329s 全链含自适应 100 轮）

## 1. 背景

一次性适配器（W58）把全部内部轮跑在首个外层轮内：外层 progress 回调只在
整场训练结束才发一次（曲线 1 个点），should_stop 只在外层轮间隙检查=
**真训练全程不可中断**——用户黑盒等待且"强制结束"形同虚设。

## 2. FR

- **FR-1 逐轮进度钩子**：引擎 `set_progress_callback(cb)`；train_epoch 注册
  ultralytics `on_fit_epoch_end` 回调 → cb({epoch,total,loss,eta_s})（本层
  只发 dict，不做 UI）；total 取自适应后轮数。
- **FR-2 可中断**：引擎 `request_stop()` 置标志；epoch 回调内若置位 →
  `trainer.stop=True`（ultralytics 轮循检查，破环返回）；外层 fit 经
  should_stop 正常收尾 → finished_sig → UI 复位（既有链路零改）。
- **FR-3 页面接线**：_make_trainer 真路径持引擎引用并装钩子（工作线程
  cb → invoke_main("_on_epoch_progress_ui")）；槽内更新进度条
  percent、chart.append(loss)、lbl_log "epoch k/N · 剩余 mm:ss"。
- **FR-4 停止联动**：_stop_training 追加 engine.request_stop()（保留
  既有 stop_flag 协作路径）。

## 3. AC

- AC-1 适配器：FakeYOLO 捕获 add_callback → 手动触发（epoch=3/100）→
  cb 收到 {epoch,total,loss,eta_s}；cb 未设时不注册。〔非 happy-path〕
- AC-2 停止：request_stop 后触发 epoch 回调 → 传入的 trainer.stop 被置
  True；未置位不改。
- AC-3 页面：_on_epoch_progress_ui 更新 bar/chart/lbl（离屏直调）；
  _emit_epoch_progress 经 invoke_main 派发（monkeypatch 捕获槽名）。
- AC-4 UIA（DoD）：真 seg 训练中采样 lbl_log ≥2 个不同 epoch 值；点
  "强制结束"后按钮/状态复位（btn_start 恢复可用）。
- AC-5 主门禁全绿+ruff 0+行数守卫；模拟路径零回归。

## 4. 范围

改：models/supervised/engines/_yolo_seg_base.py、gui/pages/train/page.py；
新 tests/test_w1_1_epoch_progress.py + tests/uia/test_train_progress_w1_1.py。
Out of scope：曲线控件美化、训练历史（W1-2）、AMP 异步（W1-4）。

## 实施纪要（2026-10-06）

- 规模守卫连锁拆分：train/page.py 814→789（EngineTrainStrategy 拆
  gui/pages/train/strategy.py）；train_epoch 117→<100（_install_epoch_callbacks
  模块助手）。
- TrainConfig 增 small_data_epoch_floor（默认 100，0=关）——cpu 冒烟
  豁免通道（自适应把 1 轮冒烟抬成 cpu 100 轮超时暴露）。
- 停止语义：engine.request_stop() → epoch 回调置 trainer.stop=True 破环
  → ultralytics 返回 → 外层 should_stop 收尾 → finished_sig → UI 复位
  （此前真训练全程不可中断——should_stop 只在外层轮间隙生效）。

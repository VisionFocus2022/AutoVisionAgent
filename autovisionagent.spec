# -*- mode: python ; coding: utf-8 -*-
"""AutoVisionAgent PyInstaller 打包配置（FR-G3）— T-AVA-16

构建命令：
  pyinstaller autovisionagent.spec --noconfirm

产出：dist/AutoVisionAgent/AutoVisionAgent.exe
"""
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ["gui/main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # 仅打包存在的文件；configs/ 在运行时按需创建
    ] + ([
        # 如果 configs/user_settings.json 存在则打包
        ("configs/user_settings.json", "configs"),
    ] if Path("configs/user_settings.json").exists() else []),
    hiddenimports=[
        # PySide6
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # 引擎惰性加载（W2: 9 引擎全实装——det/seg/abdet 移植 + sgan/super 真化）
        "models.supervised.engines.abdet_anomalib",
        "models.supervised.engines.cls_torchvision",
        "models.supervised.engines.det_yolo",
        "models.supervised.engines.pose_yolo",
        "models.supervised.engines.pseg_yolo",
        "models.supervised.engines.seg_yolo",
        "models.supervised.engines.sgan_blend",
        "models.supervised.engines.sseg_smp",
        "models.supervised.engines.super_cv2",
        # W32：OCR 可选任务引擎 + easyocr 本体（引擎方法内惰性导入，
        # 静态分析不可见——与引擎模块一并显式列出；lite 派生时剪除）
        "models.supervised.engines.ocr_easyocr",
        "easyocr",
        # 标注子系统（手动 4 模式必须显式列出：modes/__init__ 用变量拼
        # importlib 导入，PyInstaller 静态分析不可见——W4 发版检查实测漏打包
        # 导致 exe 内全部手动标注失效，UIA 曾以"软通过"掩盖）
        "labeling.sam_adapter",
        "labeling.batch_tools",
        "labeling.io_labelme",
        "labeling.modes.auto",
        "labeling.modes.interactive",
        "labeling.modes.polygon",
        "labeling.modes.rectangle",
        "labeling.modes.brush",
        "labeling.modes.keypoint",
        "labeling.modes.region_sam",
        "labeling.modes.brush_sam",
        # 分发器
        "industrial_vision_platform.vision_dispatcher",
        # W5: supervision 标注优化（渲染/导出；函数内惰性导入，显式列出防漏打包）
        "supervision",
        "inference.sv_bridge",
        "dataset.format_export",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不必要的模块减小体积
        # W26: matplotlib 恢复打包——ultralytics 导入链硬依赖
        # （ultralytics/models/yolo/semantic/train.py:8 顶层 import
        # matplotlib.pyplot），W19 排除致打包态 predict 引擎加载必败
        # （W25 UIA 真窗擒获；.venv 有 matplotlib 掩盖单测层）。
        # 体积：W26 终版重打包后 lite 实测 1.983GiB（余量 17.5MiB，
        # LITE_MARKER.json total_bytes 2,129,083,893）。此余量为
        # W27+ 体积增量波次的硬上限——下一个加体积的波次须先启用
        # Agg 回退杠杆（仅保 matplotlib Agg 后端，ultralytics 只用
        # savefig 级能力）再重打包。PYZ 清场回收量已并入本注释口径。
        # 守卫见 tests/test_w26_spec_packaging.py
        "notebook",
        "IPython",
        "jupyter",
        "tkinter",
        # W26: PYZ 静态误拉的 venv-only 运行时（W24 审计 79 个 pytest
        # 模块 + pydub 链；W26 PYZ 实证扩面 gradio169/fastapi39/flask23/
        # uvicorn40 模块——毒化测试证明九引擎注册链与 ultralytics/
        # anomalib 加载链零依赖，产品代码零引用，守卫强制安检）
        # 红线：严禁排除 unittest——torch 2.5+ 运行时依赖 unittest.mock
        # 红线：pydantic/huggingface_hub 为 anomalib 正当引用，禁排
        "pytest",
        "_pytest",
        "pydub",
        "gradio",
        "fastapi",
        "flask",
        "uvicorn",
        # W26 守卫扩面擒获的存量隐患（W19 同型）：transformers/utils/
        # notebook.py:20 无守卫模块级 import IPython.display 且该文件
        # 在 PYZ——exe 内触达即炸。引用方仅此模块（trainer.py 的引用
        # 在 is_in_notebook() 条件内恒 False；integration_utils 为函数
        # 体惰性）→ 外科排除该模块本体，IPython 保持排除不增体积
        "transformers.utils.notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoVisionAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 模式，无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 将来补图标：放置 assets/AutoVisionAgent.ico 后改回 icon="assets/AutoVisionAgent.ico"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AutoVisionAgent",
)

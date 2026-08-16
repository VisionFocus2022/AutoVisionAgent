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
        "models.supervised.engines.sseg_mmseg",
        "models.supervised.engines.super_cv2",
        # 标注子系统（仅注册已实现的模块）
        "labeling.sam_adapter",
        "labeling.batch_tools",
        "labeling.io_labelme",
        "labeling.modes.auto",
        "labeling.modes.interactive",
        # 分发器
        "industrial_vision_platform.vision_dispatcher",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不必要的模块减小体积
        "matplotlib",
        "notebook",
        "IPython",
        "jupyter",
        "tkinter",
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
    icon="assets/AutoVisionAgent.ico" if Path("assets/AutoVisionAgent.ico").exists() else None,
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

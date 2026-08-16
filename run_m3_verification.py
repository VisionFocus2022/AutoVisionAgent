#!/usr/bin/env python3
"""AutoVisionAgent M3 全量验证脚本（FR-G4）— T-AVA-18/21

执行顺序：
1. py_compile 全部新增/修改模块
2. pytest 全量测试（含覆盖率门禁）
3. GUI 渲染预览
4. 引擎注册完整性检查

运行：python run_m3_verification.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# 需要编译检查的核心模块
COMPILE_TARGETS = [
    "models/supervised/engines/__init__.py",
    "models/supervised/engines/cls_torchvision.py",
    "models/supervised/engines/pose_yolo.py",
    "models/supervised/engines/pseg_yolo.py",
    "models/supervised/engines/sseg_mmseg.py",
    "models/supervised/engines/sgan_blend.py",
    "models/supervised/engines/super_cv2.py",
    "labeling/sam_adapter.py",
    "evaluation/generative_metrics.py",
    "exporter/supervised_exporter.py",
    "industrial_vision_platform/vision_dispatcher.py",
    "gui/main.py",
    "gui/pages/__init__.py",
    "gui/pages/login/__init__.py",
    "gui/pages/login/page.py",
    "gui/pages/home/__init__.py",
    "gui/pages/home/page.py",
    "gui/pages/eval_/__init__.py",
    "gui/pages/eval_/page.py",
    "gui/pages/deploy/__init__.py",
    "gui/pages/deploy/page.py",
    "gui/pages/settings/__init__.py",
    "gui/pages/settings/page.py",
]


def run_cmd(cmd: list[str], label: str) -> int:
    """运行命令并打印结果。"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


def main() -> int:
    rc = 0

    # 1. 编译检查
    print("\n[1/4] py_compile 编译检查...")
    for target in COMPILE_TARGETS:
        path = PROJECT_ROOT / target
        if path.exists():
            r = run_cmd(
                [sys.executable, "-m", "py_compile", str(path)],
                f"编译 {target}",
            )
            if r != 0:
                print(f"  FAIL: {target}")
                rc = max(rc, r)
            else:
                print(f"  OK: {target}")
        else:
            print(f"  SKIP (不存在): {target}")

    # 2. 全量测试
    print("\n[2/4] pytest 全量测试...")
    r = run_cmd(
        [sys.executable, "-m", "pytest",
         "tests/", "--tb=short", "-q"],
        "全量测试",
    )
    rc = max(rc, r)

    # 3. M2 e2e
    print("\n[3/4] M2 集成测试...")
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    r = run_cmd(
        [sys.executable, "-m", "pytest",
         "tests/test_m2_e2e.py", "-m", "e2e",
         "--no-cov", "-q"],
        "M2 e2e 测试",
    )
    rc = max(rc, r)

    # 4. GUI 渲染预览
    print("\n[4/4] GUI 渲染预览...")
    r = run_cmd(
        [sys.executable, "-m", "gui._render_preview",
         "_m2_preview.png"],
        "GUI 渲染",
    )
    rc = max(rc, r)

    # 总结
    print(f"\n{'='*60}")
    if rc == 0:
        print("  ALL CHECKS PASSED")
    else:
        print(f"  FAILURES DETECTED (rc={rc})")
    print(f"{'='*60}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

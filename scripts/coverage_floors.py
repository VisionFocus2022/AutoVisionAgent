"""覆盖率棘轮地板检查（M16，2026-10-05 一轮审查 Tessa 建议）。

背景：pytest.ini 全局 --cov-fail-under=92 存在分母稀释——core 单独
91.2% 被 12 包合计分母"抬"过线（实测于 2026-09-29 快照），
detection_history 79.6% 完全可藏匿。无 per-module 地板。

机制（棘轮）：
- 每包设地板 = 该包当前实测覆盖率 - 1（允许 1pp 波动，防统计噪声）
- 只升不降：地板写死在 _FLOORS，提升覆盖率后应手动上调
- 低于地板即失败（CI 可用），地板本身不自动更新（棘轮单向）

用法：
    python scripts/coverage_floors.py            # 跑全量测试并检查地板
    python scripts/coverage_floors.py --json out.json   # 输出各包明细

依赖：pytest + coverage（项目已有），跑的是 pytest.ini 全量门禁同一套。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---- 棘轮地板表（当前实测 - 1，来源 2026-10-06 全量门禁实测）----
# 提升某包覆盖率后请手动上调该值（棘轮只升不降）。
_FLOORS: dict[str, float] = {
    "core": 92.6,        # 实测 93.6%（2026-10-06，审查修复测试拉升 +2.4pp）
    "serving": 95.0,     # 实测 96.0%
    "training": 96.8,    # 实测 97.8%（M8/M11/checkpoint 测试覆盖）
    "dataset": 81.2,     # 实测 82.2%（P0-1 划分 + O1 测试覆盖）
    "inference": 91.7,   # 实测 92.7%（O6/M6 测试覆盖，tiling 已接线级）
    "gui": 87.8,         # 实测 88.8%（大包宽地板，43 文件 UI 测试成本高）
}


def run_coverage(from_existing: bool = False) -> dict[str, float]:
    """跑全量测试取各包覆盖率（复用 pytest.ini 的 coverage 配置）。

    from_existing=True（CI 模式）：复用上一步 pytest 门禁已产出的
    .coverage 数据文件（coverage combine 兼容多机分片），零额外测试
    运行成本；数据不存在时报错退出。
    """
    import xml.etree.ElementTree as ET

    xml_path = ROOT / "coverage_floors.xml"
    if from_existing:
        subprocess.call(
            [sys.executable, "-m", "coverage", "combine"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not (ROOT / ".coverage").exists():
            print("[floors] 未找到 .coverage 数据（from-existing 模式需先跑 pytest）",
                  file=sys.stderr)
        ret = subprocess.call(
            [sys.executable, "-m", "coverage", "xml", "-o", str(xml_path)],
            cwd=str(ROOT),
        )
        if ret != 0:
            print("[floors] coverage xml 生成失败", file=sys.stderr)
            return {}
    else:
        cmd = [
            sys.executable, "-m", "pytest",
            "--cov-report=xml:" + str(xml_path),
            "-q",
        ]
        print("[floors] 运行全量测试（coverage xml）...")
        ret = subprocess.call(cmd, cwd=str(ROOT))
        if ret != 0 and not xml_path.exists():
            print("[floors] 测试运行失败且无 coverage 产物", file=sys.stderr)
            return {}

    tree = ET.parse(xml_path)
    results: dict[str, float] = {}

    # 主路径：coverage XML 的 <package> 元素自带正确的整包聚合 line-rate
    package_rates = {
        pkg_el.get("name", ""): float(pkg_el.get("line-rate", 0)) * 100
        for pkg_el in tree.iter("package")
    }

    for pkg in _FLOORS:
        if pkg in package_rates:
            results[pkg] = package_rates[pkg]
            continue
        # 兜底：按 class filename 前缀聚合，逐行统计（兼容 package 名
        # 含路径前缀或缺失的 coverage 版本差异）
        hit = total = 0
        for cls in tree.iter("class"):
            fname = cls.get("filename", "").replace("\\", "/")
            if fname.startswith(pkg + "/"):
                for line in cls.iter("line"):
                    total += 1
                    if int(line.get("hits", 0)) > 0:
                        hit += 1
        if total:
            results[pkg] = hit / total * 100

    xml_path.unlink(missing_ok=True)  # 临时产物清理
    return results


def check_floors(actual: dict[str, float]) -> int:
    """对照地板检查，返回退出码（0=过 / 1=有低于地板）。"""
    failures: list[str] = []
    print(f"{'包':<12} {'实测':>8} {'地板':>8} {'判定':>6}")
    print("-" * 40)
    for pkg, floor in sorted(_FLOORS.items()):
        got = actual.get(pkg)
        if got is None:
            print(f"{pkg:<12} {'N/A':>8} {floor:>8.1f} {'⚠️缺':>6}")
            failures.append(f"{pkg}: 无覆盖数据（包名未匹配或未跑）")
            continue
        ok = got >= floor
        print(f"{pkg:<12} {got:>7.1f}% {floor:>7.1f}% {'✅' if ok else '❌':>4}")
        if not ok:
            failures.append(f"{pkg}: {got:.1f}% < 地板 {floor:.1f}%")
    if failures:
        print("\n[floors] 未达地板：", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        return 1
    print("\n[floors] 全部达标（棘轮只升不降，提升后请上调 _FLOORS）")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--json", help="输出各包明细 JSON 路径")
    p.add_argument("--from-existing", action="store_true",
                   help="复用已有 .coverage 数据（CI：pytest 门禁后接跑，不重跑测试）")
    args = p.parse_args()

    actual = run_coverage(from_existing=args.from_existing)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"actual": actual, "floors": _FLOORS}, ensure_ascii=False,
                       indent=2),
            encoding="utf-8",
        )
        print(f"[floors] 明细已写入: {args.json}")
    return check_floors(actual)


if __name__ == "__main__":
    raise SystemExit(main())

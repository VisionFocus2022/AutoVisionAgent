#!/usr/bin/env python
"""i18n 词条提取工具（对标 SKolpha read_chinese.py）。

扫描源码中所有 tr("...") 调用，提取中文字符串并生成翻译词条清单。

用法::

    python scripts/extract_i18n.py [--output i18n_terms.txt]

输出未翻译词条列表（即 _EN_US 字典中缺失的键）。
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def extract_tr_strings(root: Path) -> set[str]:
    """扫描源码，提取所有 tr("...") 中的字符串。"""
    pattern = re.compile(r'tr\(\s*["\']([^"\']+)["\']\s*\)')
    strings: set[str] = set()

    skip_dirs = {".venv", "__pycache__", ".git", "dist", "build", ".pytest_cache"}
    skip_exts = {".pyc", ".pyo"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            ext = Path(f).suffix
            if ext in skip_exts or ext != ".py":
                continue
            filepath = Path(dirpath) / f
            try:
                content = filepath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in pattern.finditer(content):
                strings.add(m.group(1))

    return strings


def check_translations(source_strings: set[str], i18n_path: Path) -> None:
    """检查哪些字符串在 _EN_US 字典中缺失。"""
    try:
        content = i18n_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"ERROR: i18n.py not found at {i18n_path}")
        return

    # 提取字典中已有的键
    dict_pattern = re.compile(r'"([^"]+)":\s*"([^"]*)"')
    existing = set()
    for m in dict_pattern.finditer(content):
        existing.add(m.group(1))

    missing = source_strings - existing
    unused = existing - source_strings - {"AutoVisionAgent"}

    print(f"Source strings (tr() calls): {len(source_strings)}")
    print(f"Dictionary entries: {len(existing)}")
    print(f"Missing translations: {len(missing)}")
    print(f"Unused entries: {len(unused)}")

    if missing:
        print("\n--- Missing Translations ---")
        for s in sorted(missing):
            print(f'    "{s}": "",')

    if unused:
        print("\n--- Unused Entries (may be dynamic) ---")
        for s in sorted(unused):
            print(f'    "{s}"')


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract i18n terms from source code")
    parser.add_argument(
        "--root", default=".", help="Project root directory to scan"
    )
    parser.add_argument(
        "--output", default=None, help="Output file (default: stdout)"
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    i18n_path = root / "gui" / "core" / "i18n.py"

    if not i18n_path.exists():
        # Try relative to script location
        script_dir = Path(__file__).resolve().parent
        root = script_dir.parent
        i18n_path = root / "gui" / "core" / "i18n.py"

    print(f"Scanning: {root}")
    strings = extract_tr_strings(root)
    check_translations(strings, i18n_path)

    if args.output:
        out = Path(args.output)
        with open(out, "w", encoding="utf-8") as f:
            for s in sorted(strings):
                f.write(f"{s}\n")
        print(f"\nWrote {len(strings)} strings to {out}")


if __name__ == "__main__":
    main()

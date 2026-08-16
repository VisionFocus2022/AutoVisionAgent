#!/usr/bin/env python
"""i18n 完整性检查 — 缺失键 + 空 retranslate + 重复键。

用法:  python scripts/check_i18n.py [--fix]
  --fix  自动生成 _missing_keys.txt 供人工翻译

退出码: 0 = 全部通过, 1 = 有缺失
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui"
I18N_FILE = GUI / "core" / "i18n.py"

# ---- 1. 收集所有 tr() 调用的字符串 ----
tr_pattern = re.compile(r"""tr\(\s*["']([^"']+)["']\s*\)""")
all_tr_strings: set[str] = set()
skip_dirs = {".venv", "__pycache__", ".git", "dist", "build", ".pytest_cache"}

for dirpath, dirnames, filenames in os.walk(str(ROOT)):
    dirnames[:] = [d for d in dirnames if d not in skip_dirs]
    for f in filenames:
        if not f.endswith(".py"):
            continue
        fp = Path(dirpath, f)
        try:
            content = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in tr_pattern.finditer(content):
            all_tr_strings.add(m.group(1))

# ---- 2. 解析 _EN_US 字典 ----
i18n_content = I18N_FILE.read_text(encoding="utf-8")
dict_pattern = re.compile(r'"([^"]+)":\s*"([^"]*)"')
existing_keys: set[str] = set()
for m in dict_pattern.finditer(i18n_content):
    existing_keys.add(m.group(1))

missing = all_tr_strings - existing_keys

# ---- 3. 检查空 retranslate() ----
retranslate_pattern = re.compile(
    r"def retranslate\(self\)[^:]*:\s*\n\s+(?:pass\s*$|\"\"\".*?\"\"\"\s*\n\s+pass\s*$)",
    re.MULTILINE | re.DOTALL,
)
empty_retranslate: list[str] = []

for dirpath, dirnames, filenames in os.walk(str(GUI)):
    dirnames[:] = [d for d in dirnames if d not in skip_dirs]
    for f in filenames:
        if not f.endswith(".py"):
            continue
        fp = Path(dirpath, f)
        try:
            content = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        if retranslate_pattern.search(content):
            empty_retranslate.append(str(fp.relative_to(ROOT)))

# ---- 4. 检查重复键 ----
key_pattern = re.compile(r'^(\s*)"([^"]+)":\s*"', re.MULTILINE)
seen_keys: dict[str, int] = {}
for m in key_pattern.finditer(i18n_content):
    k = m.group(2)
    seen_keys[k] = seen_keys.get(k, 0) + 1
duplicates = {k: c for k, c in seen_keys.items() if c > 1}

# ---- 5. 输出报告 ----
report_lines: list[str] = []
has_issues = False

if missing:
    has_issues = True
    report_lines.append(f"❌ MISSING i18n KEYS ({len(missing)}):")
    for s in sorted(missing):
        report_lines.append(f'    "{s}": "",')
    # 写入文件供人工翻译
    out = ROOT / "_missing_keys.txt"
    out.write_text(
        "\n".join(f'    "{s}": "",' for s in sorted(missing)) + "\n",
        encoding="utf-8",
    )
else:
    report_lines.append("✅ All tr() strings have EN_US translations.")

if empty_retranslate:
    has_issues = True
    report_lines.append(f"\n❌ EMPTY retranslate() in {len(empty_retranslate)} file(s):")
    for f in empty_retranslate:
        report_lines.append(f"    {f}")
else:
    report_lines.append("\n✅ All retranslate() methods are implemented.")

if duplicates:
    has_issues = True
    report_lines.append(f"\n❌ DUPLICATE keys ({len(duplicates)}):")
    for k, c in sorted(duplicates.items()):
        report_lines.append(f'    "{k}" appears {c} times')
else:
    report_lines.append("\n✅ No duplicate keys in _EN_US.")

report = "\n".join(report_lines)
report_file = ROOT / "_i18n_report.txt"
report_file.write_text(report, encoding="utf-8")

print(f"Report written to {report_file}")
if has_issues:
    print(report)
    sys.exit(1)
else:
    print("All i18n checks passed!")
    sys.exit(0)

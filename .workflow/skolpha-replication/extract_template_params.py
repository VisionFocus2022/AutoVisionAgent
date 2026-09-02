"""W56-0（Task 1 步骤 2）：SKolpha TrainConfigs 解密提取参数初值。

只读取证（授权链：docs/prd-skolpha-replication.md §6.3 / §8.1——
密钥已实证 wave1 §5，本脚本不写 SKolpha 安装目录任何文件）。

产物：
- .workflow/skolpha-replication/decrypted_trainconfigs/*.yaml|py —— 明文留档（可复核）
- configs/train_templates/_source_dict.json —— 参数初值字典（W57 Task 5 转正式 YAML 的草值）
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

from cryptography.fernet import Fernet

# 密钥推导（wave1 §5 实证：frontend/utils/json_encrypt_helper._key）
_KEY = base64.urlsafe_b64encode(b"SAMSUNSAMSUNSAMSUNSAMSUNSAMSUNCN")

BASE = Path(r"E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18\TrainConfigs")
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "decrypted_trainconfigs"
DICT_OUT = HERE.parents[1] / "configs" / "train_templates" / "_source_dict.json"

# my_ 前缀参数（mm 系 .py 模板自研参数）+ 常见裸键（mean/std/img_scale 归一化族）
_PARAM_RE = re.compile(r"\b(my_[A-Za-z0-9_]+)\s*=\s*([^,\n\]}]+)")


def main() -> int:
    f = Fernet(_KEY)
    result: dict = {}
    for p in sorted(BASE.iterdir()):
        if p.suffix not in (".yaml", ".py"):
            continue
        try:
            text = f.decrypt(p.read_bytes()).decode("utf-8")
        except Exception as exc:  # noqa: BLE001  # 解密失败逐文件留档（诚实降级）
            result.setdefault("_errors", {})[p.name] = str(exc)[:100]
            continue
        (OUT_DIR / p.name).write_text(text, encoding="utf-8")
        params = {
            m.group(1): m.group(2).strip().strip("'\"")
            for m in _PARAM_RE.finditer(text)
        }
        # 文件名形态 NN_s_{task}_{variant}_vX.Y(.ext)：01_s_pseg_normal_v1.4.py → pseg/normal
        stem_parts = p.stem.split("_")
        task_code = stem_parts[2] if len(stem_parts) >= 4 else p.stem
        variant = stem_parts[3] if len(stem_parts) >= 4 else "normal"
        result.setdefault(task_code, {})[p.stem] = {
            "file": p.name,
            "format": p.suffix.lstrip("."),
            "variant": variant,
            "param_count": len(params),
            "params": params,
        }
    DICT_OUT.parent.mkdir(parents=True, exist_ok=True)
    DICT_OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tasks = [k for k in result if not k.startswith("_")]
    total_params = sum(
        entry["param_count"]
        for per_task in result.values() if isinstance(per_task, dict)
        for entry in per_task.values() if isinstance(entry, dict)
    )
    print(f"tasks={tasks}")
    print(f"total_my_params={total_params}")
    print(f"dict={DICT_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

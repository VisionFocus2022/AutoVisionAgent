"""serving/proto 生成脚本（L8，2026-10-05 一轮审查）。

背景：pb2 重新生成此前依赖手工步骤——protoc 生成 + 手工修正
_pb2_grpc.py 的包内相对导入（import autovisionagent_pb2 → from
serving.proto import ...），生成物入库无 hash 对账。人肉步骤易漂移。

本脚本固化完整链路：
1. grpc_tools.protoc 生成 pb2 / pb2_grpc；
2. 自动修正 _pb2_grpc.py 的绝对导入为包内相对导入；
3. 与入库版本 diff：无 proto 变更时零 diff（生成物对账）。

用法：
    python scripts/gen_proto.py          # 生成 + 修正 + diff 摘要
    python scripts/gen_proto.py --check  # 仅对账（CI 用，diff 非空退出 1）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "serving" / "proto"
PROTO_FILE = PROTO_DIR / "autovisionagent.proto"

# protoc 生成的绝对导入 → 包内导入（历史上手工修正的两行）
_IMPORT_FIXES = [
    (
        "import autovisionagent_pb2 as autovisionagent__pb2",
        "from serving.proto import autovisionagent_pb2 as autovisionagent__pb2",
    ),
]


def regenerate(python_exe: str) -> int:
    """protoc 生成 + 相对导入修正。"""
    cmd = [
        python_exe, "-m", "grpc_tools.protoc",
        "-I", str(PROTO_DIR),
        f"--python_out={PROTO_DIR}",
        f"--grpc_python_out={PROTO_DIR}",
        str(PROTO_FILE),
    ]
    print("[gen_proto] 运行:", " ".join(cmd))
    ret = subprocess.call(cmd)
    if ret != 0:
        print("[gen_proto] protoc 失败", file=sys.stderr)
        return ret

    grpc_py = PROTO_DIR / "autovisionagent_pb2_grpc.py"
    text = grpc_py.read_text(encoding="utf-8")
    for old, new in _IMPORT_FIXES:
        if old in text:
            text = text.replace(old, new)
            print(f"[gen_proto] 已修正导入: {old!r} → {new!r}")
    grpc_py.write_text(text, encoding="utf-8")
    print("[gen_proto] 生成完成:", PROTO_DIR / "autovisionagent_pb2.py")
    return 0


def check_drift() -> int:
    """对账：重新生成到临时目录，与入库版本 diff（CI 防漂移）。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cmd = [
            sys.executable, "-m", "grpc_tools.protoc",
            "-I", str(PROTO_DIR),
            f"--python_out={td}",
            f"--grpc_python_out={td}",
            str(PROTO_FILE),
        ]
        ret = subprocess.call(cmd, stdout=subprocess.DEVNULL)
        if ret != 0:
            print("[gen_proto:check] protoc 失败", file=sys.stderr)
            return 1
        for name in ("autovisionagent_pb2.py", "autovisionagent_pb2_grpc.py"):
            fresh = (Path(td) / name).read_text(encoding="utf-8")
            # 应用同款导入修正再比对
            for old, new in _IMPORT_FIXES:
                fresh = fresh.replace(old, new)
            committed = (PROTO_DIR / name).read_text(encoding="utf-8")
            if fresh != committed:
                print(
                    f"[gen_proto:check] 漂移: {name} 与 proto 不一致，"
                    f"请运行 python scripts/gen_proto.py 后提交",
                    file=sys.stderr,
                )
                return 1
    print("[gen_proto:check] 生成物与 proto 一致（无漂移）")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="仅对账不落盘（CI）")
    args = p.parse_args()
    if args.check:
        return check_drift()
    return regenerate(sys.executable)


if __name__ == "__main__":
    raise SystemExit(main())

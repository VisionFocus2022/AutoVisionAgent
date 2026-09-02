"""AC-010 实机动态观察（只读取证，2026-09-02）。

启动 SKolpha 3.3.2 → UIA 被动枚举窗口控件树 + 截图 → taskkill 清场。
纪律：
- 零输入注入（不 SendInput/不鼠标键盘）；仅 UIA 属性读取。
- 不点击任何按钮（导航也不点——首轮只看启动后可达面）。
- 不保存/不新建任何工程；进程树 taskkill /T /F 收尾。
产物：.workflow/skolpha-replication/live_observe/{run.log, tree_*.txt, shot_*.png}
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import uiautomation as ua
from PIL import ImageGrab

EXE = r"E:\计算机视觉\最新版-SKolpha3.3.2-更新日期2024.11.18\skolpha.exe"
OUT = Path(__file__).resolve().parent / "live_observe"
OUT.mkdir(exist_ok=True)

KEYWORDS = (
    "切割", "斜线", "交互式", "多边形", "矩形", "画笔", "关键点",
    "自动标注", "批量预测", "标注", "预测",
)


def log(msg: str) -> None:
    print(msg, flush=True)


def walk_tree(ctrl: ua.Control, depth: int, lines: list[str]) -> None:
    try:
        name = ctrl.Name or ""
        cls = ctrl.ClassName or ""
        lines.append("  " * depth + f"{ctrl.ControlTypeName} cls={cls} name={name!r}")
    except Exception as exc:  # noqa: BLE001 — 单控件读取失败不终止整树
        lines.append("  " * depth + f"<read-err {exc}>")
        return
    if depth >= 14:
        return
    try:
        kids = ctrl.GetChildren()
    except Exception:
        kids = []
    for k in kids[:300]:
        walk_tree(k, depth + 1, lines)


def dump_window(win: ua.Control, tag: str) -> list[str]:
    lines: list[str] = []
    walk_tree(win, 0, lines)
    (OUT / f"tree_{tag}.txt").write_text("\n".join(lines), encoding="utf-8")
    try:
        r = win.BoundingRectangle
        if r.right > r.left and r.bottom > r.top:
            ImageGrab.grab(
                bbox=(r.left, r.top, r.right, r.bottom), all_screens=True
            ).save(OUT / f"shot_{tag}.png")
    except Exception as exc:  # noqa: BLE001 — 截图失败不影响树取证
        log(f"shot_{tag} err: {exc}")
    hits = [ln for ln in lines if any(k in ln for k in KEYWORDS)]
    log(f"[{tag}] controls={len(lines)} keyword_hits={len(hits)}")
    for h in hits[:40]:
        log(f"[{tag}] HIT {h.strip()}")
    return lines


def main() -> int:
    proc = subprocess.Popen([EXE], cwd=os.path.dirname(EXE))
    try:
        return _observe(proc)
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
        log("cleanup done")


def _observe(proc: subprocess.Popen) -> int:
    pid = proc.pid
    log(f"launched pid={pid}")
    ua.SetGlobalSearchTimeout(1)

    deadline = time.time() + 100
    wins: list[ua.Control] = []
    while time.time() < deadline:
        time.sleep(4)
        try:
            wins = [
                c
                for c in ua.GetRootControl().GetChildren()
                if c.ProcessId == pid and c.ControlTypeName == "WindowControl"
            ]
        except Exception as exc:  # noqa: BLE001 — 桌面枚举瞬时失败重试
            log(f"poll err: {exc}")
            continue
        log(f"poll: {len(wins)} windows "
            + ", ".join(f"{w.Name!r}" for w in wins))
        if wins:
            break
    if not wins:
        log("NO_WINDOW")
        return 2

    time.sleep(8)  # 等 UI 稳定（Qt 冷启动/字体/样式加载）
    # 重新枚举一轮（首窗可能是启动闪屏，稳态窗口集更全）
    try:
        wins = [
            c
            for c in ua.GetRootControl().GetChildren()
            if c.ProcessId == pid and c.ControlTypeName == "WindowControl"
        ]
    except Exception as exc:  # noqa: BLE001
        log(f"re-enumerate err: {exc}")

    for i, w in enumerate(wins):
        try:
            tag = f"w{i}_{(w.Name or 'noname')[:12].replace('/', '_')}"
        except Exception:
            tag = f"w{i}_noname"
        dump_window(w, tag)
    log("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

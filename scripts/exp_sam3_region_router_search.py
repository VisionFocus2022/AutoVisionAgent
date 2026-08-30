"""SAM3 区域分割路由器离线搜索（W54 · T3c 证据分析）。

输入：weights/sam3-pole-ft/router_diag_w54.json（exp_sam3_region_router_diag.py 落盘：
每 (图, margin) 记录直发/±16 双臂特征与 IoU，均对用户盒裁剪后计）。

分析（全部离线 CPU，零前向）：
  1. 逐 margin 双臂基线：direct / tight / oracle-max(direct, tight) 上限
  2. 路由规则族网格搜索：规则只用直发臂**先验可观测**特征（fill/spill/bbox_in）
     ——运行时序：直发前向已付出 → 规则判定是否追加 ±16 紧提示前向
  3. 单一全局规则跨 margin 评估（margin 运行时不可知——用户画盒松紧无从感知）
  4. AC-2 证据门（PRD）：m=0 mean ≥0.74 且 m=16 ≥0.45 且 m=64 ≥0.30

路由语义（与运行时对齐）：
  - 直发零实例：产线返回空（诊断未采 tight——证据盲区，计数单列）
  - 判 tight 且 tight 零实例：回退直发结果（两手都在，取能出的）
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO_ROOT = Path(r"E:/学习项目/视觉大模型")
SRC = REPO_ROOT / "weights/sam3-pole-ft/router_diag_w54.json"
MARGINS = (0, 8, 16, 64)


def load() -> dict:
    records = json.loads(SRC.read_text(encoding="utf-8"))
    by_m: dict[int, list] = {m: [] for m in MARGINS}
    zero_direct = 0
    for r in records:
        m = r["m"]
        d, t = r.get("direct"), r.get("tight")
        if d is None:
            zero_direct += 1
            continue  # 直发零实例：产线无路由余地（盲区单列）
        fill, spill = d["fill"], d["spill"]
        # 派生特征 r：掩码面积/盒面积 = fill/(1-spill)（fill>0 时恒等可导）
        ratio = fill / (1 - spill) if spill < 1 else 99.0
        by_m[m].append({
            "fill": fill, "spill": spill, "bbox_in": d["bbox_in"], "r": ratio,
            "area": d["area"], "_img": r["img"],
            "d_iou": d["iou"],
            "t_iou": t["iou"] if t else None,  # None=tight 零实例
        })
    return by_m, zero_direct


def routed_final(row, rule) -> float:
    """规则判 tight → 取 tight（零实例回退直发）；判 direct → 直发。"""
    if rule(row):
        return row["d_iou"] if row["t_iou"] is None else row["t_iou"]
    return row["d_iou"]


def evaluate(by_m, rule, name) -> dict:
    out = {"rule": name}
    for m in MARGINS:
        rows = by_m[m]
        ious = [routed_final(r, rule) for r in rows]
        tight_rate = sum(1 for r in rows if rule(r)) / len(rows)
        out[m] = (float(np.mean(ious)), tight_rate)
    out["ac2"] = (
        out[0][0] >= 0.74 and out[16][0] >= 0.45 and out[64][0] >= 0.30
    )
    return out


def fmt(ev) -> str:
    parts = [f"m={m}:{ev[m][0]:.3f}(紧{ev[m][1]:.0%})" for m in MARGINS]
    return f"[{'PASS' if ev['ac2'] else 'fail'}] {ev['rule']:<42} " + " ".join(parts)


def main() -> None:
    by_m, zero_direct = load()
    n = {m: len(by_m[m]) for m in MARGINS}
    print(f"[search] 样本 n={n}，直发零实例(盲区)={zero_direct}", flush=True)

    # ---- 1. 双臂基线与 oracle 上限 ----
    for m in MARGINS:
        rows = by_m[m]
        d = np.array([r["d_iou"] for r in rows])
        t = np.array([r["t_iou"] if r["t_iou"] is not None else r["d_iou"] for r in rows])
        o = np.array([max(r["d_iou"], r["t_iou"] if r["t_iou"] is not None else -1) for r in rows])
        print(
            f"[base m={m:2}] direct={d.mean():.3f}  tight={t.mean():.3f}  "
            f"oracle={o.mean():.3f}  Δ(oracle-direct)={o.mean()-d.mean():+.3f}",
            flush=True,
        )

    # ---- 2. 规则族网格搜索 v2（单一全局规则，跨 margin） ----
    # v1 教训：单特征最接近的 bbox_in<0.95 只差 m=0 线 0.010，败在紧框
    # 正确抓取的 bbox 也轻微出盒——需要第二特征削 m=0 误路由（理想率≈15%，
    # bbox_in<0.95 实际 54%）。v2：bbox_in 细网格 × 二条件组合 + 派生 r。
    cands = [
        ("恒 direct（W53 形单发基线）", lambda r: False),
        ("恒 tight（A1 全紧）", lambda r: True),
    ]
    bi_grid = np.arange(0.80, 0.995, 0.01)
    for tau in np.arange(0.05, 1.0, 0.05):
        cands.append((f"spill>{tau:.2f}", (lambda th: lambda r: r["spill"] > th)(tau)))
        cands.append((f"fill<{tau:.2f}", (lambda th: lambda r: r["fill"] < th)(tau)))
        cands.append((f"bbox_in<{tau:.2f}", (lambda th: lambda r: r["bbox_in"] < th)(tau)))
    for t1 in bi_grid:
        cands.append((f"bbox_in<{t1:.2f}", (lambda th: lambda r: r["bbox_in"] < th)(t1)))
        for t2 in np.arange(0.05, 0.6, 0.05):
            cands.append((
                f"bbox_in<{t1:.2f}&spill>{t2:.2f}",
                (lambda x, y: lambda r: r["bbox_in"] < x and r["spill"] > y)(t1, t2),
            ))
        for f2 in np.arange(0.3, 0.95, 0.05):
            cands.append((
                f"bbox_in<{t1:.2f}&fill<{f2:.2f}",
                (lambda x, y: lambda r: r["bbox_in"] < x and r["fill"] < y)(t1, f2),
            ))
            cands.append((
                f"bbox_in<{t1:.2f}|fill<{f2:.2f}",
                (lambda x, y: lambda r: r["bbox_in"] < x or r["fill"] < y)(t1, f2),
            ))
        for s2 in np.arange(0.1, 0.7, 0.1):
            # 三条件：bbox_in 低且（spill 高或 fill 低）
            for f3 in np.arange(0.3, 0.8, 0.1):
                cands.append((
                    f"bi<{t1:.2f}&(sp>{s2:.1f}|fi<{f3:.1f})",
                    (lambda x, y, z: lambda r: r["bbox_in"] < x and (r["spill"] > y or r["fill"] < z))(t1, s2, f3),
                ))

    results = [evaluate(by_m, rule, name) for name, rule in cands]

    # ---- 3. 决策树（5 折 CV，OOF 口径）----
    print(f"\n[search] 规则网格 {len(results)} 条 → 达标 "
          f"{sum(1 for ev in results if ev['ac2'])} 条", flush=True)
    try:
        from sklearn.model_selection import KFold
        from sklearn.tree import DecisionTreeClassifier, export_text
        all_rows = [r for m in MARGINS for r in by_m[m]]
        X = np.array([[r["fill"], r["spill"], r["bbox_in"], r["r"]] for r in all_rows])
        y = np.array([1 if (r["t_iou"] if r["t_iou"] is not None else r["d_iou"]) > r["d_iou"] else 0
                      for r in all_rows])
        m_arr = np.array([m for m in MARGINS for _ in by_m[m]])
        for depth in (2, 3, 4):
            oof = np.zeros(len(all_rows), dtype=int)
            for tr_i, te_i in KFold(5, shuffle=True, random_state=42).split(X):
                clf = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=15, random_state=42)
                clf.fit(X[tr_i], y[tr_i])
                oof[te_i] = clf.predict(X[te_i])
            for tag, pred in (("样本内", clf.fit(X, y).predict(X)), ("OOF", oof)):
                means = {}
                for m in MARGINS:
                    sel = m_arr == m
                    ious = [
                        routed_final(all_rows[i], lambda _, p=pred[i]: p == 1)
                        for i in np.where(sel)[0]
                    ]
                    means[m] = float(np.mean(ious))
                ok = means[0] >= 0.74 and means[16] >= 0.45 and means[64] >= 0.30
                print(f"[tree d={depth} {tag}] " + " ".join(
                    f"m={m}:{means[m]:.3f}" for m in MARGINS)
                    + f"  AC-2={'PASS' if ok else 'fail'}", flush=True)
            print("[tree rules]\n" + export_text(
                DecisionTreeClassifier(max_depth=depth, min_samples_leaf=15, random_state=42).fit(X, y),
                feature_names=["fill", "spill", "bbox_in", "r"]), flush=True)
    except ImportError:
        print("[search] sklearn 未装，跳过决策树", flush=True)

    # ---- 3b. 双臂全跑择优族（恒 2 前向，零 GT 下的两臂特征对比选择）----
    # v1/v2 教训：先验特征路由 1419 条 + CV 树全灭（直发臂几何签名不含
    # 「盒松不松」信息）。本族换范式：两臂都跑，按两臂各自特征择一。
    # 核心假设「信留在盒内的掩码」：spill 低者胜（m=0 直发缺陷 spill≈0
    # vs 紧臂越盒；m=16 直发大结构 spill 高 vs 紧臂缺陷贴盒）。
    def tight_feats(r):
        return r.get("tf") or {}

    print("\n[select] 双臂择优族（恒 2 前向）", flush=True)
    sels = [
        ("min spill（信盒内掩码）", lambda d, t: t["spill"] < d["spill"]),
        ("min area（信小掩码）", lambda d, t: t["area"] < d["area"]),
        ("max bbox_in", lambda d, t: t["bbox_in"] > d["bbox_in"]),
        ("min r=area/box（信小占比）", lambda d, t: t["fill"] / max(1 - t["spill"], 1e-6) < d["fill"] / max(1 - d["spill"], 1e-6)),
    ]
    # 需要两臂特征：从原始 JSON 重建（load() 只存了 direct 特征与双臂 IoU）
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    for m in MARGINS:
        for r, rr in zip(by_m[m], [x for x in raw if x["m"] == m], strict=True):
            r["tf"] = rr["tight"]
            r["area"] = rr["direct"]["area"]
    for name, better_tight in sels:
        out = {}
        for m in MARGINS:
            ious = []
            for r in by_m[m]:
                t = r["tf"]
                pick_t = better_tight(
                    {"fill": r["fill"], "spill": r["spill"], "bbox_in": r["bbox_in"],
                     "area": r.get("area", 0)}, t)
                ious.append(r["t_iou"] if (pick_t and r["t_iou"] is not None) else r["d_iou"])
            out[m] = float(np.mean(ious))
        ok = out[0] >= 0.74 and out[16] >= 0.45 and out[64] >= 0.30
        print(f"[{'PASS' if ok else 'fail'}] {name:<24} "
              + " ".join(f"m={m}:{out[m]:.3f}" for m in MARGINS), flush=True)

    # ---- 3c. 路由 v4：f=0.5 缩放臂二级参照（area 比 = 松盒检测器）----
    # 双臂特征在 m=0 误路由尾部重叠（fill 无法分）；v4 引入第三前向：
    # f05 提示（半尺度+16 下限）掩码面积 vs 直发掩码面积——同物比值≈1，
    # 直发抓大结构则 f05 抓真目标 → 比值≪1。数据：f05_arm_w54.json。
    F05 = REPO_ROOT / "weights/sam3-pole-ft/f05_arm_w54.json"
    if F05.exists():
        f05 = json.loads(F05.read_text(encoding="utf-8"))
        f05_map = {(r["img"], r["m"]): r.get("f05") for r in f05}
        miss = sum(1 for k in f05_map if f05_map[k] is None)
        for m in MARGINS:
            for r in by_m[m]:
                f = f05_map.get((r["_img"], m))
                if f:
                    r["ratio"] = f["area"] / max(r["area"], 1)
                    r["f05_fill_prompt"] = f["fill_prompt"]
                    r["f05_iou"] = f["iou"]
        print(f"\n[v4] f05 记录 {len(f05)} 条（None {miss}），ratio 特征已 join", flush=True)
        # 三臂 oracle 上限（f05=A2-50 臂，T2 实测 m=16 0.620 优于 tight）
        for m in MARGINS:
            rows = [r for r in by_m[m] if "f05_iou" in r]
            o3 = np.array([max(r["d_iou"], r["t_iou"] or -1, r["f05_iou"]) for r in rows])
            f05_mean = np.array([r["f05_iou"] for r in rows]).mean()
            print(f"[v4-base m={m:2}] f05臂={f05_mean:.3f}  三臂oracle={o3.mean():.3f}", flush=True)

        def routed_v4(r, rule, target):
            if not rule(r):
                return r["d_iou"]
            if target == "tight":
                return r["d_iou"] if r["t_iou"] is None else r["t_iou"]
            return r.get("f05_iou", r["d_iou"])

        # ⚠️ 只搜可实现目标（tight / f05）。曾有 "→best"（路由时取
        # max(direct,tight,f05) 的 IoU）——那是 oracle 作弊：生产无 GT
        # 算不出 max，曾让 13 条规则假性过门，被 m=0 fired-subset
        # win/loss 审计逮住（m=0 触发 9/162 全输 0.828→0.250）后删除。
        v4 = []  # (name, rule_fn, target)
        for thr in (0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6):
            for target in ("tight", "f05"):
                v4.append((
                    f"ratio≤{thr:.2f}→{target}",
                    (lambda th: lambda r: r.get("ratio", 1.0) <= th)(thr),
                    target,
                ))
        for tbi in (0.90, 0.94, 0.96):
            for thr in (0.4, 0.5, 0.6):
                for target in ("tight", "f05"):
                    v4.append((
                        f"bi<{tbi:.2f}&ratio≤{thr:.1f}→{target}",
                        (lambda a, b: lambda r: r["bbox_in"] < a and r.get("ratio", 1.0) <= b)(tbi, thr),
                        target,
                    ))
        gate = {0: 0.74, 16: 0.45, 64: 0.30}
        scored = []
        for name, rule, target in v4:
            means = {
                m: float(np.mean([routed_v4(r, rule, target) for r in by_m[m]]))
                for m in MARGINS
            }
            ok = means[0] >= gate[0] and means[16] >= gate[16] and means[64] >= gate[64]
            scored.append((min(means[m] - gate[m] for m in gate), name, means, ok))
        scored.sort(key=lambda x: -x[0])
        for _dmin, name, means, ok in scored[:10]:
            print(f"[{'PASS' if ok else 'fail'}] {name:<28} "
                  + " ".join(f"m={m}:{means[m]:.3f}" for m in MARGINS), flush=True)
        print(f"[v4] 规则 {len(v4)} 条 → AC-2 达标 {sum(1 for s in scored if s[3])} 条", flush=True)
    else:
        print("\n[v4] f05_arm_w54.json 未落盘，跳过 v4 族", flush=True)

    # ---- 4. 输出：AC-2 达标者 + 全场最优（按三线最差距离排序） ----
    passed = [ev for ev in results if ev["ac2"]]
    gate = {0: 0.74, 16: 0.45, 64: 0.30}
    results.sort(key=lambda ev: -min(ev[m][0] - gate[m] for m in gate))
    print(f"\n[search] 规则 {len(results)} 条，AC-2 达标 {len(passed)} 条", flush=True)
    for ev in results[:12]:
        print(fmt(ev), flush=True)
    if passed:
        passed.sort(key=lambda ev: -min(ev[m][0] - gate[m] for m in gate))
        print("\n[search] === AC-2 达标（按最差线余量降序）===", flush=True)
        for ev in passed[:8]:
            print(fmt(ev), flush=True)
    else:
        print("\n[search] === 无规则过 AC-2：见上方 top12 与 oracle 上限 → 走 T4 回滚分支 ===", flush=True)


if __name__ == "__main__":
    main()

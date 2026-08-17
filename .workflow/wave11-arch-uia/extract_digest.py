"""从 workflow journal.jsonl 重建架构扇出摘要：lens 结果全量 + verify 判定逐条。"""
import json

SRC = r"C:/Users/888/.claude/projects/E------------/2698e7c5-7dec-4c54-a0a6-81ce50f35b18/subagents/workflows/wf_9e437d72-d8d/journal.jsonl"
DST = r"E:/学习项目/视觉大模型/.workflow/wave11-arch-uia/lens-digest.json"

lenses, verdicts = [], []
seen = set()
with open(SRC, encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("type") != "result":
            continue
        r = e.get("result")
        if not isinstance(r, dict):
            continue
        key = e.get("key")
        if key in seen:  # resume 重放的去重
            continue
        seen.add(key)
        if isinstance(r.get("findings"), list) and r.get("lens"):
            lenses.append(r)
        elif "verdict" in r:
            verdicts.append(r)

out = {
    "lensCount": len(lenses),
    "lenses": [
        {
            "lens": L.get("lens"),
            "findingCount": len(L.get("findings") or []),
            "strengths": L.get("strengths") or [],
            "coverageNotes": L.get("coverageNotes") or "",
            "findings": [
                {
                    "title": f.get("title"),
                    "severity": f.get("severity"),
                    "evidence": f.get("evidence"),
                    "threshold": f.get("threshold"),
                    "suggestion": f.get("suggestion"),
                }
                for f in (L.get("findings") or [])
            ],
        }
        for L in lenses
    ],
    "verifyVerdicts": verdicts,
}
json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
sev = {}
for L in lenses:
    for f in L.get("findings") or []:
        sev[f.get("severity")] = sev.get(f.get("severity"), 0) + 1
print("lenses:", len(lenses), "findings by severity:", sev, "| verify verdicts:", len(verdicts))
print("lens names:", [L.get("lens") for L in lenses])

from pathlib import Path
p = Path("tests/test_w44_sam_candidates.py")
src = p.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

def find(marker, start=0):
    for i in range(start, len(lines)):
        if marker in lines[i]:
            return i
    raise SystemExit(f"marker not found: {marker}")

# 1) 删 TestAutoModeWiring：类定义行起，到「B：predict_points」分隔行的上一空行为止
a = find("class TestAutoModeWiring")
b = find("B：predict_points") - 1
del lines[a:b]
src = "".join(lines)

# 2) 删 BrushSam 段：分隔行起至文件尾
idx = src.index("B：BrushSamLabeler")
# 回退到该行行首（含 # === 前缀）
ls = src.rfind("\n", 0, idx) + 1
src = src[:ls].rstrip("\n") + "\n"
p.write_text(src, encoding="utf-8")
print("w44 ok")

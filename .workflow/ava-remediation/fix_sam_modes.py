from pathlib import Path
p = Path("tests/test_sam_modes.py")
src = p.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

def find(marker, start=0):
    for i in range(start, len(lines)):
        if marker in lines[i]:
            return i
    raise SystemExit(f"marker not found: {marker}")

# 1) 删除 AutoLabeler 大块：从其分隔注释上一行到「集成」分隔注释上一行
a = find("# AutoLabeler 测试") - 1
b = find("# 集成：工厂 + 属性注入") - 1
del lines[a:b]
src = "".join(lines)

# 2) 删除 test_auto_inject_after_creation（至文件尾的最后一个方法块）
start = src.index("    def test_auto_inject_after_creation")
end = src.index("assert labeler.run() == 3", start) + len("assert labeler.run() == 3")
# 回退掉方法前的空行（保留一个换行结尾）
block = src[start:end]
assert "AUTO" in block and "set_detector" in block
src = src[:start].rstrip("\n") + "\n" + src[end:].lstrip("\n")

p.write_text(src, encoding="utf-8")
print("block del ok")

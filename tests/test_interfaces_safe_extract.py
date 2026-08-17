"""core/interfaces_supervised.py _extract_state_dict_safe 直测（W12 F4 / v2 P1-7）。

R4-7 安全回退路径三条主干（静态方法，无需实例化即可直调；生产调用点为
同类 _safe_torch_load 的回退分支）：
- 正常路径：torch.save 产 zip → 白名单反序列化提取成功且键一致；
- 恶意 pickle：zip 内 data.pkl 引用非白名单类（os.system）→ UnpicklingError 拒绝；
- 非 zip 旧格式：手写非 zip 字节 → RuntimeError 拒绝（生产消息"非 zip 格式"）。

已知缺口（W12 实测，2026-08-17）：含 tensor 存储的 torch.save zip 会因
_RestrictedUnpickler 未覆写 persistent_load 抛
"UnpicklingError: A load persistent id instruction was encountered..."，
经 _safe_torch_load 包装为 RuntimeError（提示重导出）。本簇为纯补测簇、
不持有 core/interfaces_supervised.py，故正常路径用例取 torch.save 真实 zip
格式下的无存储内容（标量 OrderedDict / {"state_dict": ...} 包装）；
待属主簇补 persistent_load 后可升级为真 tensor 用例。
"""
from __future__ import annotations

import pickle
import zipfile
from collections import OrderedDict

import pytest
import torch

from core.interfaces_supervised import AbstractTaskEngine

# _extract_state_dict_safe 是 AbstractTaskEngine 的 staticmethod（:179），
# 类上直取即为普通函数，签名 (path: str, map_location: str = "cpu")。
extract = AbstractTaskEngine._extract_state_dict_safe


def test_safe_extract_normal_zip(tmp_path):
    """正常路径：tmp_path 里 torch.save 产 zip → 安全提取成功且键一致。"""
    flat = OrderedDict([("conv.weight", 0.5), ("conv.bias", 0.1)])
    flat_path = tmp_path / "flat.pt"
    torch.save(flat, str(flat_path))

    # torch 2.x 默认产物即 zip 容器（含 <archive>/data.pkl）
    assert zipfile.is_zipfile(str(flat_path))
    out = extract(str(flat_path))

    assert isinstance(out, OrderedDict)
    assert list(out.keys()) == list(flat.keys())
    assert dict(out) == dict(flat)

    # 完整 checkpoint 包装：{"state_dict": ...} → 返回内层 state_dict
    ckpt = {"state_dict": OrderedDict([("w", 1.0), ("b", 2.0)])}
    ckpt_path = tmp_path / "ckpt.pt"
    torch.save(ckpt, str(ckpt_path))
    inner = extract(str(ckpt_path))

    assert isinstance(inner, OrderedDict)
    assert list(inner.keys()) == ["w", "b"]
    assert dict(inner) == {"w": 1.0, "b": 2.0}


def test_safe_extract_rejects_non_whitelisted_class(tmp_path):
    """恶意 pickle：非白名单类引用（os.system）→ UnpicklingError 拒绝。"""
    # 手工 pickle 操作码：PROTO2 + GLOBAL('os','system') + STOP，
    # 加载时经 find_class 解析类引用，即触发白名单拒绝。
    malicious = b"\x80\x02cos\nsystem\n."
    path = tmp_path / "evil.pt"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("archive/data.pkl", malicious)

    assert zipfile.is_zipfile(str(path))
    with pytest.raises(pickle.UnpicklingError, match="不安全的反序列化") as ei:
        extract(str(path))
    assert "os.system" in str(ei.value)


def test_safe_extract_rejects_non_zip_legacy(tmp_path):
    """非 zip 旧格式：手写非 zip 字节 → RuntimeError（非 zip 格式）拒绝。"""
    path = tmp_path / "legacy.pt"
    path.write_bytes(b"\x80\x02}.")  # 旧版裸 pickle 字节，非 zip 容器

    assert not zipfile.is_zipfile(str(path))
    with pytest.raises(RuntimeError, match="非 zip 格式"):
        extract(str(path))


# ---------------------------------------------------------------------------
# W12 F4 属主簇追加（2026-08-17）：真实 tensor 存储提取 + persistent_load
# 安全边界。修复前 _RestrictedUnpickler 未覆写 persistent_load，含 tensor
# 的 torch.save zip 必抛 "A load persistent id instruction was encountered..."
# （经 _safe_torch_load 包装为 RuntimeError）。
# ---------------------------------------------------------------------------


def _persist_id_pickle(pid):
    """构造最小 pickle 字节流：load 时把 pid 喂给 unpickler.persistent_load。

    pickle 协议 2：sentinel 经 Pickler.persistent_id 映射为 pid，
    落盘为 BINPERSID 指令（pid 元组元素照常经 find_class 解析）。
    """
    import io

    sentinel = object()
    out = io.BytesIO()
    pickler = pickle.Pickler(out, protocol=2)
    pickler.persistent_id = lambda obj: pid if obj is sentinel else None
    pickler.dump(sentinel)
    return out.getvalue()


def _write_pid_zip(path, pid, entries=None):
    """写入仅含 archive/data.pkl（喂出 pid）的恶意 zip，可附额外条目。"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("archive/data.pkl", _persist_id_pickle(pid))
        for name, data in (entries or {}).items():
            zf.writestr(name, data)


def test_safe_extract_real_tensor_state_dict(tmp_path):
    """真实 tensor 存储路径：float32/float64 tensor → 提取后形状 dtype 数值一致。

    W12 真值增强（验证员建议）：值取非均匀 arange 序列（ones/zeros 无法
    暴露错位/错 dtype 的静默错误），逐元素 torch.equal 比对保持。
    """
    sd = OrderedDict(
        [
            ("w", torch.arange(6, dtype=torch.float32).reshape(2, 3)),
            ("b", torch.arange(4, dtype=torch.float64) * 0.25 - 0.125),
        ]
    )
    path = tmp_path / "sd.pt"
    torch.save(sd, str(path))

    assert zipfile.is_zipfile(str(path))  # torch 2.x 默认 zip 容器
    out = extract(str(path))

    assert isinstance(out, OrderedDict)
    assert list(out.keys()) == ["w", "b"]
    for key in ("w", "b"):
        assert out[key].shape == sd[key].shape
        assert out[key].dtype == sd[key].dtype
        assert torch.equal(out[key], sd[key])


@pytest.mark.parametrize(
    "case, pid",
    [
        # 五元组形态不符：四元组（缺 numel）
        ("tuple_shape", ("storage", torch.FloatStorage, "0", "cpu")),
        # 五元组形态不符：六元组（legacy view_metadata 形态，zip 格式不支持）
        (
            "tuple_shape_legacy6",
            ("storage", torch.FloatStorage, "0", "cpu", 2, None),
        ),
        # pid[0] 非 'storage'
        ("bad_typename", ("evil", torch.FloatStorage, "0", "cpu", 2)),
        # storage_type 非白名单：find_class 放行（torch 命名空间）但非 storage 类
        ("storage_not_whitelisted", ("storage", torch.device, "0", "cpu", 1)),
        # 超大 numel：4GiB > 2GiB 总量上限（触发前不得读条目/分配内存）
        ("oversized_numel", ("storage", torch.FloatStorage, "0", "cpu", 1 << 30)),
        # numel 非整数 / 负数
        ("numel_not_int", ("storage", torch.FloatStorage, "0", "cpu", "2")),
        ("numel_negative", ("storage", torch.FloatStorage, "0", "cpu", -1)),
        # 非法 location（不做 eval，仅白名单 cpu/''）
        ("bad_location", ("storage", torch.FloatStorage, "0", "cuda:0", 1)),
    ],
)
def test_safe_extract_rejects_malicious_persistent_id(tmp_path, case, pid):
    """恶意持久 ID 各形态 → UnpicklingError 拒绝（不得引入新绕道）。"""
    path = tmp_path / "evil_pid.pt"
    _write_pid_zip(path, pid, entries={"archive/data/0": b"\x00" * 8})

    assert zipfile.is_zipfile(str(path))
    with pytest.raises(pickle.UnpicklingError):
        extract(str(path))


def test_safe_extract_rejects_storage_data_mismatch(tmp_path):
    """持久 ID 合法但 zip 数据条目缺失/长度不符 → UnpicklingError。"""
    # 条目缺失：numel=2（float32 → 期望 8 字节），无 archive/data/0
    path = tmp_path / "missing_entry.pt"
    _write_pid_zip(path, ("storage", torch.FloatStorage, "0", "cpu", 2))
    with pytest.raises(pickle.UnpicklingError):
        extract(str(path))

    # 长度不符：条目存在但仅 7 字节
    path = tmp_path / "short_entry.pt"
    _write_pid_zip(
        path,
        ("storage", torch.FloatStorage, "0", "cpu", 2),
        entries={"archive/data/0": b"\x00" * 7},
    )
    with pytest.raises(pickle.UnpicklingError):
        extract(str(path))


# ---------------------------------------------------------------------------
# W12 安全修复追加（2026-08-17）：find_class 名级精确白名单 + 廉价加固。
# RED 先行——修复前 find_class 对 module.startswith("torch") 一律
# getattr(torch, name)（且第三参默认值急切求值 super().find_class 兜底），
# GLOBAL('torch','save') 经 REDUCE 即可在反序列化期间任意落盘
# （裸 pickle 探针已在系统临时目录实测写出 896 字节 torch zip）。
# ---------------------------------------------------------------------------


def test_safe_extract_rejects_rce_torch_save_reduce(tmp_path):
    """RCE 回归（CRITICAL）：GLOBAL('torch','save')+REDUCE → UnpicklingError 且不落盘。

    手工操作码（协议 2；字节形态先用裸 pickle 在系统临时目录实测可触发
    torch.save 写盘后固化）：PROTO2 / GLOBAL 'torch' 'save' / NONE /
    BINUNICODE <marker 路径> / TUPLE2 / REDUCE / STOP——REDUCE 即执行
    torch.save(None, <路径>)。入口选择：直调 _extract_state_dict_safe
    （生产 _safe_torch_load 回退分支同源；包装层会把异常转 RuntimeError，
    故直调以断言 UnpicklingError 本体）。
    """
    marker = tmp_path / "pwned.marker"
    marker_bytes = str(marker).encode("utf-8")
    evil = (
        b"\x80\x02"  # PROTO 2
        + b"ctorch\nsave\n"  # GLOBAL 'torch' 'save'
        + b"N"  # NONE
        + b"X" + len(marker_bytes).to_bytes(4, "little")
        + marker_bytes  # BINUNICODE marker 路径
        + b"\x86"  # TUPLE2 → (None, 路径)
        + b"R"  # REDUCE → torch.save(None, 路径)
        + b"."  # STOP
    )
    path = tmp_path / "rce.pt"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("archive/data.pkl", evil)

    assert zipfile.is_zipfile(str(path))
    result = None
    raised = None
    try:
        result = extract(str(path))
    except BaseException as exc:  # RED 阶段需捕获任意异常形态留证
        raised = exc
    assert isinstance(raised, pickle.UnpicklingError), (
        f"恶意 data.pkl 未被拒绝：返回值={result!r}，异常={raised!r}，"
        f"marker 落盘={marker.exists()}（{marker}）"
    )
    assert "不安全的反序列化" in str(raised)
    assert "torch.save" in str(raised)
    assert not marker.exists(), f"RCE 实际落盘: {marker}"


def test_safe_extract_rejects_unhashable_storage_type(tmp_path):
    """加固：storage_type 不可哈希（list 字面量）→ TypeError 归一为 UnpicklingError。"""
    path = tmp_path / "unhashable_pid.pt"
    _write_pid_zip(
        path,
        ("storage", [torch.FloatStorage], "0", "cpu", 1),
        entries={"archive/data/0": b"\x00" * 4},
    )

    assert zipfile.is_zipfile(str(path))
    with pytest.raises(pickle.UnpicklingError):
        extract(str(path))


def test_safe_extract_rejects_oversized_data_pkl(tmp_path):
    """加固：data.pkl 单条目解压超上限 → UnpicklingError（pickle 流炸弹面）。

    高压缩比 zip 条目：limit+1 字节全零 deflate 后极小；读侧只允许
    limit+1 字节探测，须在反序列化前以"字节上限"消息拒绝。
    """
    from core import interfaces_supervised

    limit = getattr(
        interfaces_supervised, "_MAX_DATA_PKL_BYTES", 256 * 1024 * 1024
    )
    path = tmp_path / "bomb.pt"
    chunk = b"\x00" * (1 << 20)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("archive/data.pkl", "w", force_zip64=True) as wh:
            written = 0
            while written <= limit:
                wh.write(chunk)
                written += len(chunk)

    assert zipfile.is_zipfile(str(path))
    with pytest.raises(pickle.UnpicklingError, match="字节上限"):
        extract(str(path))


def test_safe_extract_integer_bool_uint8_tensors(tmp_path):
    """int64/bool/uint8 tensor → LongStorage/BoolStorage/ByteStorage 白名单路径提取。

    补真值：非均匀 arange/模运算值逐元素比对，覆盖枚举到的其余 GLOBAL 对。
    """
    sd = OrderedDict(
        [
            ("i", torch.arange(-5, 5, dtype=torch.int64)),
            ("m", torch.arange(9) % 3 == 0),
            ("u", torch.arange(12, dtype=torch.uint8) * 7),
        ]
    )
    path = tmp_path / "int_bool.pt"
    torch.save(sd, str(path))

    out = extract(str(path))
    assert isinstance(out, OrderedDict)
    assert list(out.keys()) == ["i", "m", "u"]
    for key in ("i", "m", "u"):
        assert out[key].shape == sd[key].shape
        assert out[key].dtype == sd[key].dtype
        assert torch.equal(out[key], sd[key])

"""W45·P3-15：本模块已下沉 core/mask_codec.py（gui 跨层消除）。

此处保留 re-export shim——serving/serialization、shared_memory 等既有
引用零改动；新代码一律 import core.mask_codec。
"""
from core.mask_codec import decode_mask_rle, encode_mask_rle

__all__ = ["decode_mask_rle", "encode_mask_rle"]

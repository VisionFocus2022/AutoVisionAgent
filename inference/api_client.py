"""HTTP API 推理客户端（W59-A——FR-007 对标 SKolpha deploymentParams{endpoint, apiKey}）。

SKolpha 推理三路（ultralytics/mm/SAM）+ API 部署形态（endpoint/apiKey
〔🔎 推断级，wave2 §4〕）；AVA 的 gRPC serving 为主路径不动，本模块补
轻量 HTTP 推理源：POST multipart 图像 → JSON boxes 契约。

安全口径（PRD NFR-003）：
- apiKey 不入日志不硬编码——AV_A 环境变量 AVA_API_KEY > 凭据文件
  configs/api_key.txt（.gitignore 防呆，W23 initial_credentials 同型）；
- 异常文案只含 endpoint 与状态码，不回显密钥。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from core.exceptions import ApiInferError
from core.interfaces_supervised import DetectionResult, TaskType

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30.0
API_KEY_ENV = "AVA_API_KEY"
API_KEY_FILENAME = Path("configs") / "api_key.txt"

# 响应契约必填键（缺一即 ApiInferError 点名）
_REQUIRED_KEYS = ("boxes", "labels", "scores")

_VALID_SCHEMES = ("http://", "https://")


def resolve_api_key(path: str | Path | None = None) -> str | None:
    """解析 API 密钥：环境变量 AVA_API_KEY > 凭据文件（None=无密钥）。

    Args:
        path: 凭据文件路径（默认仓内 configs/api_key.txt；测试注入用）。
    """
    env_value = os.environ.get(API_KEY_ENV, "").strip()
    if env_value:
        return env_value
    key_file = Path(path) if path is not None else (
        Path(__file__).resolve().parents[1] / API_KEY_FILENAME
    )
    try:
        value = key_file.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def infer_remote(
    endpoint: str,
    image_path: str,
    timeout: float = DEFAULT_TIMEOUT_S,
    api_key: str | None = None,
) -> DetectionResult:
    """远端 HTTP 推理：POST multipart 图像 → JSON boxes 契约。

    Args:
        endpoint: 服务地址（http/https；如 http://host:port/predict）。
        image_path: 本地图像路径。
        timeout: 请求超时秒。
        api_key: Bearer 密钥（None=匿名）。

    Returns:
        DetectionResult（boxes/labels/scores/task 契约映射）。

    Raises:
        ApiInferError: endpoint 非法/超时/断网/非 200/契约不符
        （文案含 endpoint 供定位，不含密钥）。
    """
    if not endpoint.strip().lower().startswith(_VALID_SCHEMES):
        raise ApiInferError(
            f"endpoint 无效（须 http(s):// 开头）: {endpoint[:60]}",
            endpoint=endpoint,
        )

    import requests

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with open(image_path, "rb") as fh:
            resp = requests.post(
                endpoint,
                files={"image": (os.path.basename(image_path), fh,
                                 "application/octet-stream")},
                headers=headers,
                timeout=timeout,
            )
    except requests.Timeout as exc:
        raise ApiInferError(
            f"远端推理超时（{timeout:.0f}s）: {endpoint}", endpoint=endpoint
        ) from exc
    except requests.RequestException as exc:
        raise ApiInferError(
            f"远端推理失败（网络异常）: {endpoint} — {exc.__class__.__name__}",
            endpoint=endpoint,
        ) from exc
    except OSError as exc:
        raise ApiInferError(
            f"图像读取失败: {image_path}", endpoint=endpoint
        ) from exc

    if resp.status_code != 200:
        raise ApiInferError(
            f"远端推理失败: HTTP {resp.status_code}（{endpoint}）",
            endpoint=endpoint,
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ApiInferError(
            f"远端响应非 JSON: {endpoint}", endpoint=endpoint
        ) from exc
    if not isinstance(payload, dict):
        raise ApiInferError(
            f"远端响应契约不符（非对象）: {endpoint}", endpoint=endpoint
        )

    missing = [k for k in _REQUIRED_KEYS if k not in payload]
    if missing:
        raise ApiInferError(
            f"远端响应缺键: {', '.join(missing)}（{endpoint}）",
            endpoint=endpoint,
        )

    task = TaskType(str(payload.get("task", "det")))
    boxes = tuple(
        tuple(float(v) for v in box) for box in payload.get("boxes") or []
    )
    scores = tuple(float(s) for s in payload.get("scores") or [])
    labels = tuple(str(lb) for lb in payload.get("labels") or [])
    return DetectionResult(
        task=task,
        boxes=boxes,
        labels=labels,
        scores=scores,
        score=max(scores) if scores else 0.0,
    )


__all__ = [
    "API_KEY_ENV",
    "ApiInferError",
    "DEFAULT_TIMEOUT_S",
    "infer_remote",
    "resolve_api_key",
]

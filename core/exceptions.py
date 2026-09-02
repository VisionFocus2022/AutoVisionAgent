"""统一异常体系。

所有自定义业务异常的基类和具体实现，按模块分组。
"""
from __future__ import annotations


class AppError(Exception):
    """应用层所有自定义异常的基类。"""

    def __init__(self, message: str = "", *args: object) -> None:
        super().__init__(message, *args)
        self.message = message

    def __str__(self) -> str:
        return self.message or self.__class__.__name__


# ============================== 引擎异常 ============================== #

class SupervisedEngineError(AppError):
    """有监督引擎操作异常（加载/推理/训练）。"""

    def __init__(
        self, message: str = "", *, task: str = ""
    ) -> None:
        super().__init__(message)
        self.task = task

    @property
    def details(self) -> dict:
        """返回错误详情字典（兼容测试与日志格式化）。"""
        return {"task": self.task} if self.task else {}


class UnsupportedTaskError(SupervisedEngineError):
    """请求的任务类型尚未注册引擎。"""

    def __init__(self, task_value: str = "") -> None:
        super().__init__(
            f"不支持的任务类型: {task_value}" if task_value else "不支持的任务类型",
            task=task_value,
        )


class ApiInferError(AppError):
    """远端 API 推理失败（W59-A——endpoint 无效/超时/非 200/契约不符）。

    message 面向用户（含 endpoint 与状态码，供状态栏与日志定位）；
    endpoint 属性供调用方区分目标。
    """

    def __init__(self, message: str = "", *, endpoint: str = "") -> None:
        super().__init__(message)
        self.endpoint = endpoint

    @property
    def details(self) -> dict:
        return {"endpoint": self.endpoint} if self.endpoint else {}


# ============================== 导出异常 ============================== #

class ModelExportError(AppError):
    """模型导出（ONNX/TRT/量化）过程异常。"""

    def __init__(
        self,
        message: str = "",
        *args: object,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, *args)
        self._details: dict = details or {}

    @property
    def details(self) -> dict:
        """返回错误详情字典（兼容测试与日志格式化）。"""
        return dict(self._details) if self._details else {}


# ============================== 标注异常 ============================== #

class AnnotationIOError(AppError):
    """标注文件读写异常（JSON 解析 / 图片编码）。"""

    def __init__(
        self,
        message: str = "",
        *args: object,
        path: str = "",
    ) -> None:
        super().__init__(message, *args)
        self.path = path

    @property
    def details(self) -> dict:
        """返回错误详情字典。"""
        return {"path": self.path} if self.path else {}


class InvalidShapeError(AppError):
    """标注形状数据异常（坐标越界 / 类型错误）。"""

    def __init__(
        self,
        message: str = "",
        *args: object,
        mode: str = "",
    ) -> None:
        super().__init__(message, *args)
        self.mode = mode

    @property
    def details(self) -> dict:
        """返回错误详情字典。"""
        return {"mode": self.mode} if self.mode else {}


__all__ = [
    "AppError",
    "SupervisedEngineError",
    "UnsupportedTaskError",
    "ModelExportError",
    "AnnotationIOError",
    "InvalidShapeError",
]

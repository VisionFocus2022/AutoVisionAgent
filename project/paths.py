"""项目存储根目录单源解析（W28：替换两处内联硬编码）。

历史：默认根 ~/AutoVisionAgent_Projects 曾在 gui/pages/project/page.py
与 project/counter.py 各自内联 expanduser——设置页 workspace 键持久化
但零消费（对标审查"三死键"之一）。收敛后：
  resolve_base_root() = user_settings.workspace（非空时）
                      | core.constants.DEFAULT_PROJECT_ROOT

消费方：项目管理页 base_root / TaskCounter 默认根 / predict 批量落盘
回退 / 主页最近项目刷新。

分层说明：settings 读取属 gui.core.settings_io（纯 Python 无 Qt）；本模块
惰性导入并兜底一切异常——gui 层不可用时（裁剪环境）退默认根，不击穿。
"""
from __future__ import annotations

import os

from core.constants import DEFAULT_PROJECT_ROOT_TILDE


def resolve_base_root() -> str:
    """解析项目存储根目录（单一事实源）。

    默认根在调用期经 os.path.expanduser 展开（非导入期常量）——
    tests/test_gui_misc_pages.py 的 home_env 接缝依赖调用期重定向。
    """
    try:
        from gui.core.settings_io import load_user_settings

        workspace = load_user_settings().get("workspace")
        if isinstance(workspace, str) and workspace.strip():
            # 审计折入：与默认根对称地支持 ~/ 前缀（手改 JSON 场景；
            # 设置页浏览按钮恒给绝对路径，此处仅兜平语义不一致）
            return os.path.expanduser(workspace.strip())
    except Exception:  # noqa: BLE001——settings 层任何故障都退默认根
        import logging

        logging.getLogger(__name__).warning(
            "读取 workspace 设置失败，回退默认项目根", exc_info=True
        )
    return os.path.expanduser(DEFAULT_PROJECT_ROOT_TILDE)


__all__ = ["resolve_base_root"]

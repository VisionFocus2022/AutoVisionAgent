"""W68：冻结态用户数据持久化（RED→GREEN）。

回归背景：CONFIG_DIR 冻结态解析为 `_internal\\configs`（按源码位置回溯），
PyInstaller 重建清空整个 dist 目录 → users.json/审计/历史/设置全部销毁，
首启重新生成随机密码（用户报「每次重新生成软件登录密码就变」）。

方案（用户裁决 APPDATA 按用户）：冻结态 CONFIG_DIR →
`%APPDATA%/AutoVisionAgent/configs`；源码模式维持仓根 configs（开发现状
不变）；首启迁移 `_internal/configs` 旧用户态文件（当前密码无缝衔接）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ============================== ① 目录解析 ============================== #

@pytest.mark.unit
def test_resolve_config_dir_dev_unchanged(monkeypatch, tmp_path):
    """非冻结（源码开发/测试）→ 仓根 configs，现状不变。"""
    from core import constants

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert constants._resolve_config_dir() == constants._PROJECT_ROOT / "configs"


@pytest.mark.unit
def test_resolve_config_dir_frozen_appdata(monkeypatch, tmp_path):
    """冻结态 → %APPDATA%/AutoVisionAgent/configs（重建/重装不丢）。"""
    from core import constants

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    resolved = constants._resolve_config_dir()
    assert resolved == tmp_path / "AutoVisionAgent" / "configs"


@pytest.mark.unit
def test_resolve_config_dir_frozen_no_appdata_falls_home(monkeypatch, tmp_path):
    """APPDATA 环境变量缺失（异常壳环境）→ 回退 ~/AppData/Roaming。"""
    from core import constants

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    resolved = constants._resolve_config_dir()
    assert resolved == (
        tmp_path / "AppData" / "Roaming" / "AutoVisionAgent" / "configs"
    )


# ============================== ② 旧数据迁移 ============================== #

@pytest.mark.unit
def test_migrate_legacy_configs(monkeypatch, tmp_path):
    """冻结首启：_internal/configs 旧用户态文件迁移到持久目录。

    密码不丢的核心：旧 users.json（含用户已改密的哈希）复制过去；
    已存在的目标文件不覆盖（保护新目录里更新的数据）。
    """
    from core import constants

    meipass = tmp_path / "internal"
    legacy_cfg = meipass / "configs"
    legacy_cfg.mkdir(parents=True)
    (legacy_cfg / "users.json").write_text('{"admin": {}}', encoding="utf-8")
    (legacy_cfg / "license.key").write_text("LIC", encoding="utf-8")

    appdata = tmp_path / "roaming"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    migrated = constants.migrate_legacy_configs()
    assert set(migrated) == {"users.json", "license.key"}

    new_dir = appdata / "AutoVisionAgent" / "configs"
    assert (new_dir / "users.json").read_text(encoding="utf-8") == '{"admin": {}}'
    assert (new_dir / "license.key").read_text(encoding="utf-8") == "LIC"

    # 幂等：目标已存在不覆盖（改一个值再迁移，值应保持）
    (new_dir / "users.json").write_text('{"changed": true}', encoding="utf-8")
    migrated2 = constants.migrate_legacy_configs()
    assert migrated2 == []
    assert (new_dir / "users.json").read_text(encoding="utf-8") == '{"changed": true}'


@pytest.mark.unit
def test_migrate_legacy_configs_dev_noop(monkeypatch, tmp_path):
    """源码模式迁移为零操作（开发仓不受影响）。"""
    from core import constants

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert constants.migrate_legacy_configs() == []

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from faceforge_core.config import CoreConfig, load_core_config, resolve_configured_paths
from faceforge_core.home import ensure_faceforge_layout


def test_load_core_config_defaults_when_missing(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)
    cfg = load_core_config(paths)
    assert isinstance(cfg, CoreConfig)
    assert cfg.network.bind_host == "127.0.0.1"


def test_load_core_config_validation_error(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)

    paths.core_config_path.write_text(
        json.dumps({"network": {"core_port": "not-an-int"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_core_config(paths)


def test_resolve_configured_paths_creates_overrides(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)

    cfg = CoreConfig.model_validate(
        {
            "paths": {
                "db_dir": "custom_db",
                "logs_dir": "custom_logs",
            }
        }
    )

    resolved = resolve_configured_paths(paths, cfg)
    assert resolved.db_dir.is_dir()
    assert resolved.logs_dir.is_dir()

    # Overrides are resolved relative to FACEFORGE_HOME by default.
    assert resolved.db_dir == (tmp_path / "custom_db").resolve()
    assert resolved.logs_dir == (tmp_path / "custom_logs").resolve()

    # Non-configurable dirs remain under home.
    assert resolved.config_dir == (tmp_path / "config").resolve()

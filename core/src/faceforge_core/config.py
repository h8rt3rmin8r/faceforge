from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from faceforge_core.home import FaceForgePaths


class NetworkConfig(BaseModel):
    bind_host: str = Field(default="127.0.0.1")
    core_port: int = Field(default=8787, ge=1, le=65535)
    seaweed_s3_port: int | None = Field(default=None, ge=1, le=65535)


class PathOverrides(BaseModel):
    db_dir: str | None = None
    s3_dir: str | None = None
    logs_dir: str | None = None
    plugins_dir: str | None = None


class AuthConfig(BaseModel):
    install_token: str | None = Field(default=None)


class ToolsConfig(BaseModel):
    exiftool_enabled: bool = Field(default=True)
    exiftool_path: str | None = Field(
        default=None,
        description="Optional path to the exiftool binary (used for ingest metadata extraction)",
    )


class CoreConfig(BaseModel):
    version: str = Field(default="1")
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    paths: PathOverrides = Field(default_factory=PathOverrides)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_core_config(paths: FaceForgePaths) -> CoreConfig:
    """Load config from ${FACEFORGE_HOME}/config/core.json.

    - If missing: returns defaults.
    - Validation is performed by Pydantic.
    """

    config_path = paths.core_config_path
    if not config_path.exists():
        return CoreConfig()

    raw = _read_json(config_path)
    return CoreConfig.model_validate(raw)


def write_core_config(paths: FaceForgePaths, config: CoreConfig) -> None:
    """Persist config to ${FACEFORGE_HOME}/config/core.json."""

    payload = config.model_dump(mode="json", exclude_none=True)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.core_config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ensure_install_token(paths: FaceForgePaths, config: CoreConfig) -> CoreConfig:
    """Ensure a per-install auth token exists and is stored in config.

    If missing, generate a new token and persist it to core.json.
    """

    raw = (config.auth.install_token or "").strip()
    if raw:
        return config

    token = secrets.token_urlsafe(32)
    updated_auth = config.auth.model_copy(update={"install_token": token})
    updated = config.model_copy(update={"auth": updated_auth})
    write_core_config(paths, updated)
    return updated


def resolve_configured_paths(paths: FaceForgePaths, config: CoreConfig) -> FaceForgePaths:
    """Apply user-configurable path overrides from config.

    Note: per spec, run/ and config/ are not configurable.
    """

    def _resolve_dir(raw: str | None, default: Path) -> Path:
        if raw is None or not str(raw).strip():
            return default
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (paths.home / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    db_dir = _resolve_dir(config.paths.db_dir, paths.db_dir)
    s3_dir = _resolve_dir(config.paths.s3_dir, paths.s3_dir)
    logs_dir = _resolve_dir(config.paths.logs_dir, paths.logs_dir)
    plugins_dir = _resolve_dir(config.paths.plugins_dir, paths.plugins_dir)

    # Ensure overridden dirs exist so file edits are enough.
    for p in (db_dir, s3_dir, logs_dir, plugins_dir):
        p.mkdir(parents=True, exist_ok=True)

    return FaceForgePaths(
        home=paths.home,
        db_dir=db_dir,
        s3_dir=s3_dir,
        assets_dir=paths.assets_dir,
        logs_dir=logs_dir,
        run_dir=paths.run_dir,
        config_dir=paths.config_dir,
        tools_dir=paths.tools_dir,
        plugins_dir=plugins_dir,
    )

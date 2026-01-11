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


class SeaweedManagedConfig(BaseModel):
    """Optional Core-managed SeaweedFS process settings.

    Desktop will ultimately orchestrate this, but Core can optionally run it for dev/testing
    as long as the binary is available under FACEFORGE_HOME/tools.
    """

    enabled: bool = Field(default=False)
    weed_path: str | None = Field(
        default=None,
        description=(
            "Optional path to the SeaweedFS 'weed' binary; if relative, resolved under "
            "FACEFORGE_HOME/tools"
        ),
    )
    data_dir: str | None = Field(
        default=None,
        description="Optional data dir for SeaweedFS; if relative, resolved under FACEFORGE_HOME",
    )
    ip: str = Field(default="127.0.0.1")
    master_port: int = Field(default=9333, ge=1, le=65535)
    volume_port: int = Field(default=8080, ge=1, le=65535)
    filer_port: int = Field(default=8888, ge=1, le=65535)
    s3_port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="If omitted, Core uses network.seaweed_s3_port when available, else 8333.",
    )


class S3StorageConfig(BaseModel):
    """S3-compatible storage settings (intended: SeaweedFS S3 endpoint)."""

    enabled: bool = Field(default=False)
    endpoint_url: str | None = Field(
        default=None,
        description=(
            "S3 endpoint URL, e.g. http://127.0.0.1:8333 (SeaweedFS s3). If omitted, "
            "derived from bind_host + seaweed_s3_port."
        ),
    )
    access_key: str | None = Field(default=None)
    secret_key: str | None = Field(default=None)
    bucket: str = Field(default="faceforge")
    region: str = Field(default="us-east-1")
    use_ssl: bool = Field(default=False)


class StorageRoutingConfig(BaseModel):
    """Rules for choosing a storage provider at upload time."""

    default_provider: str = Field(default="fs", description="'fs' or 's3'")
    kind_map: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional mapping of asset kind -> provider name (e.g. {'thumb': 'fs', 'file': 's3'})."
        ),
    )
    s3_min_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description=(
            "If set, assets with byte_size >= threshold are routed to S3 unless kind_map overrides."
        ),
    )


class StorageConfig(BaseModel):
    routing: StorageRoutingConfig = Field(default_factory=StorageRoutingConfig)
    s3: S3StorageConfig = Field(default_factory=S3StorageConfig)


class PathOverrides(BaseModel):
    db_dir: str | None = None
    s3_dir: str | None = None
    logs_dir: str | None = None
    plugins_dir: str | None = None


class AuthConfig(BaseModel):
    install_token: str | None = Field(default=None)


class LoggingConfig(BaseModel):
    max_size_mb: int = Field(
        default=10, ge=1, description="Max size of a log file in MB before rolling."
    )
    backup_count: int = Field(default=5, ge=1, description="Number of log archives to keep.")


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
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    seaweed: SeaweedManagedConfig = Field(default_factory=SeaweedManagedConfig)


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
        config_dir=paths.config_dir,
        plugins_dir=plugins_dir,
        tmp_dir=paths.tmp_dir,
    )

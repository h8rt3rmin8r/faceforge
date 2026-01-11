from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FaceForgePaths:
    home: Path
    db_dir: Path
    s3_dir: Path
    assets_dir: Path
    logs_dir: Path
    config_dir: Path
    plugins_dir: Path
    tmp_dir: Path

    @property
    def core_config_path(self) -> Path:
        return self.config_dir / "core.json"

    @property
    def ports_path(self) -> Path:
        return self.config_dir / "ports.json"


def resolve_faceforge_home(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ

    raw = (env.get("FACEFORGE_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()

    # Safe default for dev/scaffold: local folder under the current working directory.
    # Desktop can (and likely will) set FACEFORGE_HOME explicitly.
    return (Path.cwd() / ".faceforge").resolve()


def ensure_faceforge_layout(home: Path) -> FaceForgePaths:
    home.mkdir(parents=True, exist_ok=True)

    db_dir = home / "db"
    s3_dir = home / "s3"
    assets_dir = home / "assets"
    logs_dir = home / "logs"
    config_dir = home / "config"
    plugins_dir = home / "plugins"
    tmp_dir = home / "tmp"

    for path in (db_dir, s3_dir, assets_dir, logs_dir, config_dir, plugins_dir, tmp_dir):
        path.mkdir(parents=True, exist_ok=True)

    return FaceForgePaths(
        home=home,
        db_dir=db_dir,
        s3_dir=s3_dir,
        assets_dir=assets_dir,
        logs_dir=logs_dir,
        config_dir=config_dir,
        plugins_dir=plugins_dir,
        tmp_dir=tmp_dir,
    )

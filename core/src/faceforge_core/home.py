from __future__ import annotations

import os
import sys
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
    tools_dir: Path
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
        candidate = Path(raw).expanduser()
        # Never interpret FACEFORGE_HOME relative to CWD (e.g. Downloads when launched from an MSI).
        if not candidate.is_absolute():
            candidate = (Path.home() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def default_home() -> Path:
        # Deterministic per-user default: never depends on current working directory.
        if sys.platform.startswith("win"):
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if base:
                return Path(base) / "FaceForge"
            return Path.home() / "AppData" / "Local" / "FaceForge"

        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "FaceForge"

        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            return Path(xdg) / "faceforge"
        return Path.home() / ".local" / "share" / "faceforge"

    return default_home().resolve()


def ensure_faceforge_layout(home: Path) -> FaceForgePaths:
    home.mkdir(parents=True, exist_ok=True)

    db_dir = home / "db"
    s3_dir = home / "s3"
    assets_dir = home / "assets"
    logs_dir = home / "logs"
    config_dir = home / "config"
    tools_dir = home / "tools"
    plugins_dir = home / "plugins"
    tmp_dir = home / "tmp"

    for path in (
        db_dir,
        s3_dir,
        assets_dir,
        logs_dir,
        config_dir,
        tools_dir,
        plugins_dir,
        tmp_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    return FaceForgePaths(
        home=home,
        db_dir=db_dir,
        s3_dir=s3_dir,
        assets_dir=assets_dir,
        logs_dir=logs_dir,
        config_dir=config_dir,
        tools_dir=tools_dir,
        plugins_dir=plugins_dir,
        tmp_dir=tmp_dir,
    )

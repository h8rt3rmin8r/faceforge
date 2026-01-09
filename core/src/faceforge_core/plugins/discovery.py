from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PluginManifest(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str | None = None

    core_compat: str | None = None
    capabilities: list[str] = Field(default_factory=list)

    config_schema: dict[str, Any] | None = None
    permissions: list[str] = Field(default_factory=list)

    routes_prefix: str | None = None
    job_types: list[str] = Field(default_factory=list)

    entrypoints: dict[str, Any] | None = None


@dataclass(frozen=True)
class DiscoveredPlugin:
    manifest: PluginManifest
    manifest_path: Path
    plugin_dir: Path


def _safe_load_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


def discover_plugins(*, plugins_dir: Path) -> list[DiscoveredPlugin]:
    if not plugins_dir.exists():
        return []

    out: list[DiscoveredPlugin] = []

    for plugin_json in plugins_dir.glob("*/plugin.json"):
        try:
            data = _safe_load_json(plugin_json)
            manifest = PluginManifest.model_validate(data)
            out.append(
                DiscoveredPlugin(
                    manifest=manifest,
                    manifest_path=plugin_json,
                    plugin_dir=plugin_json.parent,
                )
            )
        except Exception:
            # Discovery is best-effort; invalid manifests are ignored.
            continue

    out.sort(key=lambda p: p.manifest.id.casefold())
    return out

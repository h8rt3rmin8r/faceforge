from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from faceforge_core.home import FaceForgePaths


@dataclass(frozen=True)
class RuntimePorts:
    core_port: int | None = None
    seaweed_s3_port: int | None = None


def _parse_ports(data: dict[str, Any]) -> RuntimePorts:
    core = data.get("core")
    seaweed = data.get("seaweed_s3")
    return RuntimePorts(
        core_port=int(core) if core is not None else None,
        seaweed_s3_port=int(seaweed) if seaweed is not None else None,
    )


def read_ports_file(
    paths: FaceForgePaths, *, allow_legacy_runtime_dir: bool = False
) -> RuntimePorts | None:
    """Read ${FACEFORGE_HOME}/config/ports.json."""

    ports_path = paths.ports_path
    if not ports_path.exists() and allow_legacy_runtime_dir:
        legacy = paths.home / "runtime" / "ports.json"
        if legacy.exists():
            ports_path = legacy

    if not ports_path.exists():
        return None

    with ports_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid ports.json format at {ports_path}")

    return _parse_ports(data)


def write_ports_file(paths: FaceForgePaths, ports: RuntimePorts) -> None:
    paths.ports_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "core": ports.core_port,
        "seaweed_s3": ports.seaweed_s3_port,
    }
    with paths.ports_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")

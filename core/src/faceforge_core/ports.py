from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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
    """Read ${FACEFORGE_HOME}/run/ports.json.

    If allow_legacy_runtime_dir=True, also checks ${FACEFORGE_HOME}/runtime/ports.json
    (the v0.2.9 spec mentions /runtime/; Sprint 1 uses /run/).
    """

    candidates: list[Path] = [paths.ports_path]
    if allow_legacy_runtime_dir:
        candidates.append(paths.home / "runtime" / "ports.json")

    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid ports.json format at {path}")
        return _parse_ports(data)

    return None


def write_ports_file(paths: FaceForgePaths, ports: RuntimePorts) -> None:
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "core": ports.core_port,
        "seaweed_s3": ports.seaweed_s3_port,
    }
    with paths.ports_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")

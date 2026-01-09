from __future__ import annotations

import json
from pathlib import Path

from faceforge_core.home import ensure_faceforge_layout
from faceforge_core.ports import RuntimePorts, read_ports_file, write_ports_file


def test_write_and_read_ports_file_round_trip(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)

    write_ports_file(paths, RuntimePorts(core_port=12345, seaweed_s3_port=23456))
    loaded = read_ports_file(paths)

    assert loaded is not None
    assert loaded.core_port == 12345
    assert loaded.seaweed_s3_port == 23456


def test_read_ports_file_legacy_runtime_dir(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)

    legacy_dir = tmp_path / "runtime"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "ports.json").write_text(
        json.dumps({"core": 11111, "seaweed_s3": 22222}),
        encoding="utf-8",
    )

    loaded = read_ports_file(paths, allow_legacy_runtime_dir=True)
    assert loaded is not None
    assert loaded.core_port == 11111
    assert loaded.seaweed_s3_port == 22222

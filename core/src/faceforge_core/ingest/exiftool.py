from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

EXIFTOOL_SKIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"_(meta|directorymeta)\.json$", re.IGNORECASE),
    re.compile(r"\.(cover|thumb|thumb(s|db|index|nail))$", re.IGNORECASE),
    re.compile(r"^(thumb|thumb(s|db|index|nail))\.db$", re.IGNORECASE),
    re.compile(r"\.(csv|html?|json|tsv|xml)$", re.IGNORECASE),
)

EXIFTOOL_ARGSFILE_LINE = (
    "-quiet -extractEmbedded3 -scanForXMP -unknown2 -json -G3:1 -struct -b "
    "-ignoreMinorErrors -charset filename=utf8 -api requestall=3 -api largefilesupport=1 --"
)

EXIFTOOL_REMOVE_KEYS: set[str] = {
    "ExifTool:ExifToolVersion",
    "ExifTool:FileSequence",
    "ExifTool:NewGUID",
    "System:BaseName",
    "System:Directory",
    "System:FileBlockCount",
    "System:FileBlockSize",
    "System:FileDeviceID",
    "System:FileDeviceNumber",
    "System:FileGroupID",
    "System:FileHardLinks",
    "System:FileInodeNumber",
    "System:FileName",
    "System:FilePath",
    "System:FilePermissions",
    "System:FileUserID",
}


def should_skip_exiftool(filename: str) -> bool:
    name = (filename or "").strip()
    if not name:
        return True
    return any(p.search(name) is not None for p in EXIFTOOL_SKIP_PATTERNS)


def _filter_exiftool_payload(payload: Any) -> Any:
    """Remove volatile/host-specific keys before storing."""

    if isinstance(payload, list):
        return [_filter_exiftool_payload(x) for x in payload]

    if isinstance(payload, dict):
        return {
            k: _filter_exiftool_payload(v)
            for k, v in payload.items()
            if k not in EXIFTOOL_REMOVE_KEYS
        }

    return payload


def build_exiftool_entry(exiftool_output: Any) -> dict[str, Any]:
    if exiftool_output in (None, ""):
        raise ValueError("exiftool output is empty")

    return {
        "Source": "ExifTool",
        "Type": "JsonMetadata",
        "Name": None,
        "NameHashes": None,
        "Data": exiftool_output,
    }


def run_exiftool(*, exiftool_path: Path, asset_path: Path) -> dict[str, Any]:
    """Run exiftool using a parameter file as required by spec.

    Returns the wrapped JsonMetadata entry ready to store.
    """

    if not exiftool_path.exists():
        raise FileNotFoundError(str(exiftool_path))
    if not asset_path.exists():
        raise FileNotFoundError(str(asset_path))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".args", delete=False, encoding="utf-8") as f:
        args_file = Path(f.name)
        f.write(EXIFTOOL_ARGSFILE_LINE)
        f.write("\n")

    try:
        proc = subprocess.run(
            [str(exiftool_path), "-@", str(args_file), str(asset_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )

        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"exiftool exited with code {proc.returncode}")
        if not out:
            raise RuntimeError("exiftool produced empty output")

        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError("exiftool output was not valid JSON") from e

        filtered = _filter_exiftool_payload(parsed)

        # Validate non-empty after filtering.
        if filtered in (None, ""):
            raise RuntimeError("exiftool JSON became empty after filtering")
        if isinstance(filtered, list) and len(filtered) == 0:
            raise RuntimeError("exiftool JSON list was empty")
        if isinstance(filtered, dict) and len(filtered) == 0:
            raise RuntimeError("exiftool JSON object was empty")

        entry = build_exiftool_entry(filtered)
        return entry
    finally:
        try:
            args_file.unlink(missing_ok=True)
        except OSError:
            pass

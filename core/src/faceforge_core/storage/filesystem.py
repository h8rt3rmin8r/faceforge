from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageLocation:
    provider: str
    key: str


class FilesystemStorageProvider:
    """Local filesystem asset storage.

    Layout is stable and content-addressed by SHA-256 hex (asset_id).

    Base dir: ${FACEFORGE_HOME}/assets
    File path: files/<aa>/<sha256>
    """

    provider_name = "fs"

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def ensure_layout(self) -> None:
        (self._base_dir / "files").mkdir(parents=True, exist_ok=True)

    def key_for_asset_id(self, asset_id: str) -> str:
        asset_id = asset_id.strip().lower()
        shard = asset_id[:2] if len(asset_id) >= 2 else "xx"
        return str(Path("files") / shard / asset_id)

    def resolve_path(self, storage_key: str) -> Path:
        return (self._base_dir / storage_key).resolve()

    def exists(self, storage_key: str) -> bool:
        return self.resolve_path(storage_key).exists()

    def finalize_temp_file(self, *, temp_path: Path, storage_key: str) -> Path:
        """Move temp file into its final storage path.

        If the destination already exists, the temp file is removed.
        Returns the destination path.
        """

        dst = self.resolve_path(storage_key)
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return dst

        # Best-effort atomic move.
        try:
            temp_path.replace(dst)
        except OSError:
            # Cross-device moves are unlikely here, but fall back to copy+remove.
            with temp_path.open("rb") as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

        # Ensure content is readable by the current user.
        try:
            os.chmod(dst, 0o644)
        except OSError:
            pass

        return dst


    def ingest_existing_file(self, *, source_path: Path, storage_key: str) -> Path:
        """Copy (or hardlink when possible) an existing file into storage.

        The source file is left in place.
        """

        dst = self.resolve_path(storage_key)
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            return dst

        # Best effort hardlink for speed; fall back to copy.
        try:
            os.link(source_path, dst)
            return dst
        except OSError:
            pass

        with source_path.open("rb") as src, dst.open("wb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)

        try:
            os.chmod(dst, 0o644)
        except OSError:
            pass

        return dst

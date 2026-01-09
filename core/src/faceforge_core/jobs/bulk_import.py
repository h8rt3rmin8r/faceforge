from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import sqlite3

from faceforge_core.db.assets import (
    append_asset_metadata_entry,
    create_asset,
    get_asset_by_content_hash,
)
from faceforge_core.db.ids import asset_id_from_content_hash, sha256_hex_file
from faceforge_core.db.jobs import (
    append_job_log,
    get_job,
    mark_job_canceled,
    update_job_progress,
)
from faceforge_core.storage.manager import StorageManager


def _guess_mime_type(filename: str | None) -> str | None:
    if not filename:
        return None
    guess, _enc = mimetypes.guess_type(filename)
    return guess


def _read_sidecar_json(sidecar_path: Path) -> Any:
    raw = sidecar_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("_meta.json must be UTF-8") from e

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("_meta.json must be valid JSON") from e

    if parsed in (None, ""):
        raise ValueError("_meta.json must be non-empty")

    return parsed


def _sidecar_candidates(file_path: Path) -> list[Path]:
    name = file_path.name
    stem = file_path.stem
    return [
        file_path.with_name(f"{name}_meta.json"),
        file_path.with_name(f"{name}._meta.json"),
        file_path.with_name(f"{stem}_meta.json"),
        file_path.with_name(f"{stem}._meta.json"),
    ]


def _is_meta_file(path: Path) -> bool:
    n = path.name.lower()
    return n == "_meta.json" or n.endswith("_meta.json") or n.endswith("._meta.json")


def run_assets_bulk_import(ctx, job_id: str, job_input: dict[str, Any]) -> dict[str, Any]:
    db_path = ctx.db_path
    storage_mgr: StorageManager = ctx.storage_mgr

    src_dir = Path(str(job_input.get("path") or "")).expanduser()
    recursive = bool(job_input.get("recursive", True))
    kind = str(job_input.get("kind") or "file")
    throttle_ms = int(job_input.get("throttle_ms") or 0)

    if not src_dir.exists() or not src_dir.is_dir():
        raise ValueError("path must be an existing directory")

    def cancel_requested() -> bool:
        j = get_job(db_path, job_id=job_id, include_deleted=False)
        return j is not None and j.cancel_requested_at is not None

    # Build deterministic file list.
    files: list[Path] = []
    if recursive:
        for p in src_dir.rglob("*"):
            if p.is_file() and not _is_meta_file(p):
                files.append(p)
    else:
        for p in src_dir.iterdir():
            if p.is_file() and not _is_meta_file(p):
                files.append(p)

    files.sort(key=lambda p: str(p).lower())

    append_job_log(
        db_path,
        job_id=job_id,
        level="info",
        message="Bulk import discovered files",
        data={"path": str(src_dir), "files": len(files), "recursive": recursive},
    )

    total = len(files)
    imported = 0
    skipped_existing = 0
    errors = 0

    if total == 0:
        update_job_progress(db_path, job_id=job_id, progress_percent=100.0, progress_step="no files")
        return {
            "path": str(src_dir),
            "imported": 0,
            "skipped_existing": 0,
            "errors": 0,
        }

    for idx, file_path in enumerate(files, start=1):
        if cancel_requested():
            append_job_log(db_path, job_id=job_id, level="info", message="Bulk import canceled")
            mark_job_canceled(
                db_path,
                job_id=job_id,
                result={
                    "path": str(src_dir),
                    "imported": imported,
                    "skipped_existing": skipped_existing,
                    "errors": errors,
                    "canceled": True,
                },
            )
            return {
                "path": str(src_dir),
                "imported": imported,
                "skipped_existing": skipped_existing,
                "errors": errors,
                "canceled": True,
            }

        pct = (idx - 1) / total * 100.0
        update_job_progress(
            db_path,
            job_id=job_id,
            progress_percent=pct,
            progress_step=f"importing {file_path.name}",
        )

        sidecar_data: Any | None = None
        sidecar_name: str | None = None
        for cand in _sidecar_candidates(file_path):
            if cand.exists() and cand.is_file():
                try:
                    sidecar_data = _read_sidecar_json(cand)
                    sidecar_name = cand.name
                except Exception as e:
                    append_job_log(
                        db_path,
                        job_id=job_id,
                        level="warning",
                        message="Sidecar JSON skipped",
                        data={"file": str(file_path), "sidecar": str(cand), "error": str(e)},
                    )
                break

        try:
            byte_size = int(file_path.stat().st_size)
            if byte_size <= 0:
                append_job_log(
                    db_path,
                    job_id=job_id,
                    level="warning",
                    message="Skipped empty file",
                    data={"file": str(file_path)},
                )
                continue

            content_hash = sha256_hex_file(file_path)
            asset_id = asset_id_from_content_hash(content_hash)

            existing = get_asset_by_content_hash(db_path, content_hash=content_hash, include_deleted=False)
            if existing is not None:
                skipped_existing += 1
                if sidecar_data is not None:
                    entry = {
                        "Source": "UserSidecar",
                        "Type": "JsonMetadata",
                        "Name": sidecar_name or "_meta.json",
                        "NameHashes": None,
                        "Data": sidecar_data,
                    }
                    append_asset_metadata_entry(db_path, asset_id=existing.asset_id, entry=entry)
                append_job_log(
                    db_path,
                    job_id=job_id,
                    level="info",
                    message="Skipped (already imported)",
                    data={"file": str(file_path), "asset_id": existing.asset_id},
                )
                continue

            upload_result = storage_mgr.store_existing_file(
                source_path=file_path,
                asset_id=asset_id,
                kind=kind,
                byte_size=byte_size,
            )

            meta_obj: dict[str, Any] = {"metadata": []}
            if sidecar_data is not None:
                meta_obj["metadata"].append(
                    {
                        "Source": "UserSidecar",
                        "Type": "JsonMetadata",
                        "Name": sidecar_name or "_meta.json",
                        "NameHashes": None,
                        "Data": sidecar_data,
                    }
                )

            mime_type = _guess_mime_type(file_path.name)

            created = False
            try:
                create_asset(
                    db_path,
                    asset_id=asset_id,
                    kind=kind,
                    filename=file_path.name,
                    content_hash=content_hash,
                    byte_size=byte_size,
                    mime_type=mime_type,
                    storage_provider=upload_result.storage_provider,
                    storage_key=upload_result.storage_key,
                    meta=meta_obj,
                )
                created = True
            except sqlite3.IntegrityError:
                # Lost a race; treat as already imported.
                skipped_existing += 1

            if created:
                imported += 1
                append_job_log(
                    db_path,
                    job_id=job_id,
                    level="info",
                    message="Imported",
                    data={"file": str(file_path), "asset_id": asset_id, "bytes": byte_size},
                )

        except Exception as e:
            errors += 1
            append_job_log(
                db_path,
                job_id=job_id,
                level="error",
                message="Import failed",
                data={"file": str(file_path), "error": str(e)},
            )

        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    update_job_progress(db_path, job_id=job_id, progress_percent=100.0, progress_step="done")
    return {
        "path": str(src_dir),
        "imported": imported,
        "skipped_existing": skipped_existing,
        "errors": errors,
    }

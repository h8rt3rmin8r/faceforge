from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, ok
from faceforge_core.db.assets import (
    AssetRow,
    append_asset_metadata_entry,
    create_asset,
    get_asset,
    get_asset_by_content_hash,
)
from faceforge_core.db.ids import asset_id_from_content_hash
from faceforge_core.ingest.exiftool import run_exiftool, should_skip_exiftool
from faceforge_core.storage.filesystem import FilesystemStorageProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assets"])


UPLOAD_FILE = File(...)
UPLOAD_META_FILE = File(
    default=None,
    description="Optional companion sidecar JSON (typically named _meta.json)",
)


class Asset(BaseModel):
    asset_id: str
    kind: str
    filename: str | None
    content_hash: str
    byte_size: int
    mime_type: str | None
    storage_provider: str
    storage_key: str
    meta: Any = Field(default_factory=dict)
    created_at: str
    updated_at: str


def _to_asset(row: AssetRow) -> Asset:
    return Asset(
        asset_id=row.asset_id,
        kind=row.kind,
        filename=row.filename,
        content_hash=row.content_hash,
        byte_size=row.byte_size,
        mime_type=row.mime_type,
        storage_provider=row.storage_provider,
        storage_key=row.storage_key,
        meta=row.meta,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _parse_range_header(range_header: str, *, size: int) -> tuple[int, int] | None:
    raw = (range_header or "").strip()
    if not raw:
        return None

    if not raw.lower().startswith("bytes="):
        return None

    spec = raw[6:].strip()

    # Only support a single range for now.
    if "," in spec:
        return None

    if "-" not in spec:
        return None

    start_s, end_s = spec.split("-", 1)
    start_s = start_s.strip()
    end_s = end_s.strip()

    if start_s == "":
        # suffix: last N bytes
        try:
            suffix = int(end_s)
        except ValueError:
            return None
        if suffix <= 0:
            return None
        if suffix >= size:
            return (0, size - 1)
        return (size - suffix, size - 1)

    try:
        start = int(start_s)
    except ValueError:
        return None

    if start < 0 or start >= size:
        return None

    if end_s == "":
        return (start, size - 1)

    try:
        end = int(end_s)
    except ValueError:
        return None

    if end < start:
        return None

    end = min(end, size - 1)
    return (start, end)


def _iter_file_range(path: Path, *, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _guess_mime_type(filename: str | None, fallback: str | None) -> str:
    if fallback:
        return fallback
    if filename:
        guess, _enc = mimetypes.guess_type(filename)
        if guess:
            return guess
    return "application/octet-stream"


def _load_sidecar_json(upload: UploadFile) -> Any:
    raw = upload.file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=422, detail="_meta.json must be UTF-8") from e

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail="_meta.json must be valid JSON") from e

    if parsed in (None, ""):
        raise HTTPException(status_code=422, detail="_meta.json must be non-empty")

    return parsed


def _resolve_exiftool_executable(request: Request) -> Path | None:
    config = getattr(request.app.state, "faceforge_config", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    enabled = bool(getattr(getattr(config, "tools", None), "exiftool_enabled", True))
    if not enabled:
        return None

    tools_dir = getattr(paths, "tools_dir", None)
    if tools_dir is None:
        return None

    tools_dir = Path(tools_dir)

    raw = getattr(getattr(config, "tools", None), "exiftool_path", None)
    if raw and str(raw).strip():
        p = Path(str(raw)).expanduser()
        # Relative paths are resolved relative to the managed tools dir.
        p = p if p.is_absolute() else (tools_dir / p)
        p = p.resolve()
        return p if p.exists() else None

    # Bundled locations only (no PATH fallback).
    is_windows = os.name == "nt"
    candidates: list[Path] = []
    if is_windows:
        candidates.extend(
            [
                tools_dir / "exiftool.exe",
                tools_dir / "exiftool" / "exiftool.exe",
            ]
        )
    else:
        candidates.extend(
            [
                tools_dir / "exiftool",
                tools_dir / "exiftool" / "exiftool",
            ]
        )

    for c in candidates:
        if c.exists():
            return c

    return None


def _exiftool_background_task(
    *,
    db_path: Path,
    exiftool_path: Path,
    asset_id: str,
    asset_path: Path,
) -> None:
    try:
        entry = run_exiftool(exiftool_path=exiftool_path, asset_path=asset_path)
        updated = append_asset_metadata_entry(db_path, asset_id=asset_id, entry=entry)
        if updated is None:
            logger.warning(
                "ExifTool metadata extracted but asset not found",
                extra={"asset_id": asset_id},
            )
    except Exception as e:
        logger.info(
            "ExifTool metadata extraction failed",
            extra={"asset_id": asset_id, "error": str(e)},
        )


@router.post("/assets/upload", response_model=ApiResponse[Asset])
async def assets_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = UPLOAD_FILE,
    meta: UploadFile | None = UPLOAD_META_FILE,
) -> ApiResponse[Asset]:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    storage = FilesystemStorageProvider(paths.assets_dir)
    storage.ensure_layout()

    if not file.filename:
        raise HTTPException(status_code=422, detail="Missing filename")

    temp_path = (paths.run_dir / f"upload-{uuid.uuid4().hex}.tmp").resolve()

    h = hashlib.sha256()
    byte_size = 0

    try:
        with temp_path.open("wb") as out:
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                byte_size += len(chunk)
    finally:
        try:
            await file.close()
        except Exception:
            pass

    if byte_size <= 0:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="Uploaded file was empty")

    content_hash = h.hexdigest()
    asset_id = asset_id_from_content_hash(content_hash)
    storage_key = storage.key_for_asset_id(asset_id)

    # Finalize bytes to storage location.
    asset_path = storage.finalize_temp_file(temp_path=temp_path, storage_key=storage_key)

    mime_type = file.content_type
    if mime_type is not None and mime_type.strip() == "":
        mime_type = None

    meta_obj: dict[str, Any] = {"metadata": []}
    if meta is not None:
        sidecar = _load_sidecar_json(meta)
        meta_obj["metadata"].append(
            {
                "Source": "UserSidecar",
                "Type": "JsonMetadata",
                "Name": meta.filename or "_meta.json",
                "NameHashes": None,
                "Data": sidecar,
            }
        )

    # Insert record (dedupe via UNIQUE(content_hash)).
    try:
        row = create_asset(
            db_path,
            asset_id=asset_id,
            kind="file",
            filename=file.filename,
            content_hash=content_hash,
            byte_size=byte_size,
            mime_type=mime_type,
            storage_provider=storage.provider_name,
            storage_key=storage_key,
            meta=meta_obj,
        )
    except sqlite3.IntegrityError as e:
        existing = get_asset_by_content_hash(
            db_path,
            content_hash=content_hash,
            include_deleted=False,
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="Asset already exists") from e
        row = existing

    # Best-effort exiftool extraction.
    exiftool_path = _resolve_exiftool_executable(request)
    if exiftool_path is not None and not should_skip_exiftool(file.filename):
        background_tasks.add_task(
            _exiftool_background_task,
            db_path=Path(db_path),
            exiftool_path=exiftool_path,
            asset_id=row.asset_id,
            asset_path=asset_path,
        )

    return ok(_to_asset(row))


@router.get("/assets/{asset_id}", response_model=ApiResponse[Asset])
async def assets_get(request: Request, asset_id: str) -> ApiResponse[Asset]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    row = get_asset(db_path, asset_id=asset_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    return ok(_to_asset(row))


@router.get("/assets/{asset_id}/download")
async def assets_download(request: Request, asset_id: str):
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    row = get_asset(db_path, asset_id=asset_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    if row.storage_provider != "fs":
        raise HTTPException(status_code=501, detail="Unsupported storage provider")

    storage = FilesystemStorageProvider(paths.assets_dir)
    asset_path = storage.resolve_path(row.storage_key)
    if not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset bytes not found")

    size = asset_path.stat().st_size
    mime = _guess_mime_type(row.filename, row.mime_type)

    range_header = request.headers.get("range")
    range_tuple = _parse_range_header(range_header or "", size=size) if range_header else None

    headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
    }

    filename = row.filename or row.asset_id
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    if range_header and range_tuple is None:
        # Invalid/unsupported range.
        headers["Content-Range"] = f"bytes */{size}"
        return Response(status_code=416, headers=headers)

    if range_tuple is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            _iter_file_range(asset_path, start=0, end=size - 1),
            media_type=mime,
            headers=headers,
        )

    start, end = range_tuple
    content_length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(content_length)

    return StreamingResponse(
        _iter_file_range(asset_path, start=start, end=end),
        status_code=206,
        media_type=mime,
        headers=headers,
    )

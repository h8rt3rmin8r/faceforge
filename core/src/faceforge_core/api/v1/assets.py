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
from faceforge_core.db.ids import asset_id_from_content_hash, new_job_id
from faceforge_core.ingest.exiftool import run_exiftool, should_skip_exiftool
from faceforge_core.jobs.dispatcher import JobContext, start_job_thread
from faceforge_core.storage.manager import StorageManager
from faceforge_core.storage.s3 import S3ObjectLocation

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


def _unlink_best_effort(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
    cleanup_path: Path | None = None,
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
    finally:
        if cleanup_path is not None:
            _unlink_best_effort(cleanup_path)


def _cleanup_temp_file(path: Path) -> None:
    _unlink_best_effort(path)


@router.post("/assets/upload", response_model=ApiResponse[Asset])
async def assets_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    kind: str = "file",
    file: UploadFile = UPLOAD_FILE,
    meta: UploadFile | None = UPLOAD_META_FILE,
) -> ApiResponse[Asset]:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    storage_mgr: StorageManager | None = getattr(request.app.state, "storage_manager", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")
    if storage_mgr is None:
        raise HTTPException(status_code=500, detail="Storage not initialized")

    if not file.filename:
        raise HTTPException(status_code=422, detail="Missing filename")

    temp_path = (paths.tmp_dir / f"upload-{uuid.uuid4().hex}.tmp").resolve()

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

    # If already present, do not store bytes again.
    existing = get_asset_by_content_hash(db_path, content_hash=content_hash, include_deleted=False)
    if existing is not None:
        _unlink_best_effort(temp_path)
        return ok(_to_asset(existing))

    # Store bytes using routing rules (S3 if available, else filesystem).
    upload_result = storage_mgr.store_upload(
        temp_path=temp_path,
        asset_id=asset_id,
        kind=kind,
        byte_size=byte_size,
    )

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
            kind=(kind or "file"),
            filename=file.filename,
            content_hash=content_hash,
            byte_size=byte_size,
            mime_type=mime_type,
            storage_provider=upload_result.storage_provider,
            storage_key=upload_result.storage_key,
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

        # If the DB insert lost a race, clean up any temp file we still own.
        if upload_result.cleanup_temp_path is not None:
            _unlink_best_effort(upload_result.cleanup_temp_path)

    # Best-effort exiftool extraction.
    exiftool_path = _resolve_exiftool_executable(request)
    if exiftool_path is not None and not should_skip_exiftool(file.filename):
        # If bytes landed in S3, run ExifTool against the local temp file and
        # delete it when the background task completes.
        local_for_exif = upload_result.local_path or upload_result.cleanup_temp_path
        if local_for_exif is not None:
            background_tasks.add_task(
                _exiftool_background_task,
                db_path=Path(db_path),
                exiftool_path=exiftool_path,
                asset_id=row.asset_id,
                asset_path=local_for_exif,
                cleanup_path=upload_result.cleanup_temp_path,
            )
        else:
            logger.info(
                "ExifTool skipped: no local bytes available",
                extra={"asset_id": row.asset_id},
            )
    elif upload_result.cleanup_temp_path is not None:
        # Ensure temp bytes are cleaned up if we kept them for a potential ExifTool run.
        background_tasks.add_task(_cleanup_temp_file, upload_result.cleanup_temp_path)

    return ok(_to_asset(row))


class BulkImportRequest(BaseModel):
    path: str = Field(min_length=1, description="Directory to scan for files")
    recursive: bool = True
    kind: str = "file"


class BulkImportResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: str


@router.post("/assets/bulk-import", response_model=ApiResponse[BulkImportResponse])
async def assets_bulk_import(
    request: Request, payload: BulkImportRequest
) -> ApiResponse[BulkImportResponse]:
    """Start a bulk import of a local directory as a durable job."""

    db_path = getattr(request.app.state, "db_path", None)
    storage_mgr: StorageManager | None = getattr(request.app.state, "storage_manager", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")
    if storage_mgr is None:
        raise HTTPException(status_code=500, detail="Storage not initialized")

    from faceforge_core.db.jobs import append_job_log, create_job

    job_id = new_job_id()
    job_type = "assets.bulk-import"
    job_input = {"path": payload.path, "recursive": payload.recursive, "kind": payload.kind}

    row = create_job(db_path, job_id=job_id, job_type=job_type, status="queued", input=job_input)
    append_job_log(db_path, job_id=job_id, level="info", message="Job queued")

    ctx = JobContext(db_path=db_path, storage_mgr=storage_mgr)
    start_job_thread(ctx=ctx, job_id=job_id)

    return ok(
        BulkImportResponse(
            job_id=row.job_id,
            job_type=row.job_type,
            status=row.status,
            created_at=row.created_at,
        )
    )


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
    config = getattr(request.app.state, "faceforge_config", None)
    storage_mgr: StorageManager | None = getattr(request.app.state, "storage_manager", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")
    if storage_mgr is None:
        raise HTTPException(status_code=500, detail="Storage not initialized")

    row = get_asset(db_path, asset_id=asset_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    if row.storage_provider == "s3":
        s3_cfg = getattr(getattr(config, "storage", None), "s3", None) if config else None
        if not (s3_cfg is not None and bool(getattr(s3_cfg, "enabled", False))):
            raise HTTPException(status_code=503, detail="S3 storage disabled")
        if storage_mgr.get_s3_provider() is None:
            raise HTTPException(status_code=503, detail="S3 storage not configured")

    try:
        size = storage_mgr.get_size_bytes(
            storage_provider=row.storage_provider,
            storage_key=row.storage_key,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Asset bytes not found") from e
    except Exception as e:
        raise HTTPException(status_code=501, detail="Unsupported storage provider") from e
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

    def _iter_full() -> Any:
        if row.storage_provider == "fs":
            p = storage_mgr.fs.resolve_path(row.storage_key)
            with p.open("rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            return

        if row.storage_provider == "s3":
            s3 = storage_mgr.get_s3_provider()
            if s3 is None:
                return
            loc = S3ObjectLocation.from_storage_key(
                row.storage_key,
                default_bucket=s3.default_bucket,
            )
            yield from s3.iter_range(location=loc, start=0, end=size - 1)
            return

    if range_tuple is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            _iter_full(),
            media_type=mime,
            headers=headers,
        )

    start, end = range_tuple
    content_length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(content_length)

    def _iter_partial() -> Any:
        if row.storage_provider == "fs":
            p = storage_mgr.fs.resolve_path(row.storage_key)
            with p.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            return

        if row.storage_provider == "s3":
            s3 = storage_mgr.get_s3_provider()
            if s3 is None:
                return
            loc = S3ObjectLocation.from_storage_key(
                row.storage_key,
                default_bucket=s3.default_bucket,
            )
            yield from s3.iter_range(location=loc, start=start, end=end)
            return

    return StreamingResponse(
        _iter_partial(),
        status_code=206,
        media_type=mime,
        headers=headers,
    )

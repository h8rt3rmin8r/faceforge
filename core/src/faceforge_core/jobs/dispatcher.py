from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from faceforge_core.db.jobs import (
    append_job_log,
    get_job,
    mark_job_canceled,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from faceforge_core.jobs.bulk_import import run_assets_bulk_import
from faceforge_core.storage.manager import StorageManager


JobHandler = Callable[["JobContext", str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class JobContext:
    db_path: Path
    storage_mgr: StorageManager


_JOB_HANDLERS: dict[str, JobHandler] = {
    "assets.bulk-import": run_assets_bulk_import,
}


def known_job_types() -> set[str]:
    return set(_JOB_HANDLERS.keys())


def start_job_thread(*, ctx: JobContext, job_id: str) -> None:
    t = threading.Thread(
        target=_run_job,
        kwargs={"ctx": ctx, "job_id": job_id},
        name=f"ff-job-{job_id[:8]}",
        daemon=True,
    )
    t.start()


def _run_job(*, ctx: JobContext, job_id: str) -> None:
    job = get_job(ctx.db_path, job_id=job_id, include_deleted=False)
    if job is None:
        return

    handler = _JOB_HANDLERS.get(job.job_type)
    if handler is None:
        append_job_log(
            ctx.db_path,
            job_id=job_id,
            level="error",
            message="Unknown job type",
            data={"job_type": job.job_type},
        )
        mark_job_failed(
            ctx.db_path,
            job_id=job_id,
            error={"code": "unknown_job_type", "message": "Unknown job type"},
        )
        return

    if job.cancel_requested_at is not None:
        append_job_log(ctx.db_path, job_id=job_id, level="info", message="Job canceled")
        mark_job_canceled(
            ctx.db_path,
            job_id=job_id,
            result={"canceled": True},
        )
        return

    try:
        mark_job_running(ctx.db_path, job_id=job_id)
        append_job_log(
            ctx.db_path,
            job_id=job_id,
            level="info",
            message="Job started",
            data={"job_type": job.job_type},
        )

        raw_input = job.input
        job_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}

        result = handler(ctx, job_id, job_input)

        # Handler is responsible for cooperative cancellation state updates.
        final = get_job(ctx.db_path, job_id=job_id, include_deleted=False)
        if final is not None and final.status == "canceled":
            return

        mark_job_succeeded(ctx.db_path, job_id=job_id, result=result)
        append_job_log(ctx.db_path, job_id=job_id, level="info", message="Job completed")
    except Exception as e:
        append_job_log(
            ctx.db_path,
            job_id=job_id,
            level="error",
            message="Job failed",
            data={"error": str(e)},
        )
        mark_job_failed(
            ctx.db_path,
            job_id=job_id,
            error={"code": "job_failed", "message": str(e)},
        )

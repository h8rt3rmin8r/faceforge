from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, ok
from faceforge_core.db.ids import new_job_id
from faceforge_core.db.jobs import (
    JobLogRow,
    JobRow,
    append_job_log,
    get_job,
    list_jobs,
    list_job_logs,
    request_job_cancel,
)
from faceforge_core.jobs.dispatcher import JobContext, known_job_types, start_job_thread
from faceforge_core.storage.manager import StorageManager

router = APIRouter(tags=["jobs"])


class Job(BaseModel):
    job_id: str
    job_type: str
    status: str
    progress_percent: float | None = None
    progress_step: str | None = None
    input: Any | None = None
    result: Any | None = None
    cancel_requested_at: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    canceled_at: str | None = None
    error: Any | None = None


def _to_job(row: JobRow) -> Job:
    return Job(
        job_id=row.job_id,
        job_type=row.job_type,
        status=row.status,
        progress_percent=row.progress_percent,
        progress_step=row.progress_step,
        input=row.input,
        result=row.result,
        cancel_requested_at=row.cancel_requested_at,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        canceled_at=row.canceled_at,
        error=row.error,
    )


class JobCreateRequest(BaseModel):
    job_type: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


@router.post("/jobs", response_model=ApiResponse[Job])
async def jobs_create(request: Request, payload: JobCreateRequest) -> ApiResponse[Job]:
    db_path = getattr(request.app.state, "db_path", None)
    storage_mgr: StorageManager | None = getattr(request.app.state, "storage_manager", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")
    if storage_mgr is None:
        raise HTTPException(status_code=500, detail="Storage not initialized")

    job_type = payload.job_type.strip()
    if job_type not in known_job_types():
        raise HTTPException(
            status_code=422,
            detail=f"Unknown job_type. Supported: {sorted(known_job_types())}",
        )

    job_id = new_job_id()

    # Late import to avoid circular imports at module load time.
    from faceforge_core.db.jobs import create_job

    row = create_job(db_path, job_id=job_id, job_type=job_type, status="queued", input=payload.input)
    append_job_log(db_path, job_id=job_id, level="info", message="Job queued")

    ctx = JobContext(db_path=db_path, storage_mgr=storage_mgr)
    start_job_thread(ctx=ctx, job_id=job_id)

    return ok(_to_job(row))


class JobListResponse(BaseModel):
    items: list[Job]
    total: int
    limit: int
    offset: int


@router.get("/jobs", response_model=ApiResponse[JobListResponse])
async def jobs_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter by exact status"),
    job_type: str | None = Query(default=None, description="Filter by exact job_type"),
) -> ApiResponse[JobListResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    result = list_jobs(db_path, limit=limit, offset=offset, status=status, job_type=job_type)
    return ok(
        JobListResponse(
            items=[_to_job(r) for r in result.items],
            total=result.total,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/jobs/{job_id}", response_model=ApiResponse[Job])
async def jobs_get(request: Request, job_id: str) -> ApiResponse[Job]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    row = get_job(db_path, job_id=job_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return ok(_to_job(row))


class JobLogEntry(BaseModel):
    job_log_id: int
    ts: str
    level: Literal["debug", "info", "warning", "error"] | str
    message: str
    data: Any | None = None


def _to_log(row: JobLogRow) -> JobLogEntry:
    return JobLogEntry(
        job_log_id=row.job_log_id,
        ts=row.ts,
        level=row.level,
        message=row.message,
        data=row.data,
    )


class JobLogResponse(BaseModel):
    items: list[JobLogEntry]
    next_after_id: int


@router.get("/jobs/{job_id}/log", response_model=ApiResponse[JobLogResponse])
async def jobs_log(
    request: Request,
    job_id: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> ApiResponse[JobLogResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    job = get_job(db_path, job_id=job_id, include_deleted=False)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = list_job_logs(db_path, job_id=job_id, after_id=after_id, limit=limit)
    items = [_to_log(r) for r in rows]
    next_after = items[-1].job_log_id if items else after_id
    return ok(JobLogResponse(items=items, next_after_id=next_after))


class JobCancelResponse(BaseModel):
    cancel_requested: bool
    job: Job


@router.post("/jobs/{job_id}/cancel", response_model=ApiResponse[JobCancelResponse])
async def jobs_cancel(request: Request, job_id: str) -> ApiResponse[JobCancelResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    job = get_job(db_path, job_id=job_id, include_deleted=False)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    ok_cancel = request_job_cancel(db_path, job_id=job_id)
    if ok_cancel:
        append_job_log(db_path, job_id=job_id, level="info", message="Cancel requested")

    # Return current state (may still be running; cancellation is cooperative).
    job2 = get_job(db_path, job_id=job_id, include_deleted=False)
    if job2 is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return ok(JobCancelResponse(cancel_requested=ok_cancel, job=_to_job(job2)))

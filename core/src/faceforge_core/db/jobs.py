from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _utc_now_sqlite_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _loads_json(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class JobRow:
    job_id: str
    job_type: str
    status: str
    progress_percent: float | None
    progress_step: str | None
    input: Any
    result: Any
    cancel_requested_at: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    canceled_at: str | None
    error: Any
    deleted_at: str | None


def _job_from_db_row(row: sqlite3.Row) -> JobRow:
    keys = set(row.keys())
    return JobRow(
        job_id=row["job_id"],
        job_type=row["job_type"],
        status=row["status"],
        progress_percent=row["progress_percent"],
        progress_step=row["progress_step"],
        input=_loads_json(row["input_json"]) if "input_json" in keys else None,
        result=_loads_json(row["result_json"]) if "result_json" in keys else None,
        cancel_requested_at=row["cancel_requested_at"] if "cancel_requested_at" in keys else None,
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        canceled_at=row["canceled_at"],
        error=_loads_json(row["error_json"]),
        deleted_at=row["deleted_at"],
    )


def create_job(db_path, *, job_id: str, job_type: str, status: str, input: Any) -> JobRow:
    input_json = json.dumps(input if input is not None else {}, ensure_ascii=False)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (job_id, job_type, status, input_json)
            VALUES (?, ?, ?, ?);
            """.strip(),
            (job_id, job_type, status, input_json),
        )

        row = conn.execute(
            """
            SELECT job_id, job_type, status, progress_percent, progress_step,
                   input_json, result_json, cancel_requested_at,
                   created_at, started_at, finished_at, canceled_at, error_json, deleted_at
            FROM jobs
            WHERE job_id = ?;
            """.strip(),
            (job_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read job after insert")

    return _job_from_db_row(row)


def get_job(db_path, *, job_id: str, include_deleted: bool = False) -> JobRow | None:
    where = "WHERE job_id = ?"
    params: list[Any] = [job_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT job_id, job_type, status, progress_percent, progress_step,
                   input_json, result_json, cancel_requested_at,
                   created_at, started_at, finished_at, canceled_at, error_json, deleted_at
            FROM jobs
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _job_from_db_row(row) if row is not None else None


@dataclass(frozen=True)
class JobListResult:
    items: list[JobRow]
    total: int


def list_jobs(
    db_path,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    job_type: str | None = None,
) -> JobListResult:
    clauses: list[str] = ["deleted_at IS NULL"]
    params: list[Any] = []

    if status is not None and status.strip():
        clauses.append("status = ?")
        params.append(status.strip())

    if job_type is not None and job_type.strip():
        clauses.append("job_type = ?")
        params.append(job_type.strip())

    where_sql = "WHERE " + " AND ".join(clauses)

    with _connect(db_path) as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS n FROM jobs {where_sql};",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row is not None else 0

        rows = conn.execute(
            f"""
            SELECT job_id, job_type, status, progress_percent, progress_step,
                   input_json, result_json, cancel_requested_at,
                   created_at, started_at, finished_at, canceled_at, error_json, deleted_at
            FROM jobs
            {where_sql}
            ORDER BY created_at DESC, job_id ASC
            LIMIT ? OFFSET ?;
            """.strip(),
            [*params, limit, offset],
        ).fetchall()

    return JobListResult(items=[_job_from_db_row(r) for r in rows], total=total)


def mark_job_running(db_path, *, job_id: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running', started_at = COALESCE(started_at, ?)
            WHERE job_id = ? AND deleted_at IS NULL AND status IN ('queued');
            """.strip(),
            (_utc_now_sqlite_iso(), job_id),
        )


def update_job_progress(
    db_path,
    *,
    job_id: str,
    progress_percent: float | None = None,
    progress_step: str | None = None,
) -> None:
    updates: list[str] = []
    params: list[Any] = []

    if progress_percent is not None:
        updates.append("progress_percent = ?")
        params.append(float(progress_percent))

    if progress_step is not None:
        updates.append("progress_step = ?")
        params.append(progress_step)

    if not updates:
        return

    params.append(job_id)

    with _connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE jobs
            SET {", ".join(updates)}
            WHERE job_id = ? AND deleted_at IS NULL;
            """.strip(),
            params,
        )


def mark_job_succeeded(db_path, *, job_id: str, result: Any | None = None) -> None:
    result_json = json.dumps(result, ensure_ascii=False) if result is not None else None

    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'succeeded',
                progress_percent = COALESCE(progress_percent, 100.0),
                finished_at = COALESCE(finished_at, ?),
                result_json = COALESCE(result_json, ?)
            WHERE job_id = ? AND deleted_at IS NULL AND status NOT IN ('succeeded','failed','canceled');
            """.strip(),
            (_utc_now_sqlite_iso(), result_json, job_id),
        )


def mark_job_failed(db_path, *, job_id: str, error: Any) -> None:
    error_json = json.dumps(error, ensure_ascii=False)

    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                finished_at = COALESCE(finished_at, ?),
                error_json = ?
            WHERE job_id = ? AND deleted_at IS NULL AND status NOT IN ('succeeded','failed','canceled');
            """.strip(),
            (_utc_now_sqlite_iso(), error_json, job_id),
        )


def request_job_cancel(db_path, *, job_id: str) -> bool:
    now = _utc_now_sqlite_iso()

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET cancel_requested_at = COALESCE(cancel_requested_at, ?)
            WHERE job_id = ?
              AND deleted_at IS NULL
              AND status IN ('queued', 'running');
            """.strip(),
            (now, job_id),
        )
        return cur.rowcount > 0


def mark_job_canceled(db_path, *, job_id: str, result: Any | None = None) -> None:
    result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
    now = _utc_now_sqlite_iso()

    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'canceled',
                canceled_at = COALESCE(canceled_at, ?),
                finished_at = COALESCE(finished_at, ?),
                result_json = COALESCE(result_json, ?)
            WHERE job_id = ? AND deleted_at IS NULL AND status NOT IN ('succeeded','failed','canceled');
            """.strip(),
            (now, now, result_json, job_id),
        )


@dataclass(frozen=True)
class JobLogRow:
    job_log_id: int
    job_id: str
    ts: str
    level: str
    message: str
    data: Any


def _job_log_from_db_row(row: sqlite3.Row) -> JobLogRow:
    return JobLogRow(
        job_log_id=int(row["job_log_id"]),
        job_id=row["job_id"],
        ts=row["ts"],
        level=row["level"],
        message=row["message"],
        data=_loads_json(row["data_json"]),
    )


def append_job_log(
    db_path,
    *,
    job_id: str,
    level: str,
    message: str,
    data: Any | None = None,
) -> JobLogRow:
    data_json = json.dumps(data, ensure_ascii=False) if data is not None else None

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO job_logs (job_id, level, message, data_json)
            VALUES (?, ?, ?, ?);
            """.strip(),
            (job_id, level, message, data_json),
        )
        if cur.lastrowid is None:
            raise RuntimeError("Failed to insert job log")
        job_log_id = int(cur.lastrowid)

        row = conn.execute(
            """
            SELECT job_log_id, job_id, ts, level, message, data_json
            FROM job_logs
            WHERE job_log_id = ?;
            """.strip(),
            (job_log_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read job log after insert")

    return _job_log_from_db_row(row)


def list_job_logs(
    db_path,
    *,
    job_id: str,
    after_id: int = 0,
    limit: int = 500,
) -> list[JobLogRow]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT job_log_id, job_id, ts, level, message, data_json
            FROM job_logs
            WHERE job_id = ? AND job_log_id > ?
            ORDER BY job_log_id ASC
            LIMIT ?;
            """.strip(),
            (job_id, after_id, limit),
        ).fetchall()

    return [_job_log_from_db_row(r) for r in rows]

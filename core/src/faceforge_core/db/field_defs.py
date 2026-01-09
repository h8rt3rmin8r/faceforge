from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from faceforge_core.db.ids import new_field_def_id


def _utc_now_sqlite_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _loads_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _dumps_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


@dataclass(frozen=True)
class FieldDefRow:
    field_def_id: str
    scope: str
    field_key: str
    field_type: str
    required: bool
    options: Any
    regex: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


def _field_def_from_db_row(row: sqlite3.Row) -> FieldDefRow:
    return FieldDefRow(
        field_def_id=row["field_def_id"],
        scope=row["scope"],
        field_key=row["field_key"],
        field_type=row["field_type"],
        required=bool(int(row["required"])),
        options=_loads_json(row["options_json"]),
        regex=row["regex"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def create_field_def(
    db_path,
    *,
    scope: str,
    field_key: str,
    field_type: str,
    required: bool = False,
    options: Any | None = None,
    regex: str | None = None,
) -> FieldDefRow:
    field_def_id = new_field_def_id()
    options_json = _dumps_json(options)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO field_definitions (
                field_def_id, scope, field_key, field_type, required, options_json, regex
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """.strip(),
            (
                field_def_id,
                scope,
                field_key,
                field_type,
                1 if required else 0,
                options_json,
                regex,
            ),
        )

        row = conn.execute(
            """
            SELECT field_def_id, scope, field_key, field_type, required, options_json, regex,
                   created_at, updated_at, deleted_at
            FROM field_definitions
            WHERE field_def_id = ?;
            """.strip(),
            (field_def_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read field definition after insert")

    return _field_def_from_db_row(row)


def get_field_def(
    db_path, *, field_def_id: str, include_deleted: bool = False
) -> FieldDefRow | None:
    where = "WHERE field_def_id = ?"
    params: list[Any] = [field_def_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT field_def_id, scope, field_key, field_type, required, options_json, regex,
                   created_at, updated_at, deleted_at
            FROM field_definitions
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _field_def_from_db_row(row) if row is not None else None


def get_field_def_by_key(
    db_path, *, scope: str, field_key: str, include_deleted: bool = False
) -> FieldDefRow | None:
    where = "WHERE scope = ? AND field_key = ?"
    params: list[Any] = [scope, field_key]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT field_def_id, scope, field_key, field_type, required, options_json, regex,
                   created_at, updated_at, deleted_at
            FROM field_definitions
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _field_def_from_db_row(row) if row is not None else None


def list_field_defs(
    db_path,
    *,
    scope: str | None = None,
    include_deleted: bool = False,
) -> list[FieldDefRow]:
    clauses: list[str] = []
    params: list[Any] = []

    if scope is not None and scope.strip():
        clauses.append("scope = ?")
        params.append(scope.strip())

    if not include_deleted:
        clauses.append("deleted_at IS NULL")

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT field_def_id, scope, field_key, field_type, required, options_json, regex,
                   created_at, updated_at, deleted_at
            FROM field_definitions
            {where_sql}
            ORDER BY scope ASC, field_key ASC, field_def_id ASC;
            """.strip(),
            params,
        ).fetchall()

    return [_field_def_from_db_row(r) for r in rows]


def patch_field_def(
    db_path,
    *,
    field_def_id: str,
    scope: str | None = None,
    field_key: str | None = None,
    field_type: str | None = None,
    required: bool | None = None,
    options: Any | None = None,
    regex: str | None = None,
) -> FieldDefRow | None:
    current = get_field_def(db_path, field_def_id=field_def_id, include_deleted=False)
    if current is None:
        return None

    updates: list[str] = []
    params: list[Any] = []

    if scope is not None:
        updates.append("scope = ?")
        params.append(scope)

    if field_key is not None:
        updates.append("field_key = ?")
        params.append(field_key)

    if field_type is not None:
        updates.append("field_type = ?")
        params.append(field_type)

    if required is not None:
        updates.append("required = ?")
        params.append(1 if required else 0)

    if options is not None:
        updates.append("options_json = ?")
        params.append(_dumps_json(options))

    if regex is not None:
        updates.append("regex = ?")
        params.append(regex)

    if not updates:
        return current

    updates.append("updated_at = ?")
    params.append(_utc_now_sqlite_iso())
    params.append(field_def_id)

    with _connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE field_definitions
            SET {", ".join(updates)}
            WHERE field_def_id = ? AND deleted_at IS NULL;
            """.strip(),
            params,
        )

        row = conn.execute(
            """
            SELECT field_def_id, scope, field_key, field_type, required, options_json, regex,
                   created_at, updated_at, deleted_at
            FROM field_definitions
            WHERE field_def_id = ? AND deleted_at IS NULL;
            """.strip(),
            (field_def_id,),
        ).fetchone()

    return _field_def_from_db_row(row) if row is not None else None


def soft_delete_field_def(db_path, *, field_def_id: str) -> bool:
    now = _utc_now_sqlite_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE field_definitions
            SET deleted_at = ?, updated_at = ?
            WHERE field_def_id = ? AND deleted_at IS NULL;
            """.strip(),
            (now, now, field_def_id),
        )
        return cur.rowcount > 0

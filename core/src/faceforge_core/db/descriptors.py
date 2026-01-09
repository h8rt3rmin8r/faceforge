from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from faceforge_core.db.ids import new_descriptor_id


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
        return None


def _dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class DescriptorRow:
    descriptor_id: str
    entity_id: str
    scope: str
    field_key: str
    value: Any
    created_at: str
    updated_at: str
    deleted_at: str | None


def _descriptor_from_db_row(row: sqlite3.Row) -> DescriptorRow:
    return DescriptorRow(
        descriptor_id=row["descriptor_id"],
        entity_id=row["entity_id"],
        scope=row["scope"],
        field_key=row["field_key"],
        value=_loads_json(row["value_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def list_descriptors_for_entity(
    db_path, *, entity_id: str, include_deleted: bool = False
) -> list[DescriptorRow]:
    where = "WHERE entity_id = ?"
    params: list[Any] = [entity_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT descriptor_id, entity_id, scope, field_key, value_json,
                   created_at, updated_at, deleted_at
            FROM descriptors
            {where}
            ORDER BY scope ASC, field_key ASC, descriptor_id ASC;
            """.strip(),
            params,
        ).fetchall()

    return [_descriptor_from_db_row(r) for r in rows]


def get_descriptor(
    db_path, *, descriptor_id: str, include_deleted: bool = False
) -> DescriptorRow | None:
    where = "WHERE descriptor_id = ?"
    params: list[Any] = [descriptor_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT descriptor_id, entity_id, scope, field_key, value_json,
                   created_at, updated_at, deleted_at
            FROM descriptors
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _descriptor_from_db_row(row) if row is not None else None


def create_descriptor(
    db_path,
    *,
    entity_id: str,
    scope: str,
    field_key: str,
    value: Any,
) -> DescriptorRow:
    descriptor_id = new_descriptor_id()
    value_json = _dumps_json(value)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO descriptors (descriptor_id, entity_id, scope, field_key, value_json)
            VALUES (?, ?, ?, ?, ?);
            """.strip(),
            (descriptor_id, entity_id, scope, field_key, value_json),
        )

        row = conn.execute(
            """
            SELECT descriptor_id, entity_id, scope, field_key, value_json,
                   created_at, updated_at, deleted_at
            FROM descriptors
            WHERE descriptor_id = ?;
            """.strip(),
            (descriptor_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read descriptor after insert")

    return _descriptor_from_db_row(row)


def patch_descriptor_value(db_path, *, descriptor_id: str, value: Any) -> DescriptorRow | None:
    value_json = _dumps_json(value)

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE descriptors
            SET value_json = ?, updated_at = ?
            WHERE descriptor_id = ? AND deleted_at IS NULL;
            """.strip(),
            (value_json, _utc_now_sqlite_iso(), descriptor_id),
        )
        if cur.rowcount == 0:
            return None

        row = conn.execute(
            """
            SELECT descriptor_id, entity_id, scope, field_key, value_json,
                   created_at, updated_at, deleted_at
            FROM descriptors
            WHERE descriptor_id = ? AND deleted_at IS NULL;
            """.strip(),
            (descriptor_id,),
        ).fetchone()

    return _descriptor_from_db_row(row) if row is not None else None


def soft_delete_descriptor(db_path, *, descriptor_id: str) -> bool:
    now = _utc_now_sqlite_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE descriptors
            SET deleted_at = ?, updated_at = ?
            WHERE descriptor_id = ? AND deleted_at IS NULL;
            """.strip(),
            (now, now, descriptor_id),
        )
        return cur.rowcount > 0

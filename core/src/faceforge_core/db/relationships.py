from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from faceforge_core.db.ids import new_relationship_id


def _utc_now_sqlite_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _loads_dict(raw: str) -> dict[str, Any]:
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(v, dict):
        return v
    return {}


def _dumps_dict(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


@dataclass(frozen=True)
class RelationshipRow:
    relationship_id: str
    src_entity_id: str
    dst_entity_id: str
    relationship_type: str
    fields: dict[str, Any]
    created_at: str
    deleted_at: str | None


def _relationship_from_db_row(row: sqlite3.Row) -> RelationshipRow:
    return RelationshipRow(
        relationship_id=row["relationship_id"],
        src_entity_id=row["src_entity_id"],
        dst_entity_id=row["dst_entity_id"],
        relationship_type=row["relationship_type"],
        fields=_loads_dict(row["fields_json"]),
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
    )


def create_relationship(
    db_path,
    *,
    src_entity_id: str,
    dst_entity_id: str,
    relationship_type: str,
    fields: dict[str, Any] | None = None,
) -> RelationshipRow:
    relationship_id = new_relationship_id()
    fields_json = _dumps_dict(fields)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO relationships (
                relationship_id,
                src_entity_id,
                dst_entity_id,
                relationship_type,
                fields_json
            )
            VALUES (?, ?, ?, ?, ?);
            """.strip(),
            (relationship_id, src_entity_id, dst_entity_id, relationship_type, fields_json),
        )

        row = conn.execute(
            """
            SELECT relationship_id, src_entity_id, dst_entity_id, relationship_type,
                   fields_json, created_at, deleted_at
            FROM relationships
            WHERE relationship_id = ?;
            """.strip(),
            (relationship_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read relationship after insert")

    return _relationship_from_db_row(row)


def get_relationship(
    db_path,
    *,
    relationship_id: str,
    include_deleted: bool = False,
) -> RelationshipRow | None:
    where = "WHERE relationship_id = ?"
    params: list[Any] = [relationship_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT relationship_id, src_entity_id, dst_entity_id, relationship_type,
                   fields_json, created_at, deleted_at
            FROM relationships
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _relationship_from_db_row(row) if row is not None else None


def list_relationships_for_entity(
    db_path,
    *,
    entity_id: str,
    include_deleted: bool = False,
) -> list[RelationshipRow]:
    where = "WHERE (src_entity_id = ? OR dst_entity_id = ?)"
    params: list[Any] = [entity_id, entity_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT relationship_id, src_entity_id, dst_entity_id, relationship_type,
                   fields_json, created_at, deleted_at
            FROM relationships
            {where}
            ORDER BY created_at DESC, relationship_id ASC;
            """.strip(),
            params,
        ).fetchall()

    return [_relationship_from_db_row(r) for r in rows]


def soft_delete_relationship(db_path, *, relationship_id: str) -> bool:
    now = _utc_now_sqlite_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE relationships
            SET deleted_at = ?
            WHERE relationship_id = ? AND deleted_at IS NULL;
            """.strip(),
            (now, relationship_id),
        )
        return cur.rowcount > 0


def list_relationship_types(
    db_path,
    *,
    query: str | None,
    limit: int,
    include_deleted: bool = False,
) -> list[str]:
    clauses: list[str] = []
    params: list[Any] = []

    if not include_deleted:
        clauses.append("deleted_at IS NULL")

    q = (query or "").strip().lower()
    if q:
        clauses.append("LOWER(relationship_type) LIKE ?")
        params.append(f"%{q}%")

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT relationship_type
            FROM relationships
            {where_sql}
            ORDER BY relationship_type ASC
            LIMIT ?;
            """.strip(),
            [*params, limit],
        ).fetchall()

    out: list[str] = []
    for r in rows:
        v = r["relationship_type"]
        if isinstance(v, str) and v.strip():
            out.append(v)
    return out

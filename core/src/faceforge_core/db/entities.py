from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from faceforge_core.db.ids import new_entity_id


def _utc_now_sqlite_iso() -> str:
    # Match the DB default format closely: YYYY-MM-DDTHH:MM:SS.sssZ
    # SQLite stores TEXT; we standardize to milliseconds.
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class EntityRow:
    entity_id: str
    display_name: str
    aliases: list[str]
    tags: list[str]
    fields: dict[str, Any]
    created_at: str
    updated_at: str
    deleted_at: str | None


def _loads_list(raw: str) -> list[str]:
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    return []


def _loads_dict(raw: str) -> dict[str, Any]:
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(v, dict):
        return v
    return {}


def _entity_from_db_row(row: sqlite3.Row) -> EntityRow:
    return EntityRow(
        entity_id=row["entity_id"],
        display_name=row["display_name"],
        aliases=_loads_list(row["aliases_json"]),
        tags=_loads_list(row["tags_json"]),
        fields=_loads_dict(row["fields_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_entity(
    db_path,
    *,
    display_name: str,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    fields: dict[str, Any] | None = None,
) -> EntityRow:
    entity_id = new_entity_id()
    aliases_json = json.dumps(aliases or [], ensure_ascii=False)
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    fields_json = json.dumps(fields or {}, ensure_ascii=False)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO entities (entity_id, display_name, aliases_json, tags_json, fields_json)
            VALUES (?, ?, ?, ?, ?);
            """.strip(),
            (entity_id, display_name, aliases_json, tags_json, fields_json),
        )

        row = conn.execute(
            """
            SELECT entity_id, display_name, aliases_json, tags_json, fields_json,
                   created_at, updated_at, deleted_at
            FROM entities
            WHERE entity_id = ?;
            """.strip(),
            (entity_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read entity after insert")

    return _entity_from_db_row(row)


def get_entity(db_path, *, entity_id: str, include_deleted: bool = False) -> EntityRow | None:
    where = "WHERE entity_id = ?"
    params: list[Any] = [entity_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT entity_id, display_name, aliases_json, tags_json, fields_json,
                   created_at, updated_at, deleted_at
            FROM entities
            {where};
            """.strip(),
            params,
        ).fetchone()

    if row is None:
        return None
    return _entity_from_db_row(row)


@dataclass(frozen=True)
class EntityListResult:
    items: list[EntityRow]
    total: int


def _build_list_filters(
    *,
    q: str | None,
    tag: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = ["deleted_at IS NULL"]
    params: list[Any] = []

    if q is not None and q.strip():
        # Minimal search primitive (intentionally not fancy): substring match.
        like = f"%{q.strip()}%"
        clauses.append(
            "(display_name LIKE ? OR aliases_json LIKE ? OR tags_json LIKE ? OR fields_json LIKE ?)"
        )
        params.extend([like, like, like, like])

    if tag is not None and tag.strip():
        # tags are stored as a JSON array of strings.
        # Minimal filter: string contains \"<tag>\".
        needle = f'%"{tag.strip()}"%'
        clauses.append("tags_json LIKE ?")
        params.append(needle)

    where_sql = "WHERE " + " AND ".join(clauses)
    return where_sql, params


def list_entities(
    db_path,
    *,
    limit: int,
    offset: int,
    sort_by: str,
    sort_order: str,
    q: str | None = None,
    tag: str | None = None,
) -> EntityListResult:
    allowed_sort_by = {
        "created_at": "created_at",
        "updated_at": "updated_at",
        "display_name": "display_name",
    }
    allowed_order = {"asc": "ASC", "desc": "DESC"}

    sort_col = allowed_sort_by.get(sort_by, "created_at")
    order_sql = allowed_order.get(sort_order.lower() if sort_order else "", "DESC")

    where_sql, params = _build_list_filters(q=q, tag=tag)

    with _connect(db_path) as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS n FROM entities {where_sql};",
            params,
        ).fetchone()
        total = int(total_row["n"]) if total_row is not None else 0

        rows = conn.execute(
            f"""
            SELECT entity_id, display_name, aliases_json, tags_json, fields_json,
                   created_at, updated_at, deleted_at
            FROM entities
            {where_sql}
            ORDER BY {sort_col} {order_sql}, entity_id ASC
            LIMIT ? OFFSET ?;
            """.strip(),
            [*params, limit, offset],
        ).fetchall()

    items = [_entity_from_db_row(r) for r in rows]
    return EntityListResult(items=items, total=total)


def patch_entity(
    db_path,
    *,
    entity_id: str,
    display_name: str | None = None,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    fields: dict[str, Any] | None = None,
) -> EntityRow | None:
    # Read current to support partial updates without clobbering.
    current = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if current is None:
        return None

    updates: list[str] = []
    params: list[Any] = []

    if display_name is not None:
        updates.append("display_name = ?")
        params.append(display_name)

    if aliases is not None:
        updates.append("aliases_json = ?")
        params.append(json.dumps(aliases, ensure_ascii=False))

    if tags is not None:
        updates.append("tags_json = ?")
        params.append(json.dumps(tags, ensure_ascii=False))

    if fields is not None:
        updates.append("fields_json = ?")
        params.append(json.dumps(fields, ensure_ascii=False))

    if not updates:
        return current

    updates.append("updated_at = ?")
    params.append(_utc_now_sqlite_iso())
    params.append(entity_id)

    with _connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE entities
            SET {", ".join(updates)}
            WHERE entity_id = ? AND deleted_at IS NULL;
            """.strip(),
            params,
        )

        row = conn.execute(
            """
            SELECT entity_id, display_name, aliases_json, tags_json, fields_json,
                   created_at, updated_at, deleted_at
            FROM entities
            WHERE entity_id = ? AND deleted_at IS NULL;
            """.strip(),
            (entity_id,),
        ).fetchone()

    if row is None:
        return None
    return _entity_from_db_row(row)


def soft_delete_entity(db_path, *, entity_id: str) -> bool:
    now = _utc_now_sqlite_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE entities
            SET deleted_at = ?, updated_at = ?
            WHERE entity_id = ? AND deleted_at IS NULL;
            """.strip(),
            (now, now, entity_id),
        )
    return cur.rowcount > 0

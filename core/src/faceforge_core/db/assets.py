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


def _loads_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


@dataclass(frozen=True)
class AssetRow:
    asset_id: str
    kind: str
    filename: str | None
    content_hash: str
    byte_size: int
    mime_type: str | None
    storage_provider: str
    storage_key: str
    meta: Any
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class EntityAssetRow:
    entity_id: str
    asset: AssetRow
    role: str | None
    linked_at: str


def _asset_from_db_row(row: sqlite3.Row) -> AssetRow:
    return AssetRow(
        asset_id=row["asset_id"],
        kind=row["kind"],
        filename=row["filename"],
        content_hash=row["content_hash"],
        byte_size=int(row["byte_size"]),
        mime_type=row["mime_type"],
        storage_provider=row["storage_provider"],
        storage_key=row["storage_key"],
        meta=_loads_json(row["meta_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def get_asset(db_path, *, asset_id: str, include_deleted: bool = False) -> AssetRow | None:
    where = "WHERE asset_id = ?"
    params: list[Any] = [asset_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT asset_id, kind, filename, content_hash, byte_size, mime_type,
                   storage_provider, storage_key, meta_json, created_at, updated_at, deleted_at
            FROM assets
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _asset_from_db_row(row) if row is not None else None


def get_asset_by_content_hash(
    db_path, *, content_hash: str, include_deleted: bool = False
) -> AssetRow | None:
    where = "WHERE content_hash = ?"
    params: list[Any] = [content_hash]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT asset_id, kind, filename, content_hash, byte_size, mime_type,
                   storage_provider, storage_key, meta_json, created_at, updated_at, deleted_at
            FROM assets
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _asset_from_db_row(row) if row is not None else None


def create_asset(
    db_path,
    *,
    asset_id: str,
    kind: str,
    filename: str | None,
    content_hash: str,
    byte_size: int,
    mime_type: str | None,
    storage_provider: str,
    storage_key: str,
    meta: Any,
) -> AssetRow:
    meta_json = json.dumps(meta if meta is not None else {}, ensure_ascii=False)

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id,
                kind,
                filename,
                content_hash,
                byte_size,
                mime_type,
                storage_provider,
                storage_key,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """.strip(),
            (
                asset_id,
                kind,
                filename,
                content_hash,
                byte_size,
                mime_type,
                storage_provider,
                storage_key,
                meta_json,
            ),
        )

        row = conn.execute(
            """
            SELECT asset_id, kind, filename, content_hash, byte_size, mime_type,
                   storage_provider, storage_key, meta_json, created_at, updated_at, deleted_at
            FROM assets
            WHERE asset_id = ?;
            """.strip(),
            (asset_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read asset after insert")

    return _asset_from_db_row(row)


def update_asset_meta(db_path, *, asset_id: str, meta: Any) -> AssetRow | None:
    meta_json = json.dumps(meta if meta is not None else {}, ensure_ascii=False)

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE assets
            SET meta_json = ?, updated_at = ?
            WHERE asset_id = ? AND deleted_at IS NULL;
            """.strip(),
            (meta_json, _utc_now_sqlite_iso(), asset_id),
        )
        if cur.rowcount == 0:
            return None

        row = conn.execute(
            """
            SELECT asset_id, kind, filename, content_hash, byte_size, mime_type,
                   storage_provider, storage_key, meta_json, created_at, updated_at, deleted_at
            FROM assets
            WHERE asset_id = ?;
            """.strip(),
            (asset_id,),
        ).fetchone()

    return _asset_from_db_row(row) if row is not None else None


def append_asset_metadata_entry(
    db_path, *, asset_id: str, entry: dict[str, Any]
) -> AssetRow | None:
    current = get_asset(db_path, asset_id=asset_id, include_deleted=False)
    if current is None:
        return None

    meta = current.meta
    if not isinstance(meta, dict):
        meta = {}

    items = meta.get("metadata")
    if not isinstance(items, list):
        items = []
    items.append(entry)
    meta["metadata"] = items

    return update_asset_meta(db_path, asset_id=asset_id, meta=meta)


def link_asset_to_entity(
    db_path,
    *,
    entity_id: str,
    asset_id: str,
    role: str | None = None,
) -> None:
    now = _utc_now_sqlite_iso()

    with _connect(db_path) as conn:
        # Idempotent: if it already exists, update role and clear deleted_at.
        conn.execute(
            """
            INSERT INTO entity_assets (entity_id, asset_id, role, created_at, deleted_at)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(entity_id, asset_id) DO UPDATE SET
                role = excluded.role,
                deleted_at = NULL;
            """.strip(),
            (entity_id, asset_id, role, now),
        )


def unlink_asset_from_entity(db_path, *, entity_id: str, asset_id: str) -> bool:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE entity_assets
            SET deleted_at = ?
            WHERE entity_id = ? AND asset_id = ? AND deleted_at IS NULL;
            """.strip(),
            (_utc_now_sqlite_iso(), entity_id, asset_id),
        )
        return cur.rowcount > 0


def list_assets_for_entity(
    db_path,
    *,
    entity_id: str,
    include_deleted_links: bool = False,
    include_deleted_assets: bool = False,
) -> list[EntityAssetRow]:
    link_where = "ea.entity_id = ?"
    params: list[Any] = [entity_id]

    if not include_deleted_links:
        link_where += " AND ea.deleted_at IS NULL"

    asset_where = "1=1"
    if not include_deleted_assets:
        asset_where += " AND a.deleted_at IS NULL"

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                ea.entity_id,
                ea.role,
                ea.created_at AS linked_at,
                a.asset_id,
                a.kind,
                a.filename,
                a.content_hash,
                a.byte_size,
                a.mime_type,
                a.storage_provider,
                a.storage_key,
                a.meta_json,
                a.created_at,
                a.updated_at,
                a.deleted_at
            FROM entity_assets ea
            JOIN assets a ON a.asset_id = ea.asset_id
            WHERE {link_where} AND {asset_where}
            ORDER BY ea.created_at DESC, a.asset_id ASC;
            """.strip(),
            params,
        ).fetchall()

    out: list[EntityAssetRow] = []
    for r in rows:
        asset = _asset_from_db_row(r)
        out.append(
            EntityAssetRow(
                entity_id=r["entity_id"],
                asset=asset,
                role=r["role"],
                linked_at=r["linked_at"],
            )
        )
    return out

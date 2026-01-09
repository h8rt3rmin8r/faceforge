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


def _dumps_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


@dataclass(frozen=True)
class PluginRegistryRow:
    plugin_id: str
    enabled: bool
    version: str | None
    config: Any
    discovered_at: str
    updated_at: str
    deleted_at: str | None


def _row_from_db(row: sqlite3.Row) -> PluginRegistryRow:
    return PluginRegistryRow(
        plugin_id=row["plugin_id"],
        enabled=bool(int(row["enabled"])),
        version=row["version"],
        config=_loads_json(row["config_json"]),
        discovered_at=row["discovered_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def upsert_plugin_discovery(
    db_path,
    *,
    plugin_id: str,
    version: str | None,
) -> PluginRegistryRow:
    now = _utc_now_sqlite_iso()

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO plugin_registry (
                plugin_id,
                enabled,
                version,
                config_json,
                discovered_at,
                updated_at,
                deleted_at
            )
            VALUES (?, 0, ?, '{}', ?, ?, NULL)
            ON CONFLICT(plugin_id) DO UPDATE SET
                version = excluded.version,
                discovered_at = excluded.discovered_at,
                updated_at = excluded.updated_at,
                deleted_at = NULL;
            """.strip(),
            (plugin_id, version, now, now),
        )

        row = conn.execute(
            """
            SELECT plugin_id, enabled, version, config_json, discovered_at, updated_at, deleted_at
            FROM plugin_registry
            WHERE plugin_id = ?;
            """.strip(),
            (plugin_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Failed to read plugin registry after upsert")

    return _row_from_db(row)


def list_plugin_registry(db_path, *, include_deleted: bool = False) -> list[PluginRegistryRow]:
    where = "WHERE 1=1"
    params: list[Any] = []
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT plugin_id, enabled, version, config_json, discovered_at, updated_at, deleted_at
            FROM plugin_registry
            {where}
            ORDER BY plugin_id ASC;
            """.strip(),
            params,
        ).fetchall()

    return [_row_from_db(r) for r in rows]


def get_plugin_registry(
    db_path,
    *,
    plugin_id: str,
    include_deleted: bool = False,
) -> PluginRegistryRow | None:
    where = "WHERE plugin_id = ?"
    params: list[Any] = [plugin_id]
    if not include_deleted:
        where += " AND deleted_at IS NULL"

    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT plugin_id, enabled, version, config_json, discovered_at, updated_at, deleted_at
            FROM plugin_registry
            {where};
            """.strip(),
            params,
        ).fetchone()

    return _row_from_db(row) if row is not None else None


def set_plugin_enabled(db_path, *, plugin_id: str, enabled: bool) -> PluginRegistryRow | None:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE plugin_registry
            SET enabled = ?, updated_at = ?, deleted_at = NULL
            WHERE plugin_id = ? AND deleted_at IS NULL;
            """.strip(),
            (1 if enabled else 0, _utc_now_sqlite_iso(), plugin_id),
        )
        if cur.rowcount == 0:
            return None

        row = conn.execute(
            """
            SELECT plugin_id, enabled, version, config_json, discovered_at, updated_at, deleted_at
            FROM plugin_registry
            WHERE plugin_id = ? AND deleted_at IS NULL;
            """.strip(),
            (plugin_id,),
        ).fetchone()

    return _row_from_db(row) if row is not None else None


def get_plugin_config(db_path, *, plugin_id: str) -> Any | None:
    row = get_plugin_registry(db_path, plugin_id=plugin_id, include_deleted=False)
    if row is None:
        return None
    return row.config


def set_plugin_config(db_path, *, plugin_id: str, config: Any) -> PluginRegistryRow | None:
    config_json = _dumps_json(config)

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE plugin_registry
            SET config_json = ?, updated_at = ?, deleted_at = NULL
            WHERE plugin_id = ? AND deleted_at IS NULL;
            """.strip(),
            (config_json, _utc_now_sqlite_iso(), plugin_id),
        )
        if cur.rowcount == 0:
            return None

        row = conn.execute(
            """
            SELECT plugin_id, enabled, version, config_json, discovered_at, updated_at, deleted_at
            FROM plugin_registry
            WHERE plugin_id = ? AND deleted_at IS NULL;
            """.strip(),
            (plugin_id,),
        ).fetchone()

    return _row_from_db(row) if row is not None else None

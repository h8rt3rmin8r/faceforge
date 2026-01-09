from __future__ import annotations

import sqlite3
from pathlib import Path

from faceforge_core.config import load_core_config, resolve_configured_paths
from faceforge_core.db import resolve_db_path
from faceforge_core.db.migrate import apply_migrations
from faceforge_core.home import ensure_faceforge_layout


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name ASC;"
        ).fetchall()
    return {r[0] for r in rows}


def _table_columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {r[1] for r in rows}


def test_migrations_blank_to_latest(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)
    config = load_core_config(paths)
    paths = resolve_configured_paths(paths, config)

    db_path = resolve_db_path(paths)

    apply_migrations(db_path)
    apply_migrations(db_path)  # idempotent

    tables = _table_names(db_path)

    assert "schema_migrations" in tables
    assert "entities" in tables
    assert "assets" in tables
    assert "entity_assets" in tables
    assert "relationships" in tables
    assert "jobs" in tables
    assert "job_logs" in tables
    assert "field_definitions" in tables
    assert "plugin_registry" in tables

    jobs_cols = _table_columns(db_path, "jobs")
    assert "input_json" in jobs_cols
    assert "result_json" in jobs_cols
    assert "cancel_requested_at" in jobs_cols

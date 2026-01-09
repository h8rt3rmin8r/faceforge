from __future__ import annotations

import sqlite3
from pathlib import Path

from faceforge_core.db.migrations import MIGRATIONS


def ensure_db_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def apply_migrations(db_path: Path) -> None:
    """Apply all known migrations to a SQLite DB.

    - Safe to run multiple times.
    - Works from blank DB -> latest.
    """

    ensure_db_parent_dir(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
            ");"
        )

        applied = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM schema_migrations ORDER BY name ASC;"
            ).fetchall()
        }

        for name, sql in MIGRATIONS:
            if name in applied:
                continue

            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?);", (name,))

from __future__ import annotations

from pathlib import Path

from faceforge_core.home import FaceForgePaths

DEFAULT_DB_FILENAME = "core.sqlite3"


def resolve_db_path(paths: FaceForgePaths) -> Path:
    """Resolve the Core metadata SQLite database path.

    The directory is controlled by the Sprint 1 `db_dir` layout/override.
    """

    return paths.db_dir / DEFAULT_DB_FILENAME

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from faceforge_core.config import load_core_config, resolve_configured_paths
from faceforge_core.db import resolve_db_path
from faceforge_core.db.ids import asset_id_from_content_hash, new_entity_id, sha256_hex_file
from faceforge_core.db.migrate import apply_migrations
from faceforge_core.home import ensure_faceforge_layout, resolve_faceforge_home


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_entity(db_path: Path, *, display_name: str) -> str:
    entity_id = new_entity_id()

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO entities (entity_id, display_name, aliases_json, tags_json, fields_json)
            VALUES (?, ?, '[]', '[]', '{}');
            """.strip(),
            (entity_id, display_name),
        )

    return entity_id


def create_asset_from_file(
    db_path: Path, *, file_path: Path, kind: str = "file"
) -> tuple[str, str]:
    content_hash = sha256_hex_file(file_path)
    asset_id = asset_id_from_content_hash(content_hash)

    meta = {
        "source": {"path": str(file_path)},
    }

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
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?);
            """.strip(),
            (
                asset_id,
                kind,
                file_path.name,
                content_hash,
                file_path.stat().st_size,
                json.dumps(meta, ensure_ascii=False),
            ),
        )

    return asset_id, content_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m faceforge_core.internal.bootstrap_db",
        description="FaceForge Core internal DB bootstrapper (no API).",
    )
    parser.add_argument("--home", type=Path, default=None, help="Override FACEFORGE_HOME")
    parser.add_argument("--migrate", action="store_true", help="Apply migrations")
    parser.add_argument(
        "--create-entity", metavar="NAME", help="Create an entity with display_name"
    )
    parser.add_argument(
        "--create-asset",
        metavar="PATH",
        type=Path,
        help="Create an asset record from a file",
    )
    args = parser.parse_args(argv)

    environ = None
    if args.home is not None:
        environ = {"FACEFORGE_HOME": str(args.home)}

    home = resolve_faceforge_home(environ)
    paths = ensure_faceforge_layout(home)
    config = load_core_config(paths)
    paths = resolve_configured_paths(paths, config)

    db_path = resolve_db_path(paths)

    if args.migrate or args.create_entity or args.create_asset:
        apply_migrations(db_path)

    if args.create_entity:
        entity_id = create_entity(db_path, display_name=args.create_entity)
        print(entity_id)

    if args.create_asset:
        asset_id, content_hash = create_asset_from_file(db_path, file_path=args.create_asset)
        print(json.dumps({"asset_id": asset_id, "content_hash": content_hash}, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

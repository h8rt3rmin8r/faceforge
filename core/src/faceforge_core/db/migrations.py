from __future__ import annotations

MIGRATIONS: list[tuple[str, str]] = [
    (
        "0001_init",
        """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    fields_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_deleted_at ON entities(deleted_at);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'file',
    filename TEXT,
    content_hash TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    mime_type TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT,
    UNIQUE(content_hash)
);

CREATE INDEX IF NOT EXISTS idx_assets_deleted_at ON assets(deleted_at);

CREATE TABLE IF NOT EXISTS entity_assets (
    entity_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    role TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT,
    PRIMARY KEY (entity_id, asset_id),
    FOREIGN KEY(entity_id) REFERENCES entities(entity_id) ON DELETE RESTRICT,
    FOREIGN KEY(asset_id) REFERENCES assets(asset_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_entity_assets_entity_id ON entity_assets(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_assets_asset_id ON entity_assets(asset_id);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    src_entity_id TEXT NOT NULL,
    dst_entity_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    fields_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT,
    FOREIGN KEY(src_entity_id) REFERENCES entities(entity_id) ON DELETE RESTRICT,
    FOREIGN KEY(dst_entity_id) REFERENCES entities(entity_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_relationships_src ON relationships(src_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_dst ON relationships(dst_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_percent REAL,
    progress_step TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    canceled_at TEXT,
    error_json TEXT,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_deleted_at ON jobs(deleted_at);

CREATE TABLE IF NOT EXISTS job_logs (
    job_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_job_logs_ts ON job_logs(ts);

CREATE TABLE IF NOT EXISTS field_definitions (
    field_def_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'entity',
    field_key TEXT NOT NULL,
    field_type TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 0,
    options_json TEXT NOT NULL DEFAULT '{}',
    regex TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT,
    UNIQUE(scope, field_key)
);

CREATE INDEX IF NOT EXISTS idx_field_defs_deleted_at ON field_definitions(deleted_at);

CREATE TABLE IF NOT EXISTS plugin_registry (
    plugin_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    version TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_plugin_registry_enabled ON plugin_registry(enabled);
CREATE INDEX IF NOT EXISTS idx_plugin_registry_deleted_at ON plugin_registry(deleted_at);
""",
    )
]

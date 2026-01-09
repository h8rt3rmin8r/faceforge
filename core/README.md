# FaceForge Core

This folder contains the **Core API service** (planned: FastAPI + Uvicorn).

## Sprint 1: home/config/runtime contract

Core is **local-first** and writes all persistent/runtime files under `FACEFORGE_HOME`.

### FACEFORGE_HOME

- If `FACEFORGE_HOME` is set, Core uses that directory.
- If it is not set, Core defaults to a local dev folder: `./.faceforge` (relative to the working directory).

### Required subfolders

On startup, Core ensures these directories exist:

- `${FACEFORGE_HOME}/db`
- `${FACEFORGE_HOME}/s3`
- `${FACEFORGE_HOME}/logs`
- `${FACEFORGE_HOME}/run`
- `${FACEFORGE_HOME}/config`
- `${FACEFORGE_HOME}/plugins`

### Core config file

Core loads JSON config from:

- `${FACEFORGE_HOME}/config/core.json`

If the file does not exist, defaults are used.

Current config shape (v1, subject to change):

```json
{
	"version": "1",
	"auth": {
		"install_token": "..."
	},
	"network": {
		"bind_host": "127.0.0.1",
		"core_port": 8787,
		"seaweed_s3_port": null
	},
	"paths": {
		"db_dir": null,
		"s3_dir": null,
		"logs_dir": null,
		"plugins_dir": null
	}
}
```

Notes:

- `paths.*` may be absolute paths or paths relative to `FACEFORGE_HOME`.
- `run/` and `config/` are intentionally **not configurable**.

### Runtime ports file

Desktop (or other launcher) may write the selected ports to:

- `${FACEFORGE_HOME}/run/ports.json`

Format:

```json
{
	"core": 43210,
	"seaweed_s3": 43211
}
```

Core also supports a legacy location for compatibility with the design spec:

- `${FACEFORGE_HOME}/runtime/ports.json`

## Dev run

From the repo root (Windows PowerShell):

- `./scripts/dev-core.ps1`
- `./scripts/check-core.ps1` (format + lint + tests)

This repo is set up to avoid relying on a global Python for running commands.
The scripts create/use the repo-local `.venv` and always run via `.venv\\Scripts\\python.exe`.

Prereq: Python 3.12+ installed (used only to bootstrap the repo-local `.venv`).

The service should come up on `http://127.0.0.1:8787` and expose:

- `GET /healthz`
- `GET /docs` (public)
- `GET /v1/ping` (requires token)
- `GET /v1/system/info` (requires token)
- `GET /v1/entities` (requires token)
- `POST /v1/entities` (requires token)
- `GET/PATCH/DELETE /v1/entities/{entity_id}` (requires token)

### Auth (Sprint 3)

Core requires a per-install token for non-health endpoints.

- The token is stored in `${FACEFORGE_HOME}/config/core.json` under `auth.install_token`.
- Requests may provide the token via:
	- `Authorization: Bearer <token>`
	- `X-FaceForge-Token: <token>`

## Sprint 2: SQLite schema + migrations (internal)

Core stores metadata in a SQLite DB under:

- `${FACEFORGE_HOME}/db/core.sqlite3`

On Core startup, schema migrations are applied automatically (idempotent).

Apply migrations and create sample records without using the API:

- `python -m faceforge_core.internal.bootstrap_db --home <PATH> --migrate`
- `python -m faceforge_core.internal.bootstrap_db --home <PATH> --create-entity "Ada Lovelace"`
- `python -m faceforge_core.internal.bootstrap_db --home <PATH> --create-asset <FILEPATH>`

## Sprint 4: Entities CRUD (v1)

Endpoints:

- `GET /v1/entities`
- `POST /v1/entities`
- `GET /v1/entities/{entity_id}`
- `PATCH /v1/entities/{entity_id}`
- `DELETE /v1/entities/{entity_id}` (soft delete)

List query params (minimal primitives):

- `limit` (default 50, max 200)
- `offset` (default 0)
- `sort_by`: `created_at` | `updated_at` | `display_name`
- `sort_order`: `asc` | `desc`
- `q`: substring match (basic)
- `tag`: filter by exact tag string

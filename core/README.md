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
- `GET /docs`

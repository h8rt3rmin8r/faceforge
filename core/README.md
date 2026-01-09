# FaceForge Core

This folder contains the **Core API service** (planned: FastAPI + Uvicorn).

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

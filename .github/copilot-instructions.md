# faceforge — Copilot agent notes

## Source of truth
- Treat the design spec as authoritative: `docs/FaceForge Core - Project Design Specification - v0.2.9.md`.
- The implementation roadmap lives in: `docs/FaceForge Core - MVP Sprint Sequence.md`.

## Repo layout (current)
- `core/` and `desktop/` are currently placeholders (`.keep`); most “how it should work” is only in `docs/` today.
- `brand/` contains fonts/logo/favicon assets used for UI branding.

## Big-picture architecture (intended)
- **Desktop-managed local bundle** (no end-user Docker): a **Tauri v2** desktop shell orchestrates a local **Core API server**.
- **Core = “boring center”**: stable CRUD + storage + jobs/logs + plugin surface; compute-heavy work is out-of-process plugins.
- **Integration-first**: external tools should interact via a stable HTTP API; keep OpenAPI accurate.

## Core conventions to follow when implementing
- API routes are versioned under `/v1/...`; enable `/docs` and `/redoc`.
- Default network posture: bind to `127.0.0.1`; require a **per-install token** for non-health endpoints.
- Local-first storage contract: resolve `FACEFORGE_HOME` and create subfolders (e.g. `db/`, `logs/`, `config/`, `plugins/`).
- Metadata DB is **SQLite**; model “relational spine + JSON fields” (entities/assets/relationships/jobs + flexible descriptors).
- Asset download must be streaming-friendly with HTTP range support; avoid hiding user data inside opaque volumes.
- Default object storage is an S3-compatible local endpoint (SeaweedFS per spec), but Core must still work with filesystem-only storage.

## How to work in this repo as it evolves
- When adding initial code, keep boundaries: Core service code under `core/`, desktop orchestrator under `desktop/`.
- Prefer small, spec-aligned increments (Sprint 0 → Sprint N); if you introduce dev commands/scripts, document them in `README.md`.

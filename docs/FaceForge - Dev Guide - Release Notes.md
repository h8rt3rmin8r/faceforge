# FaceForge v0.1.9 Release Notes

This is a patch release focused on Desktop bundling reliability and significant improvements to the documentation generation pipeline (HTML/PDF).

## Summary
- **Desktop packaging**: Ensures the official SeaweedFS `weed.exe` is staged during release builds (so installers ship a real binary, not a placeholder).
- **Docs pipeline**: Improves `update-docs.ps1` with a cleaner config-driven workflow and more robust PDF generation.
- **Repo hygiene**: Consolidates documentation under `docs/`, improves styling/assets, and removes leftover version-pinned links.

## Upgrade Notes
- No manual configuration changes are expected for this update.

## Known Issues
- No new issues have been identified in this release. If you hit something, please file a GitHub issue with logs from `FACEFORGE_HOME/logs/`.

---

# FaceForge v0.1.8 Release Notes

This is a patch release focused on Desktop orchestration quality-of-life and maintainer/developer workflow polish.

## Summary
- **Desktop orchestration**: Adds auto-restart behavior and a “minimize on exit” setting, with accompanying UI updates.
- **Build & scripts**: Improves PowerShell scripts with richer comment-based help and auto-generated scripts documentation.
- **Versioning hygiene**: Keeps version metadata aligned across manifests and lockfiles for repeatable builds.

## Upgrade Notes
- No manual configuration changes are expected for this update.

## Known Issues
- No new issues have been identified in this release. If you hit something, please file a GitHub issue with logs from `FACEFORGE_HOME/logs/`.

---

# FaceForge v0.1.7 Release Notes

This is a patch release focused on documentation/packaging polish and keeping version metadata consistent across Core and Desktop.

## Summary
- **Docs output**: Auto-generates HTML/PDF versions of README docs.
- **README accuracy**: Updates `FACEFORGE_HOME` directory structure and config path details.
- **Versioning**: Keeps version strings aligned across the repo for bundling and release automation.

---

# FaceForge v0.1.6 Release Notes

This is a patch release focused on stability and operational polish across Core and Desktop. It includes improvements to how the local filesystem layout is structured, reduces logging edge-cases during reload, and tightens a couple of first-run/wizard flows.

## Summary
- **Core layout**: Uses a deterministic, OS-appropriate default for `FACEFORGE_HOME` (never the current working directory) and keeps the FaceForge home clean and predictable.
- **Logging**: Refines logging setup to reduce duplicate-handler behavior and keep rotation reliable.
- **Desktop wizard/UI**: Makes first-run settings persistence more robust and aligns the settings payload structure.
- **Automation**: Improves non-interactive build behavior for CI and scripted usage.

## What Changed

### Core
- **FaceForge home + layout**: Ensures `FACEFORGE_HOME` resolution never depends on the process working directory (e.g. running an installer from Downloads).
- **Logging initialization cleanup**: Refactors the log handler setup to avoid duplicate handlers on reload, and keeps output consistent.

### Desktop
- **First-run robustness**: Ensures the temporary directory exists before saving wizard settings.
- **Settings payload consistency**: Updates the UI-side payload structure to match what the desktop side expects.

### Build & Developer Experience
- **Non-interactive builds**: Updates `scripts/build-core.ps1` to avoid confirmation prompts when running unattended.
- **Dependency metadata hygiene**: Keeps Tauri desktop lockfile version metadata consistent.

## Upgrade Notes
- On next start, Core will create any missing subfolders under `FACEFORGE_HOME` (notably `tmp/` and `tools/`) if they do not already exist.
- No manual configuration changes are expected for this update.

## Known Issues
- No new issues have been identified in this release. If you hit something, please file a GitHub issue with logs from `FACEFORGE_HOME/logs/`.

---

# FaceForge v0.1.5 Release Notes

We are excited to announce FaceForge v0.1.5! This release brings significant improvements to the desktop orchestration, UI enhancements, and a more robust development infrastructure.

## 🚀 Key Changes

### Desktop & UI
- **Refactored Orchestrator**: Improved tool path resolution and stability in the desktop orchestrator.
- **Settings & Logs Management**: Enhanced the UI with a dedicated settings interface and better log viewing capabilities.
- **Styling Improvements**: Polished the overall look and feel for a smoother user experience.

### Core & Infrastructure
- **Centralized Version Management**: Introduced a new `scripts/set-version.ps1` script to eliminate hardcoded version strings and ensure consistency across the project.
- **Path Structure**: Updated ports path and file structure layout.

## 📦 Maintenance
- **Version consistency**: Synchronized version numbers across Core (Python), Desktop (Tauri), and Rust components.

---
*For a full list of changes, please refer to the git log.*

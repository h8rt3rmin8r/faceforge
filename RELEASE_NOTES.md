# FaceForge v0.1.6 Release Notes

This is a patch release focused on stability and operational polish across Core and Desktop. It includes improvements to how the local filesystem layout is structured, reduces logging edge-cases during reload, and tightens a couple of first-run/wizard flows.

## Summary
- **Core layout**: Introduces dedicated runtime and tools directories to keep the FaceForge home clean and predictable.
- **Logging**: Refines logging setup to reduce duplicate-handler behavior and keep rotation reliable.
- **Desktop wizard/UI**: Makes first-run settings persistence more robust and aligns the settings payload structure.
- **Automation**: Improves non-interactive build behavior for CI and scripted usage.

## What Changed

### Core
- **New FaceForgePaths fields**: Adds `run_dir` and `tools_dir` and threads them through layout/config/ports handling.
- **Logging initialization cleanup**: Refactors the log handler setup to avoid duplicate handlers on reload, and keeps output consistent.

### Desktop
- **First-run robustness**: Ensures the temporary directory exists before saving wizard settings.
- **Settings payload consistency**: Updates the UI-side payload structure to match what the desktop side expects.

### Build & Developer Experience
- **Non-interactive builds**: Updates `scripts/build-core.ps1` to avoid confirmation prompts when running unattended.
- **Dependency metadata hygiene**: Keeps Tauri desktop lockfile version metadata consistent.

## Upgrade Notes
- On next start, Core will create new subfolders under `FACEFORGE_HOME` (notably `run/` and `tools/`) if they do not already exist.
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
- **Version consistency**: Synchronized version numbers across Core (Python), Desktop (Node/Tauri), and Rust components.

---
*For a full list of changes, please refer to the git log.*

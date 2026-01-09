from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def test_healthz_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

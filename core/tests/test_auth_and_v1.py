from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def test_v1_requires_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        r = client.get("/v1/ping")
        assert r.status_code == 401
        body = r.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "unauthorized"

        token = client.app.state.faceforge_config.auth.install_token
        assert isinstance(token, str)
        assert token

        r2 = client.get("/v1/ping", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True, "data": {"pong": True}, "error": None}

        r3 = client.get("/v1/system/info", headers={"Authorization": f"Bearer {token}"})
        assert r3.status_code == 200
        body3 = r3.json()
        assert body3["ok"] is True
        assert body3["data"]["faceforge_home"]
        assert body3["data"]["version"]


def test_docs_and_openapi_are_public(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        docs = client.get("/docs")
        assert docs.status_code == 200

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        spec = openapi.json()
        assert "/v1/ping" in spec.get("paths", {})
        assert "/v1/system/info" in spec.get("paths", {})

        op = spec["paths"]["/v1/ping"]["get"]
        assert "security" in op

        op2 = spec["paths"]["/v1/system/info"]["get"]
        assert "security" in op2

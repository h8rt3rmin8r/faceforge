from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def test_ui_login_is_public_and_ui_requires_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        r = client.get("/ui/login")
        assert r.status_code == 200

        r2 = client.get("/ui/entities")
        assert r2.status_code == 401


def test_ui_cookie_auth_allows_ui_and_asset_download(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        token = client.app.state.faceforge_config.auth.install_token

        # Login (sets cookie)
        r = client.post("/ui/login", data={"token": token}, follow_redirects=False)
        assert r.status_code == 302

        # UI page should render with cookie-based auth
        ui = client.get("/ui/entities")
        assert ui.status_code == 200
        assert "Entities" in ui.text

        # Upload asset via API (header auth)
        headers = {"Authorization": f"Bearer {token}"}
        content = b"hello world"
        up = client.post(
            "/v1/assets/upload",
            headers=headers,
            files={"file": ("hello.txt", content, "text/plain")},
        )
        assert up.status_code == 200
        asset_id = up.json()["data"]["asset_id"]

        # Download via cookie auth (no header)
        dl = client.get(f"/v1/assets/{asset_id}/download")
        assert dl.status_code == 200
        assert dl.content == content


def test_ui_plugins_page_renders_discovered_plugins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    plugin_dir = tmp_path / "plugins" / "demo-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo.plugin",
                "name": "Demo Plugin",
                "version": "0.1.0",
                "capabilities": ["ui"],
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "enabled_by_default": {"type": "boolean", "description": "Example flag"}
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        token = client.app.state.faceforge_config.auth.install_token
        r = client.post("/ui/login", data={"token": token}, follow_redirects=False)
        assert r.status_code == 302

        p = client.get("/ui/plugins")
        assert p.status_code == 200
        assert "demo.plugin" in p.text

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def _write_demo_plugin(
    plugins_dir: Path,
    *,
    plugin_id: str = "demo.plugin",
    name: str = "Demo Plugin",
    config_schema: dict[str, Any] | None = None,
) -> None:
    plugin_dir = plugins_dir / "demo-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "name": name,
                "version": "0.1.0",
                "capabilities": ["ui"],
                "config_schema": config_schema,
            }
        ),
        encoding="utf-8",
    )


def test_plugins_list_discovers_and_persists_enabled_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    _write_demo_plugin(tmp_path / "plugins")

    # First run: plugin discovered; enable it.
    with TestClient(create_app()) as client:
        app = cast(FastAPI, client.app)
        token = app.state.faceforge_config.auth.install_token
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/v1/plugins", headers=headers)
        assert r.status_code == 200
        items = cast(list[dict[str, Any]], r.json()["data"]["items"])
        assert any(p["plugin_id"] == "demo.plugin" for p in items)

        e = client.post("/v1/plugins/demo.plugin/enable", headers=headers)
        assert e.status_code == 200
        assert e.json()["data"]["enabled"] is True

    # Second run: enabled state should persist in sqlite.
    with TestClient(create_app()) as client2:
        app2 = cast(FastAPI, client2.app)
        token2 = app2.state.faceforge_config.auth.install_token
        headers2 = {"Authorization": f"Bearer {token2}"}

        r2 = client2.get("/v1/plugins", headers=headers2)
        assert r2.status_code == 200
        items2 = cast(list[dict[str, Any]], r2.json()["data"]["items"])
        demo = next(p for p in items2 if p["plugin_id"] == "demo.plugin")
        assert demo["enabled"] is True


def test_plugins_config_put_validates_schema_and_roundtrips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    _write_demo_plugin(
        tmp_path / "plugins",
        config_schema={
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "required": ["foo"],
            "additionalProperties": False,
        },
    )

    with TestClient(create_app()) as client:
        app = cast(FastAPI, client.app)
        token = app.state.faceforge_config.auth.install_token
        headers = {"Authorization": f"Bearer {token}"}

        bad = client.put("/v1/plugins/demo.plugin/config", headers=headers, json={"config": {}})
        assert bad.status_code == 422

        good = client.put(
            "/v1/plugins/demo.plugin/config",
            headers=headers,
            json={"config": {"foo": "bar"}},
        )
        assert good.status_code == 200
        assert good.json()["data"]["config"]["foo"] == "bar"

        getc = client.get("/v1/plugins/demo.plugin/config", headers=headers)
        assert getc.status_code == 200
        assert getc.json()["data"]["config"]["foo"] == "bar"

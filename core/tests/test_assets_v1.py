from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_assets_upload_metadata_download_range_and_linking(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        token = client.app.state.faceforge_config.auth.install_token
        headers = {"Authorization": f"Bearer {token}"}

        content = b"hello world"
        sidecar = b'{"foo": "bar"}'

        r = client.post(
            "/v1/assets/upload",
            headers=headers,
            files={
                "file": ("hello.txt", content, "text/plain"),
                "meta": ("_meta.json", sidecar, "application/json"),
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        asset_id = body["data"]["asset_id"]
        assert asset_id == _sha256_hex(content)

        r2 = client.get(f"/v1/assets/{asset_id}", headers=headers)
        assert r2.status_code == 200
        meta = r2.json()["data"]
        assert meta["byte_size"] == len(content)
        assert meta["content_hash"] == _sha256_hex(content)
        assert isinstance(meta["meta"], dict)
        assert isinstance(meta["meta"].get("metadata"), list)
        assert any(x.get("Source") == "UserSidecar" for x in meta["meta"].get("metadata", []))

        d = client.get(f"/v1/assets/{asset_id}/download", headers=headers)
        assert d.status_code == 200
        assert d.content == content

        d2 = client.get(
            f"/v1/assets/{asset_id}/download",
            headers={**headers, "Range": "bytes=0-4"},
        )
        assert d2.status_code == 206
        assert d2.content == b"hello"
        assert d2.headers.get("content-range", "").startswith("bytes 0-4/")

        d3 = client.get(
            f"/v1/assets/{asset_id}/download",
            headers={**headers, "Range": "bytes=999-1000"},
        )
        assert d3.status_code == 416

        e = client.post(
            "/v1/entities",
            headers=headers,
            json={"display_name": "Alice", "aliases": [], "tags": [], "fields": {}},
        )
        assert e.status_code == 200
        entity_id = e.json()["data"]["entity_id"]

        link = client.post(
            f"/v1/entities/{entity_id}/assets/{asset_id}",
            headers=headers,
            json={"role": "primary"},
        )
        assert link.status_code == 200
        assert link.json()["data"]["linked"] is True

        unlink = client.delete(
            f"/v1/entities/{entity_id}/assets/{asset_id}",
            headers=headers,
        )
        assert unlink.status_code == 200
        assert unlink.json()["data"]["linked"] is True

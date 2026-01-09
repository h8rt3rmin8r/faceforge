from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from faceforge_core.app import create_app


def _auth_headers(client: TestClient) -> dict[str, str]:
    state = getattr(client.app, "state", None)
    config = getattr(state, "faceforge_config", None)
    auth = getattr(config, "auth", None)
    token = getattr(auth, "install_token", None)
    assert isinstance(token, str)
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_entities_crud_and_paging(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        # Create 100 entities
        created_ids: list[str] = []
        for i in range(100):
            name = f"Entity {i:03d}"
            r = client.post(
                "/v1/entities",
                headers=headers,
                json={
                    "display_name": name,
                    "aliases": [f"E{i}"] if i % 10 == 0 else [],
                    "tags": ["batch", "even"] if i % 2 == 0 else ["batch", "odd"],
                    "fields": {"index": i},
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            created_ids.append(body["data"]["entity_id"])

        # Page through them
        r1 = client.get("/v1/entities?limit=25&offset=0", headers=headers)
        assert r1.status_code == 200
        body1 = r1.json()["data"]
        assert body1["total"] == 100
        assert body1["limit"] == 25
        assert body1["offset"] == 0
        assert len(body1["items"]) == 25

        r2 = client.get("/v1/entities?limit=50&offset=75", headers=headers)
        assert r2.status_code == 200
        body2 = r2.json()["data"]
        assert body2["total"] == 100
        assert len(body2["items"]) == 25

        # Minimal filter: tag
        r3 = client.get("/v1/entities?tag=even", headers=headers)
        assert r3.status_code == 200
        body3 = r3.json()["data"]
        assert body3["total"] == 50


def test_entity_patch_only_updates_touched_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        created = client.post(
            "/v1/entities",
            headers=headers,
            json={
                "display_name": "Ada Lovelace",
                "aliases": ["Augusta Ada"],
                "tags": ["person", "math"],
                "fields": {"born": 1815, "died": 1852},
            },
        )
        assert created.status_code == 200
        entity = created.json()["data"]
        entity_id = entity["entity_id"]
        created_at = entity["created_at"]

        patched = client.patch(
            f"/v1/entities/{entity_id}",
            headers=headers,
            json={"display_name": "Ada King"},
        )
        assert patched.status_code == 200
        patched_entity = patched.json()["data"]
        assert patched_entity["entity_id"] == entity_id
        assert patched_entity["display_name"] == "Ada King"

        # Ensure untouched fields were not clobbered
        assert patched_entity["aliases"] == ["Augusta Ada"]
        assert patched_entity["tags"] == ["person", "math"]
        assert patched_entity["fields"] == {"born": 1815, "died": 1852}

        # Timestamps behave sensibly: created_at is stable
        assert patched_entity["created_at"] == created_at
        assert isinstance(patched_entity["updated_at"], str)
        assert patched_entity["updated_at"]


def test_entity_delete_soft_hides_from_get_and_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        created = client.post(
            "/v1/entities",
            headers=headers,
            json={"display_name": "Delete Me"},
        )
        entity_id = created.json()["data"]["entity_id"]

        deleted = client.delete(f"/v1/entities/{entity_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["data"]["deleted"] is True

        get_after = client.get(f"/v1/entities/{entity_id}", headers=headers)
        assert get_after.status_code == 404

        listed = client.get("/v1/entities", headers=headers)
        assert listed.status_code == 200
        items = listed.json()["data"]["items"]
        assert all(e["entity_id"] != entity_id for e in items)

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


def test_relationships_round_trip_query_and_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        # Create 2 entities
        e1 = client.post("/v1/entities", headers=headers, json={"display_name": "Alice"})
        assert e1.status_code == 200
        src_id = e1.json()["data"]["entity_id"]

        e2 = client.post("/v1/entities", headers=headers, json={"display_name": "Bob"})
        assert e2.status_code == 200
        dst_id = e2.json()["data"]["entity_id"]

        # Create relationship
        created = client.post(
            "/v1/relationships",
            headers=headers,
            json={
                "src_entity_id": src_id,
                "dst_entity_id": dst_id,
                "relationship_type": "friend",
                "fields": {"note": "met at work"},
            },
        )
        assert created.status_code == 200
        rel = created.json()["data"]
        rel_id = rel["relationship_id"]
        assert rel["src_entity_id"] == src_id
        assert rel["dst_entity_id"] == dst_id
        assert rel["relationship_type"] == "friend"
        assert rel["fields"] == {"note": "met at work"}

        # Query by src
        listed_src = client.get(f"/v1/relationships?entity_id={src_id}", headers=headers)
        assert listed_src.status_code == 200
        items_src = listed_src.json()["data"]["items"]
        assert any(x["relationship_id"] == rel_id for x in items_src)

        # Query by dst
        listed_dst = client.get(f"/v1/relationships?entity_id={dst_id}", headers=headers)
        assert listed_dst.status_code == 200
        items_dst = listed_dst.json()["data"]["items"]
        assert any(x["relationship_id"] == rel_id for x in items_dst)

        # Relation-type suggestions include DB-created type
        sugg = client.get("/v1/relation-types?query=fri", headers=headers)
        assert sugg.status_code == 200
        types = sugg.json()["data"]["items"]
        assert "friend" in [t.lower() for t in types]

        # Delete relationship (soft)
        deleted = client.delete(f"/v1/relationships/{rel_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["data"]["deleted"] is True

        # No longer queryable
        listed_after = client.get(f"/v1/relationships?entity_id={src_id}", headers=headers)
        assert listed_after.status_code == 200
        items_after = listed_after.json()["data"]["items"]
        assert all(x["relationship_id"] != rel_id for x in items_after)


def test_relation_types_seed_list_is_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        # Fresh DB should still provide suggestions.
        r = client.get("/v1/relation-types?query=par", headers=headers)
        assert r.status_code == 200
        items = [x.lower() for x in r.json()["data"]["items"]]
        assert "parent" in items

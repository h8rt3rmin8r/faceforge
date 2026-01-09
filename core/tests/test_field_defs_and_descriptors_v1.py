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


def test_field_defs_crud_and_descriptor_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        # Create field definition (required + regex)
        fd = client.post(
            "/v1/admin/field-defs",
            headers=headers,
            json={
                "scope": "descriptor",
                "field_key": "country_code",
                "field_type": "string",
                "required": True,
                "regex": "^[A-Z]{2}$",
                "options": {},
            },
        )
        assert fd.status_code == 200
        field_def_id = fd.json()["data"]["field_def_id"]
        assert field_def_id

        # List includes it
        listed = client.get("/v1/admin/field-defs?scope=descriptor", headers=headers)
        assert listed.status_code == 200
        items = listed.json()["data"]["items"]
        assert any(x["field_key"] == "country_code" for x in items)

        # Create entity
        e = client.post(
            "/v1/entities",
            headers=headers,
            json={"display_name": "Alice", "aliases": [], "tags": [], "fields": {}},
        )
        assert e.status_code == 200
        entity_id = e.json()["data"]["entity_id"]

        # Invalid descriptor rejected (regex)
        bad = client.post(
            f"/v1/entities/{entity_id}/descriptors",
            headers=headers,
            json={"scope": "descriptor", "field_key": "country_code", "value": "us"},
        )
        assert bad.status_code == 422
        bad_body = bad.json()
        assert bad_body["ok"] is False
        assert bad_body["error"]["code"] == "validation_error"

        # Valid descriptor accepted
        good = client.post(
            f"/v1/entities/{entity_id}/descriptors",
            headers=headers,
            json={"scope": "descriptor", "field_key": "country_code", "value": "US"},
        )
        assert good.status_code == 200
        descriptor_id = good.json()["data"]["descriptor_id"]
        assert descriptor_id

        # Patch descriptor with invalid value
        bad_patch = client.patch(
            f"/v1/descriptors/{descriptor_id}",
            headers=headers,
            json={"value": "USA"},
        )
        assert bad_patch.status_code == 422

        # Patch descriptor with valid value
        good_patch = client.patch(
            f"/v1/descriptors/{descriptor_id}",
            headers=headers,
            json={"value": "CA"},
        )
        assert good_patch.status_code == 200
        assert good_patch.json()["data"]["value"] == "CA"

        # Delete descriptor
        deleted = client.delete(f"/v1/descriptors/{descriptor_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["data"]["deleted"] is True

        # Delete field definition
        deleted_fd = client.delete(f"/v1/admin/field-defs/{field_def_id}", headers=headers)
        assert deleted_fd.status_code == 200


def test_enum_options_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FACEFORGE_HOME", str(tmp_path))

    with TestClient(create_app()) as client:
        headers = _auth_headers(client)

        fd = client.post(
            "/v1/admin/field-defs",
            headers=headers,
            json={
                "scope": "descriptor",
                "field_key": "eye_color",
                "field_type": "enum",
                "required": False,
                "options": {"options": ["blue", "green", "brown"]},
            },
        )
        assert fd.status_code == 200

        e = client.post(
            "/v1/entities",
            headers=headers,
            json={"display_name": "Bob", "aliases": [], "tags": [], "fields": {}},
        )
        assert e.status_code == 200
        entity_id = e.json()["data"]["entity_id"]

        bad = client.post(
            f"/v1/entities/{entity_id}/descriptors",
            headers=headers,
            json={"scope": "descriptor", "field_key": "eye_color", "value": "hazel"},
        )
        assert bad.status_code == 422

        good = client.post(
            f"/v1/entities/{entity_id}/descriptors",
            headers=headers,
            json={"scope": "descriptor", "field_key": "eye_color", "value": "green"},
        )
        assert good.status_code == 200

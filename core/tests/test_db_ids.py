from __future__ import annotations

from faceforge_core.db.ids import asset_id_from_content_hash, new_entity_id, sha256_hex


def test_sha256_hex_known_value() -> None:
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_new_entity_id_is_sha256_hex() -> None:
    entity_id = new_entity_id()
    assert len(entity_id) == 64
    assert all(c in "0123456789abcdef" for c in entity_id)


def test_asset_id_from_content_hash_validation() -> None:
    h = sha256_hex(b"hello")
    assert asset_id_from_content_hash(h) == h

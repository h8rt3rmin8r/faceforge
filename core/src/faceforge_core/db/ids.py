from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import BinaryIO


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_hex_stream(stream: BinaryIO, *, chunk_size: int = 1024 * 1024) -> str:
    """Compute a SHA-256 hex digest from a binary stream."""

    h = hashlib.sha256()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


def sha256_hex_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    with path.open("rb") as f:
        return sha256_hex_stream(f, chunk_size=chunk_size)


def new_entity_id() -> str:
    """Generate a new entity ID.

    IDs are SHA-256 hex strings (64 chars) and are generated at creation time.
    """

    return sha256_hex(uuid.uuid4().bytes)


def asset_id_from_content_hash(content_hash: str) -> str:
    """Derive the asset ID from a content hash.

    For v1 we keep this 1:1 with the SHA-256 hex digest.
    """

    content_hash = content_hash.strip().lower()
    if len(content_hash) != 64 or any(c not in "0123456789abcdef" for c in content_hash):
        raise ValueError("content_hash must be a 64-character lowercase hex sha256 digest")
    return content_hash

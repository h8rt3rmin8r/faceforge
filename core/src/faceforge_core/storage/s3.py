from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class S3ObjectLocation:
    bucket: str
    key: str

    def to_storage_key(self) -> str:
        # Keep it simple and parseable.
        return f"{self.bucket}:{self.key}"

    @staticmethod
    def from_storage_key(storage_key: str, *, default_bucket: str) -> S3ObjectLocation:
        raw = (storage_key or "").strip()
        if ":" in raw:
            bucket, key = raw.split(":", 1)
            bucket = bucket.strip()
            key = key.strip()
            if bucket and key:
                return S3ObjectLocation(bucket=bucket, key=key)
        return S3ObjectLocation(bucket=default_bucket, key=raw)


class S3StorageProvider:
    """S3-compatible storage provider (intended for SeaweedFS S3 endpoint)."""

    provider_name = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str,
        use_ssl: bool,
        default_bucket: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._use_ssl = use_ssl
        self._default_bucket = default_bucket
        self._client = None

    @property
    def default_bucket(self) -> str:
        return self._default_bucket

    def _get_client(self):
        if self._client is not None:
            return self._client

        import boto3
        from botocore.client import Config

        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            use_ssl=self._use_ssl,
            config=Config(s3={"addressing_style": "path"}),
        )
        return self._client

    def ensure_bucket(self, bucket: str | None = None) -> None:
        b = bucket or self._default_bucket
        client = self._get_client()
        try:
            client.head_bucket(Bucket=b)
            return
        except Exception:
            # Best-effort create.
            client.create_bucket(Bucket=b)

    def key_for_asset_id(self, asset_id: str) -> str:
        asset_id = asset_id.strip().lower()
        shard = asset_id[:2] if len(asset_id) >= 2 else "xx"
        return f"assets/{shard}/{asset_id}"

    def put_file(self, *, temp_path: Path, location: S3ObjectLocation) -> None:
        client = self._get_client()
        self.ensure_bucket(location.bucket)
        with temp_path.open("rb") as f:
            client.put_object(Bucket=location.bucket, Key=location.key, Body=f)


    def put_file_from_path(self, *, source_path: Path, location: S3ObjectLocation) -> None:
        client = self._get_client()
        self.ensure_bucket(location.bucket)
        with source_path.open("rb") as f:
            client.put_object(Bucket=location.bucket, Key=location.key, Body=f)

    def head_size_bytes(self, *, location: S3ObjectLocation) -> int:
        client = self._get_client()
        r = client.head_object(Bucket=location.bucket, Key=location.key)
        return int(r.get("ContentLength") or 0)

    def iter_range(
        self,
        *,
        location: S3ObjectLocation,
        start: int,
        end: int,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        client = self._get_client()
        range_header = f"bytes={start}-{end}"
        r = client.get_object(Bucket=location.bucket, Key=location.key, Range=range_header)
        body = r["Body"]
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk

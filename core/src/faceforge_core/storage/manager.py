from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from faceforge_core.config import CoreConfig
from faceforge_core.home import FaceForgePaths
from faceforge_core.seaweedfs import s3_endpoint_healthy, s3_endpoint_url_for_config
from faceforge_core.storage.filesystem import FilesystemStorageProvider
from faceforge_core.storage.s3 import S3ObjectLocation, S3StorageProvider


@dataclass(frozen=True)
class UploadResult:
    storage_provider: str
    storage_key: str
    # If present, a stable local path to bytes (e.g. filesystem provider).
    local_path: Path | None
    # If present, a temp path that should be cleaned up after background tasks.
    cleanup_temp_path: Path | None


class StorageManager:
    def __init__(self, *, paths: FaceForgePaths, config: CoreConfig) -> None:
        self._paths = paths
        self._config = config

        self._fs = FilesystemStorageProvider(Path(paths.assets_dir))
        self._fs.ensure_layout()

        self._s3: S3StorageProvider | None = None
        self._s3_health_cached_at: float | None = None
        self._s3_health_cached_ok: bool = False

    @property
    def fs(self) -> FilesystemStorageProvider:
        return self._fs

    def _s3_enabled(self) -> bool:
        return bool(self._config.storage.s3.enabled)

    def s3_configured(self) -> bool:
        if not self._s3_enabled():
            return False

        endpoint = s3_endpoint_url_for_config(self._config)
        if not endpoint:
            return False

        cfg = self._config.storage.s3
        return bool((cfg.access_key or "").strip() and (cfg.secret_key or "").strip())

    def _s3_health(self) -> bool:
        # Cache to avoid probing the port repeatedly under load.
        now = time.time()
        if self._s3_health_cached_at is not None and (now - self._s3_health_cached_at) < 1.0:
            return self._s3_health_cached_ok

        ok = s3_endpoint_healthy(self._config)
        self._s3_health_cached_at = now
        self._s3_health_cached_ok = ok
        return ok

    def s3_available(self) -> bool:
        return self._s3_enabled() and self._s3_health()

    def get_s3_provider(self) -> S3StorageProvider | None:
        if not self.s3_configured():
            return None
        return self._get_s3()

    def get_size_bytes(self, *, storage_provider: str, storage_key: str) -> int:
        if storage_provider == "fs":
            path = self._fs.resolve_path(storage_key)
            return path.stat().st_size
        if storage_provider == "s3":
            s3 = self._get_s3()
            loc = S3ObjectLocation.from_storage_key(storage_key, default_bucket=s3.default_bucket)
            return s3.head_size_bytes(location=loc)
        raise ValueError(f"Unsupported storage provider: {storage_provider}")

    def _get_s3(self) -> S3StorageProvider:
        if self._s3 is not None:
            return self._s3

        cfg = self._config.storage.s3
        endpoint = s3_endpoint_url_for_config(self._config)
        if not endpoint:
            raise RuntimeError("S3 endpoint_url not configured")

        access_key = (cfg.access_key or "").strip()
        secret_key = (cfg.secret_key or "").strip()
        if not access_key or not secret_key:
            raise RuntimeError("S3 access_key/secret_key not configured")

        self._s3 = S3StorageProvider(
            endpoint_url=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            region=cfg.region,
            use_ssl=cfg.use_ssl,
            default_bucket=cfg.bucket,
        )
        return self._s3

    def choose_provider_for_upload(self, *, kind: str, byte_size: int) -> str:
        routing = self._config.storage.routing

        kind_norm = (kind or "").strip().lower() or "file"
        mapped = routing.kind_map.get(kind_norm)
        if mapped:
            return mapped

        threshold = routing.s3_min_size_bytes
        if threshold is not None and byte_size >= threshold:
            return "s3"

        return routing.default_provider

    def store_upload(
        self,
        *,
        temp_path: Path,
        asset_id: str,
        kind: str,
        byte_size: int,
    ) -> UploadResult:
        preferred = self.choose_provider_for_upload(kind=kind, byte_size=byte_size)

        provider = preferred
        if provider == "s3" and not self.s3_available():
            provider = "fs"

        if provider == "s3":
            s3 = self._get_s3()
            key = s3.key_for_asset_id(asset_id)
            loc = S3ObjectLocation(bucket=s3.default_bucket, key=key)
            s3.put_file(temp_path=temp_path, location=loc)
            return UploadResult(
                storage_provider=s3.provider_name,
                storage_key=loc.to_storage_key(),
                local_path=None,
                cleanup_temp_path=temp_path,
            )

        # Default to filesystem.
        storage_key = self._fs.key_for_asset_id(asset_id)
        asset_path = self._fs.finalize_temp_file(temp_path=temp_path, storage_key=storage_key)
        return UploadResult(
            storage_provider=self._fs.provider_name,
            storage_key=storage_key,
            local_path=asset_path,
            cleanup_temp_path=None,
        )


    def store_existing_file(
        self,
        *,
        source_path: Path,
        asset_id: str,
        kind: str,
        byte_size: int,
    ) -> UploadResult:
        """Store an existing file path into the configured backend.

        The source file is not modified.
        """

        preferred = self.choose_provider_for_upload(kind=kind, byte_size=byte_size)

        provider = preferred
        if provider == "s3" and not self.s3_available():
            provider = "fs"

        if provider == "s3":
            s3 = self._get_s3()
            key = s3.key_for_asset_id(asset_id)
            loc = S3ObjectLocation(bucket=s3.default_bucket, key=key)
            s3.put_file_from_path(source_path=source_path, location=loc)
            return UploadResult(
                storage_provider=s3.provider_name,
                storage_key=loc.to_storage_key(),
                local_path=None,
                cleanup_temp_path=None,
            )

        storage_key = self._fs.key_for_asset_id(asset_id)
        asset_path = self._fs.ingest_existing_file(source_path=source_path, storage_key=storage_key)
        return UploadResult(
            storage_provider=self._fs.provider_name,
            storage_key=storage_key,
            local_path=asset_path,
            cleanup_temp_path=None,
        )

    def open_download(
        self,
        *,
        storage_provider: str,
        storage_key: str,
        start: int,
        end: int,
        asset_id: str,
    ) -> tuple[Iterator[bytes], int]:
        """Return (byte iterator, total size bytes)."""

        if storage_provider == "fs":
            path = self._fs.resolve_path(storage_key)
            size = path.stat().st_size

            def _iter_file_range(chunk_size: int = 1024 * 1024):
                with path.open("rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = f.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return _iter_file_range(), size

        if storage_provider == "s3":
            s3 = self._get_s3()
            loc = S3ObjectLocation.from_storage_key(storage_key, default_bucket=s3.default_bucket)
            size = s3.head_size_bytes(location=loc)
            return s3.iter_range(location=loc, start=start, end=end), size

        raise ValueError(f"Unsupported storage provider: {storage_provider}")


def build_storage_manager(*, paths: FaceForgePaths, config: CoreConfig) -> StorageManager:
    return StorageManager(paths=paths, config=config)

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from faceforge_core.config import CoreConfig
from faceforge_core.home import FaceForgePaths


@dataclass(frozen=True)
class SeaweedProcess:
    popen: subprocess.Popen
    started_at: float
    s3_endpoint_url: str


def _is_windows() -> bool:
    return os.name == "nt"


def resolve_weed_executable(paths: FaceForgePaths, config: CoreConfig) -> Path | None:
    tools_dir = Path(paths.tools_dir)

    raw = (config.seaweed.weed_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
        p = p if p.is_absolute() else (tools_dir / p)
        p = p.resolve()
        return p if p.exists() else None

    candidates: list[Path] = []
    if _is_windows():
        candidates.extend(
            [
                tools_dir / "weed.exe",
                tools_dir / "seaweedfs" / "weed.exe",
                tools_dir / "seaweed" / "weed.exe",
            ]
        )
    else:
        candidates.extend(
            [
                tools_dir / "weed",
                tools_dir / "seaweedfs" / "weed",
                tools_dir / "seaweed" / "weed",
            ]
        )

    for c in candidates:
        if c.exists():
            return c

    return None


def resolve_seaweed_data_dir(paths: FaceForgePaths, config: CoreConfig) -> Path:
    raw = (config.seaweed.data_dir or "").strip()
    if not raw:
        return (Path(paths.s3_dir) / "seaweedfs").resolve()

    p = Path(raw).expanduser()
    p = p if p.is_absolute() else (Path(paths.home) / p)
    return p.resolve()


def resolve_seaweed_s3_port(config: CoreConfig) -> int:
    if config.seaweed.s3_port is not None:
        return config.seaweed.s3_port
    if config.network.seaweed_s3_port is not None:
        return config.network.seaweed_s3_port
    return 8333


def _endpoint_url(config: CoreConfig) -> str | None:
    # Prefer explicit endpoint.
    explicit = (config.storage.s3.endpoint_url or "").strip()
    if explicit:
        return explicit

    port = config.network.seaweed_s3_port
    if port is None:
        return None

    scheme = "https" if config.storage.s3.use_ssl else "http"
    return f"{scheme}://{config.network.bind_host}:{port}"


def s3_endpoint_url_for_config(config: CoreConfig) -> str | None:
    return _endpoint_url(config)


def tcp_port_open(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def s3_endpoint_healthy(config: CoreConfig, *, timeout_s: float = 0.2) -> bool:
    url = _endpoint_url(config)
    if not url:
        return False

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    return tcp_port_open(host, port, timeout_s=timeout_s)


def build_weed_server_args(paths: FaceForgePaths, config: CoreConfig) -> list[str]:
    data_dir = resolve_seaweed_data_dir(paths, config)
    data_dir.mkdir(parents=True, exist_ok=True)

    s3_port = resolve_seaweed_s3_port(config)

    # `weed server` runs master+volume+filer and can expose an S3 API with -s3.
    return [
        "server",
        f"-ip={config.seaweed.ip}",
        f"-dir={str(data_dir)}",
        f"-master.port={config.seaweed.master_port}",
        f"-volume.port={config.seaweed.volume_port}",
        f"-filer.port={config.seaweed.filer_port}",
        "-s3",
        f"-s3.port={s3_port}",
    ]


def start_managed_seaweed(paths: FaceForgePaths, config: CoreConfig) -> SeaweedProcess | None:
    if not config.seaweed.enabled:
        return None

    weed = resolve_weed_executable(paths, config)
    if weed is None:
        return None

    s3_port = resolve_seaweed_s3_port(config)

    endpoint = s3_endpoint_url_for_config(
        config.model_copy(
            update={"network": config.network.model_copy(update={"seaweed_s3_port": s3_port})}
        )
    )
    if endpoint is None:
        scheme = "https" if config.storage.s3.use_ssl else "http"
        endpoint = f"{scheme}://{config.seaweed.ip}:{s3_port}"

    args = [str(weed), *build_weed_server_args(paths, config)]

    popen = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _is_windows() else 0,
    )

    started_at = time.time()
    # Best-effort: wait briefly for the S3 port to come up.
    for _ in range(30):
        cfg_with_port = config.model_copy(
            update={"network": config.network.model_copy(update={"seaweed_s3_port": s3_port})}
        )
        if s3_endpoint_healthy(cfg_with_port):
            break
        time.sleep(0.1)

    return SeaweedProcess(popen=popen, started_at=started_at, s3_endpoint_url=endpoint)


def stop_managed_seaweed(proc: SeaweedProcess | None) -> None:
    if proc is None:
        return

    try:
        proc.popen.terminate()
        proc.popen.wait(timeout=3)
    except Exception:
        try:
            proc.popen.kill()
        except Exception:
            pass

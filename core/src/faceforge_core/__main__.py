from __future__ import annotations

import os

import uvicorn

from faceforge_core.app import create_app
from faceforge_core.config import load_core_config, resolve_configured_paths
from faceforge_core.home import ensure_faceforge_layout, resolve_faceforge_home
from faceforge_core.ports import read_ports_file


def main() -> None:
    home = resolve_faceforge_home()
    paths = ensure_faceforge_layout(home)
    config = load_core_config(paths)
    paths = resolve_configured_paths(paths, config)

    ports = read_ports_file(paths, allow_legacy_runtime_dir=True)

    host = os.environ.get("FACEFORGE_BIND") or config.network.bind_host

    env_port = os.environ.get("FACEFORGE_PORT")
    if env_port:
        port = int(env_port)
    elif ports and ports.core_port is not None:
        port = ports.core_port
    else:
        # Keep the scaffold's existing default unless config explicitly changes it.
        port = config.network.core_port

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()

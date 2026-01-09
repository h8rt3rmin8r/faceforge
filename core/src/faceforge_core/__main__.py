from __future__ import annotations

import os

import uvicorn

from faceforge_core.app import create_app


def main() -> None:
    host = os.environ.get("FACEFORGE_BIND", "127.0.0.1")
    port = int(os.environ.get("FACEFORGE_PORT", "8787"))

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()

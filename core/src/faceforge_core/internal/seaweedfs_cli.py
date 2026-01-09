from __future__ import annotations

import argparse
import time
from pathlib import Path

from faceforge_core.config import load_core_config, resolve_configured_paths
from faceforge_core.home import ensure_faceforge_layout
from faceforge_core.seaweedfs import (
    resolve_seaweed_data_dir,
    resolve_weed_executable,
    s3_endpoint_healthy,
    s3_endpoint_url_for_config,
    start_managed_seaweed,
    stop_managed_seaweed,
)


def main() -> int:
    p = argparse.ArgumentParser(description="FaceForge Core SeaweedFS helper (dev/testing)")
    p.add_argument("--home", required=True, help="FACEFORGE_HOME path")
    p.add_argument("--health", action="store_true", help="Check S3 endpoint health and exit")
    p.add_argument("--run", action="store_true", help="Run managed SeaweedFS until Ctrl+C")

    args = p.parse_args()

    paths = ensure_faceforge_layout(Path(args.home).expanduser().resolve())
    cfg = load_core_config(paths)
    paths = resolve_configured_paths(paths, cfg)

    if args.health:
        endpoint = s3_endpoint_url_for_config(cfg) or "(not configured)"
        ok = s3_endpoint_healthy(cfg)
        print(f"endpoint={endpoint}")
        print(f"healthy={ok}")
        return 0 if ok else 1

    if args.run:
        weed = resolve_weed_executable(paths, cfg)
        if weed is None:
            print(
                "SeaweedFS binary not found. Expected under FACEFORGE_HOME/tools "
                "(or configure seaweed.weed_path)."
            )
            return 2

        data_dir = resolve_seaweed_data_dir(paths, cfg)
        endpoint = s3_endpoint_url_for_config(cfg) or "(derived at runtime)"
        print(f"weed={weed}")
        print(f"data_dir={data_dir}")
        print(f"s3_endpoint={endpoint}")

        proc = start_managed_seaweed(paths, cfg)
        if proc is None:
            print("SeaweedFS did not start (is seaweed.enabled=true in config?)")
            return 3

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_managed_seaweed(proc)

        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

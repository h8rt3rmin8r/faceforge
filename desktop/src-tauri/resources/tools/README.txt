This directory contains third-party tools bundled with FaceForge.
- ExifTool: https://exiftool.org/
- SeaweedFS: https://github.com/seaweedfs/seaweedfs

Note:
- This repo intentionally does not check in the real SeaweedFS binary.
- `weed.exe` in this folder may be a placeholder in source checkouts.
- Release builds should run `scripts/ensure-seaweedfs.ps1` (and `scripts/build-desktop.ps1` already does) to download the official Windows x64 `weed.exe` into this folder before packaging.

Please refer to the respective licenses in this directory.
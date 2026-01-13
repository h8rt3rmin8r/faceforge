from __future__ import annotations

from pathlib import Path

from faceforge_core.home import ensure_faceforge_layout, resolve_faceforge_home


def test_resolve_faceforge_home_from_env(tmp_path: Path) -> None:
    home = resolve_faceforge_home({"FACEFORGE_HOME": str(tmp_path)})
    assert home == tmp_path.resolve()


def test_ensure_faceforge_layout_creates_required_dirs(tmp_path: Path) -> None:
    paths = ensure_faceforge_layout(tmp_path)

    assert paths.home.exists()
    assert paths.db_dir.is_dir()
    assert paths.s3_dir.is_dir()
    assert paths.assets_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.tools_dir.is_dir()
    assert paths.plugins_dir.is_dir()
    assert paths.tmp_dir.is_dir()

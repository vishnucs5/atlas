"""Hatchling custom build hook for ATLAS CLI self-contained distribution."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class AtlasCliBuildHook(BuildHookInterface):
    """Stages internal ATLAS monorepo packages into the CLI distribution."""

    PLUGIN_NAME = "custom"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._staged_dirs: list[Path] = []

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Copy monorepo packages into src/ before packaging if building from repo."""
        cli_root = Path(self.root).resolve()
        repo_root = cli_root.parents[1]
        packages_dir = repo_root / "packages"

        if not packages_dir.is_dir():
            # Already inside an unpacked sdist where modules exist in src/
            return

        src_dir = cli_root / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        for pkg_path in sorted(packages_dir.iterdir()):
            pkg_src = pkg_path / "src"
            if not pkg_src.is_dir():
                continue
            for mod_path in pkg_src.iterdir():
                if mod_path.is_dir() and mod_path.name.startswith("atlas_"):
                    dest = src_dir / mod_path.name
                    if not dest.exists():
                        shutil.copytree(mod_path, dest)
                        self._staged_dirs.append(dest)

    def finalize(self, version: str, build_data: dict[str, Any], artifact: str) -> None:
        """Clean up staged packages from src/ to keep working tree clean."""
        cli_root = Path(self.root).resolve()
        repo_root = cli_root.parents[1]
        packages_dir = repo_root / "packages"

        # Only clean up if we are in the monorepo source tree
        if packages_dir.is_dir():
            for staged in self._staged_dirs:
                if staged.is_dir():
                    shutil.rmtree(staged, ignore_errors=True)
            self._staged_dirs.clear()

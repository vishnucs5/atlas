"""Safe repository exploration, discovery, and metadata extraction."""

import fnmatch
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_core.contracts.coding import RepositoryFileMetadata

DEFAULT_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".cache",
    "dist",
    "build",
    ".egg-info",
    ".next",
    ".nuxt",
}

DEFAULT_SENSITIVE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.pkcs12",
    "*id_rsa*",
    "*id_ecdsa*",
    "*id_ed25519*",
    "*credentials*.json",
    "*service_account*.json",
    "secrets.*",
]


class RepositoryExplorer:
    """Safe explorer for navigating and inspecting code repositories."""

    def __init__(
        self,
        repo_root: str | Path,
        max_file_size_bytes: int = 10 * 1024 * 1024,  # 10 MB limit
        max_depth: int = 20,
        sensitive_patterns: list[str] | None = None,
        custom_ignored_dirs: set[str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        if not self.repo_root.is_dir():
            msg = f"Repository root does not exist or is not a directory: {self.repo_root}"
            raise ValueError(msg)

        self.max_file_size_bytes = max_file_size_bytes
        self.max_depth = max_depth
        self.sensitive_patterns = sensitive_patterns or DEFAULT_SENSITIVE_PATTERNS
        self.ignored_dirs = set(DEFAULT_IGNORED_DIRS)
        if custom_ignored_dirs:
            self.ignored_dirs.update(custom_ignored_dirs)

        self.gitignore_patterns: list[str] = self._load_gitignore()

    def _load_gitignore(self) -> list[str]:
        """Load ignore patterns from root .gitignore if present."""
        gitignore_path = self.repo_root / ".gitignore"
        patterns: list[str] = []
        if gitignore_path.is_file():
            try:
                for line in gitignore_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        patterns.append(stripped)
            except OSError:
                pass
        return patterns

    def resolve_safe_path(self, rel_or_abs_path: str | Path) -> Path:
        """Resolve a path and strictly verify it resides within repository boundaries.

        Raises:
            ValueError: If the resolved path attempts directory traversal outside repo_root.
        """
        raw_path = Path(rel_or_abs_path)
        if raw_path.is_absolute():
            resolved = raw_path.resolve()
        else:
            resolved = (self.repo_root / raw_path).resolve()

        # Boundary containment check
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as err:
            msg = f"Path traversal violation: '{rel_or_abs_path}' resolves to '{resolved}', outside workspace '{self.repo_root}'"
            raise ValueError(msg) from err

        return resolved

    def is_sensitive(self, rel_path: str) -> bool:
        """Check if relative path matches any sensitive file pattern."""
        basename = os.path.basename(rel_path)
        for pattern in self.sensitive_patterns:
            if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """Check whether path is ignored by directory rules or .gitignore."""
        parts = rel_path.replace("\\", "/").strip("/").split("/")
        for part in parts:
            if part in self.ignored_dirs:
                return True

        basename = os.path.basename(rel_path)
        for pattern in self.gitignore_patterns:
            # Simple gitignore matching
            clean_pat = pattern.rstrip("/")
            if fnmatch.fnmatch(basename, clean_pat) or fnmatch.fnmatch(rel_path, clean_pat):
                return True
            if pattern.endswith("/") and is_dir and fnmatch.fnmatch(basename, clean_pat):
                return True
        return False

    @staticmethod
    def is_binary_content(sample_bytes: bytes) -> bool:
        """Heuristic check for binary content based on null byte presence."""
        return b"\x00" in sample_bytes

    def get_metadata(self, rel_or_abs_path: str | Path) -> RepositoryFileMetadata:
        """Extract metadata and SHA-256 hash for a specific file."""
        safe_path = self.resolve_safe_path(rel_or_abs_path)
        rel_str = str(safe_path.relative_to(self.repo_root)).replace("\\", "/")

        if not safe_path.exists():
            msg = f"File does not exist: {rel_str}"
            raise FileNotFoundError(msg)

        is_symlink = safe_path.is_symlink()
        stat = safe_path.stat()
        size_bytes = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

        is_bin = False
        sha256_hex = ""

        if safe_path.is_file() and not self.is_sensitive(rel_str):
            # Check binary sample
            try:
                with safe_path.open("rb") as f:
                    sample = f.read(8192)
                    is_bin = self.is_binary_content(sample)
                    if not is_bin and size_bytes <= self.max_file_size_bytes:
                        hasher = hashlib.sha256()
                        hasher.update(sample)
                        while chunk := f.read(65536):
                            hasher.update(chunk)
                        sha256_hex = hasher.hexdigest()
            except OSError:
                pass

        return RepositoryFileMetadata(
            rel_path=rel_str,
            abs_path=str(safe_path),
            size_bytes=size_bytes,
            is_binary=is_bin,
            is_symlink=is_symlink,
            sha256=sha256_hex,
            last_modified=mtime,
        )

    def discover_files(
        self,
        subpath: str = "",
        include_binary: bool = False,
        include_sensitive: bool = False,
        max_count: int = 1000,
    ) -> list[RepositoryFileMetadata]:
        """Discover files within a workspace subpath, applying boundary, size, and ignore gates."""
        base = self.resolve_safe_path(subpath)
        results: list[RepositoryFileMetadata] = []

        for root, dirs, files in os.walk(base, followlinks=False):
            rel_root = str(Path(root).relative_to(self.repo_root)).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            # Calculate depth
            depth = len(rel_root.split("/")) if rel_root else 0
            if depth >= self.max_depth:
                dirs.clear()
                continue

            # Filter out ignored directories in-place
            dirs[:] = [
                d for d in dirs if not self.is_ignored(f"{rel_root}/{d}".strip("/"), is_dir=True)
            ]

            for fname in files:
                file_rel = f"{rel_root}/{fname}".strip("/")
                if self.is_ignored(file_rel, is_dir=False):
                    continue
                if not include_sensitive and self.is_sensitive(file_rel):
                    continue

                full_path = Path(root) / fname
                try:
                    meta = self.get_metadata(full_path)
                    if not include_binary and meta.is_binary:
                        continue
                    results.append(meta)
                    if len(results) >= max_count:
                        return sorted(results, key=lambda m: m.rel_path)
                except (OSError, ValueError):
                    continue

        return sorted(results, key=lambda m: m.rel_path)

    def explore_tree(self, subpath: str = "", max_depth: int = 3) -> dict[str, Any]:
        """Build a hierarchical directory tree summary up to max_depth."""
        base = self.resolve_safe_path(subpath)

        def _build_node(current_path: Path, current_depth: int) -> dict[str, Any]:
            rel_path = str(current_path.relative_to(self.repo_root)).replace("\\", "/")
            if rel_path == ".":
                rel_path = ""

            if current_path.is_file():
                return {
                    "name": current_path.name,
                    "path": rel_path,
                    "type": "file",
                    "size": current_path.stat().st_size,
                }

            node: dict[str, Any] = {
                "name": current_path.name or self.repo_root.name,
                "path": rel_path,
                "type": "directory",
                "children": [],
            }

            if current_depth >= max_depth:
                return node

            try:
                for entry in sorted(current_path.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
                    rel_child = str(entry.relative_to(self.repo_root)).replace("\\", "/")
                    if entry.is_dir() and self.is_ignored(rel_child, is_dir=True):
                        continue
                    if entry.is_file() and (
                        self.is_ignored(rel_child, is_dir=False) or self.is_sensitive(rel_child)
                    ):
                        continue
                    node["children"].append(_build_node(entry, current_depth + 1))
            except OSError:
                pass

            return node

        return _build_node(base, 0)

    def discover_project_manifests(self) -> dict[str, str]:
        """Discover standard software engineering project manifests."""
        manifest_files = {
            "python_pyproject": "pyproject.toml",
            "python_setup": "setup.py",
            "python_requirements": "requirements.txt",
            "javascript_package": "package.json",
            "rust_cargo": "Cargo.toml",
            "go_mod": "go.mod",
            "java_maven": "pom.xml",
            "java_gradle": "build.gradle",
            "dockerfile": "Dockerfile",
            "docker_compose": "docker-compose.yml",
        }
        found: dict[str, str] = {}
        for key, fname in manifest_files.items():
            candidate = self.repo_root / fname
            if candidate.is_file():
                found[key] = fname
        return found

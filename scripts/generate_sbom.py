"""Generate CycloneDX v1.5 Software Bill of Materials (SBOM) for ATLAS CLI.

Extracts verifiable license, description, hash, and dependency provenance
directly from uv.lock, installed package metadata, and workspace pyproject.toml
manifests. Separates runtime from development dependencies and prevents
internal package PURL collisions with public PyPI namespaces.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

# Known SPDX mapping for third-party packages whose metadata uses free-text names
KNOWN_PACKAGE_LICENSES: dict[str, tuple[str, str]] = {
    "atlas-monorepo": ("Apache-2.0", "ATLAS - Autonomous Task & Lifecycle Automation System"),
    "colorama": ("BSD-3-Clause", "Cross-platform colored terminal text"),
    "embedded-postgres": ("PostgreSQL", "Embedded PostgreSQL database engine for testing"),
    "fasteners": ("Apache-2.0", "Cross-platform locks for threads and processes"),
    "playwright": (
        "Apache-2.0",
        "Fast and reliable end-to-end testing and automation for modern web apps",
    ),
    "psycopg": ("LGPL-3.0-only", "PostgreSQL database adapter for Python"),
    "psycopg-binary": ("LGPL-3.0-only", "PostgreSQL database adapter for Python (binary wheel)"),
    "psycopg-pool": ("LGPL-3.0-only", "Connection pool for psycopg"),
}

DEV_ONLY_PACKAGES = {
    "bandit",
    "coverage",
    "embedded-postgres",
    "iniconfig",
    "mypy",
    "mypy-extensions",
    "pip-audit",
    "pluggy",
    "pytest",
    "pytest-asyncio",
    "ruff",
}


def _hash_directory(directory: Path) -> str:
    """Compute deterministic SHA-256 digest of a source tree."""
    hasher = hashlib.sha256()
    for p in sorted(directory.rglob("*")):
        if p.is_file() and not p.name.endswith(".pyc") and "__pycache__" not in p.parts:
            rel = p.relative_to(directory).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(p.read_bytes())
    return hasher.hexdigest()


def load_internal_package_metadata(repo_root: Path) -> dict[str, dict[str, str]]:
    """Scan workspace packages and extract declared metadata and content hashes."""
    meta: dict[str, dict[str, str]] = {}

    # Packages
    packages_dir = repo_root / "packages"
    if packages_dir.is_dir():
        for p in packages_dir.iterdir():
            pyproj = p / "pyproject.toml"
            if pyproj.is_file():
                with open(pyproj, "rb") as f:
                    data = tomllib.load(f).get("project", {})
                    name = data.get("name")
                    src_dir = p / "src"
                    tree_hash = _hash_directory(src_dir) if src_dir.is_dir() else ""
                    meta[name] = {
                        "version": data.get("version", "0.1.0"),
                        "license": "Apache-2.0",
                        "description": data.get("description", f"ATLAS internal package {name}"),
                        "sha256": tree_hash,
                    }

    # Apps
    apps_dir = repo_root / "apps"
    if apps_dir.is_dir():
        for app in apps_dir.iterdir():
            pyproj = app / "pyproject.toml"
            if pyproj.is_file():
                with open(pyproj, "rb") as f:
                    data = tomllib.load(f).get("project", {})
                    name = data.get("name")
                    src_dir = app / "src"
                    tree_hash = _hash_directory(src_dir) if src_dir.is_dir() else ""
                    meta[name] = {
                        "version": data.get("version", "0.16.8"),
                        "license": "Apache-2.0",
                        "description": data.get("description", f"ATLAS application {name}"),
                        "sha256": tree_hash,
                    }

    return meta


def generate_sbom(
    lockfile_path: Path = Path("uv.lock"),
    output_path: Path = Path("dist/atlas-cli-sbom.json"),
    repo_root: Path = Path("."),
) -> dict:
    """Generate CycloneDX v1.5 JSON SBOM from uv.lock and package metadata."""
    if not lockfile_path.is_file():
        raise FileNotFoundError(f"Lockfile {lockfile_path} not found")

    with open(lockfile_path, "rb") as f:
        lock_data = tomllib.load(f)

    internal_metadata = load_internal_package_metadata(repo_root)
    packages = lock_data.get("package", [])
    components = []
    dependencies_graph = []

    for pkg in packages:
        name = pkg.get("name")
        version = pkg.get("version", "unknown")
        is_internal = name in internal_metadata or name.startswith("atlas-")
        is_dev = name in DEV_ONLY_PACKAGES

        # License & description retrieval
        license_id = None
        description = None

        if is_internal and name in internal_metadata:
            license_id = internal_metadata[name]["license"]
            description = internal_metadata[name]["description"]
            tree_hash = internal_metadata[name]["sha256"]
        elif name == "atlas-monorepo":
            license_id, description = KNOWN_PACKAGE_LICENSES[name]
            tree_hash = hashlib.sha256((repo_root / "pyproject.toml").read_bytes()).hexdigest()
        elif name in KNOWN_PACKAGE_LICENSES:
            license_id, description = KNOWN_PACKAGE_LICENSES[name]
            tree_hash = None
        else:
            try:
                dist_meta = importlib.metadata.metadata(name)
                license_id = dist_meta.get("License-Expression") or dist_meta.get("License")
                description = dist_meta.get("Summary")
            except Exception:
                license_id = None
                description = None
            tree_hash = None

        # Distinct PURL namespace for internal packages to avoid PyPI collisions
        if is_internal:
            bom_ref = f"pkg:generic/atlas/{name}@{version}"
            purl = f"pkg:generic/atlas/{name}@{version}"
        else:
            bom_ref = f"pkg:pypi/{name}@{version}"
            purl = f"pkg:pypi/{name}@{version}"

        # Scope: separate required runtime vs excluded development packages
        scope = "excluded" if is_dev else "required"

        comp: dict[str, Any] = {
            "type": "application" if name == "atlas-cli" else "library",
            "bom-ref": bom_ref,
            "name": name,
            "version": version,
            "description": description or f"Python package {name}",
            "scope": scope,
            "purl": purl,
        }

        if is_internal:
            comp["supplier"] = {"name": "ATLAS Engineering"}

        # Licenses
        if license_id:
            comp["licenses"] = [{"license": {"id": license_id}}]

        # Hashes
        hashes: list[dict[str, str]] = []
        wheels = pkg.get("wheels", [])
        sdist = pkg.get("sdist", {})

        for w in wheels:
            if "hash" in w:
                h_algo, h_val = w["hash"].split(":") if ":" in w["hash"] else ("sha256", w["hash"])
                hashes.append({"alg": h_algo.upper(), "content": h_val})
        if "hash" in sdist:
            h_algo, h_val = (
                sdist["hash"].split(":") if ":" in sdist["hash"] else ("sha256", sdist["hash"])
            )
            hashes.append({"alg": h_algo.upper(), "content": h_val})

        if not hashes and tree_hash:
            hashes.append({"alg": "SHA-256", "content": tree_hash})

        if hashes:
            comp["hashes"] = hashes

        components.append(comp)

        # Build dependency relationship graph
        pkg_deps = pkg.get("dependencies", [])
        dep_refs = []
        for dep in pkg_deps:
            dep_name = dep.get("name") if isinstance(dep, dict) else str(dep)
            if dep_name.startswith("atlas-"):
                dep_refs.append(f"pkg:generic/atlas/{dep_name}")
            else:
                dep_refs.append(f"pkg:pypi/{dep_name}")
        dependencies_graph.append(
            {
                "ref": bom_ref,
                "dependsOn": dep_refs,
            }
        )

    sbom = {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tools": [
                {
                    "vendor": "ATLAS Engineering",
                    "name": "atlas-sbom-generator",
                    "version": "1.1.0",
                }
            ],
            "component": {
                "type": "application",
                "bom-ref": "pkg:pypi/atlas-cli@0.16.8",
                "name": "atlas-cli",
                "version": "0.16.8",
                "description": "ATLAS CLI — Autonomous Developer Environment & Enterprise Coding Agent",
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            },
        },
        "components": components,
        "dependencies": dependencies_graph,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")

    # Also mirror to reports/release/
    reports_target = repo_root / "reports" / "release" / "atlas-cli-sbom.json"
    if reports_target.parent.is_dir():
        reports_target.write_text(json.dumps(sbom, indent=2), encoding="utf-8")

    print(f"Generated compliant CycloneDX SBOM at {output_path} with {len(components)} components.")
    return sbom


def generate_checksums(
    dist_dir: Path = Path("dist"),
    output_file: Path = Path("dist/SHA256SUMS.txt"),
    repo_root: Path = Path("."),
) -> None:
    """Generate SHA256 checksums for all release artifacts in dist."""
    lines = []
    for file_path in sorted(dist_dir.iterdir()):
        if (
            file_path.is_file()
            and file_path.name != "SHA256SUMS.txt"
            and file_path.name != ".gitignore"
        ):
            sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
            lines.append(f"{sha256}  {file_path.name}")

    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Also mirror to reports/release/
    reports_target = repo_root / "reports" / "release" / "SHA256SUMS.txt"
    if reports_target.parent.is_dir():
        reports_target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Generated checksums at {output_file}:\n" + "\n".join(lines))


if __name__ == "__main__":
    generate_sbom()
    generate_checksums()

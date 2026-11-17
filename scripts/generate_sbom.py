"""Generate CycloneDX v1.5 Software Bill of Materials (SBOM) for ATLAS CLI."""

from __future__ import annotations

import hashlib
import json
import time
import tomllib
import uuid
from pathlib import Path


def generate_sbom(
    lockfile_path: Path = Path("uv.lock"), output_path: Path = Path("dist/atlas-cli-sbom.json")
) -> dict:
    """Generate CycloneDX JSON SBOM from uv.lock."""
    if not lockfile_path.is_file():
        raise FileNotFoundError(f"Lockfile {lockfile_path} not found")

    with open(lockfile_path, "rb") as f:
        lock_data = tomllib.load(f)

    packages = lock_data.get("package", [])
    components = []

    for pkg in packages:
        name = pkg.get("name")
        version = pkg.get("version", "unknown")

        # Calculate component attributes
        comp = {
            "type": "library",
            "bom-ref": f"pkg:pypi/{name}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "scope": "required",
        }

        # Check for wheel/sdist hash in wheels
        wheels = pkg.get("wheels", [])
        sdist = pkg.get("sdist", {})
        hashes = []
        for w in wheels:
            if "hash" in w:
                h_algo, h_val = w["hash"].split(":") if ":" in w["hash"] else ("sha256", w["hash"])
                hashes.append({"alg": h_algo.upper(), "content": h_val})
        if "hash" in sdist:
            h_algo, h_val = (
                sdist["hash"].split(":") if ":" in sdist["hash"] else ("sha256", sdist["hash"])
            )
            hashes.append({"alg": h_algo.upper(), "content": h_val})

        if hashes:
            comp["hashes"] = hashes

        components.append(comp)

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
                    "version": "1.0.0",
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
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
    print(f"Generated SBOM at {output_path} with {len(components)} components.")
    return sbom


def generate_checksums(
    dist_dir: Path = Path("dist"), output_file: Path = Path("dist/SHA256SUMS.txt")
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
    print(f"Generated checksums at {output_file}:\n" + "\n".join(lines))


if __name__ == "__main__":
    generate_sbom()
    generate_checksums()

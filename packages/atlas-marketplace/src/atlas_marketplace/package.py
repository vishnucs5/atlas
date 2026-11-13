"""Workflow Package Packaging, Validation, Integrity Hashing, and Signing."""

import hashlib
import hmac
import io
import json
import tarfile
from typing import Any

from atlas_marketplace.models import (
    PackageManifest,
    WorkflowGraphDefinition,
    WorkflowPackage,
)


class PackageValidationError(Exception):
    """Raised when package manifest or schema validation fails."""


class PackageIntegrityError(Exception):
    """Raised when package file checksum does not match declared checksums."""


class PackageSignatureError(Exception):
    """Raised when package signature verification fails or publisher is untrusted."""


def calculate_sha256(data: bytes) -> str:
    """Compute hex-encoded SHA-256 digest of binary content."""
    return hashlib.sha256(data).hexdigest()


def sign_payload(data: bytes, secret_or_key: str) -> str:
    """Generate deterministic HMAC-SHA256 signature for package verification."""
    return hmac.new(
        key=secret_or_key.encode("utf-8"),
        msg=data,
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_payload_signature(data: bytes, signature: str, secret_or_key: str) -> bool:
    """Constant-time verification of HMAC-SHA256 signature."""
    expected = sign_payload(data, secret_or_key)
    return hmac.compare_digest(expected, signature)


def validate_workflow_dag_cycles(graph: WorkflowGraphDefinition) -> None:
    """Deterministically check workflow DAG for cyclic dependencies using Kahn's algorithm."""
    nodes = {node.node_id: node for node in graph.nodes}
    in_degree = dict.fromkeys(nodes, 0)
    adjacency: dict[str, list[str]] = {nid: [] for nid in nodes}

    for nid, node in nodes.items():
        for dep in node.dependencies:
            if dep not in nodes:
                raise PackageValidationError(
                    f"Workflow node '{nid}' depends on non-existent node '{dep}'."
                )
            adjacency[dep].append(nid)
            in_degree[nid] += 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited_count = 0

    while queue:
        curr = queue.pop(0)
        visited_count += 1
        for neighbor in adjacency[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(nodes):
        raise PackageValidationError(
            f"Workflow graph '{graph.graph_id}' contains cyclic dependencies."
        )


def build_package_archive(
    manifest: PackageManifest,
    workflow: WorkflowGraphDefinition | None = None,
    extra_files: dict[str, bytes] | None = None,
    signing_key: str | None = None,
) -> bytes:
    """Assemble package contents, compute checksums, generate signature, and bundle into tar.gz archive."""
    files_to_pack: dict[str, bytes] = {}

    # 1. Manifest
    manifest_bytes = manifest.model_dump_json(indent=2).encode("utf-8")
    files_to_pack["manifest.json"] = manifest_bytes

    # 2. Workflow (if present)
    if workflow:
        validate_workflow_dag_cycles(workflow)
        wf_bytes = workflow.model_dump_json(indent=2).encode("utf-8")
        files_to_pack["workflow.json"] = wf_bytes

    # 3. Extra files (e.g. skill.py, README.md)
    if extra_files:
        for fname, fbytes in extra_files.items():
            files_to_pack[fname] = fbytes

    # 4. Checksums
    checksums: dict[str, str] = {
        fname: calculate_sha256(fbytes) for fname, fbytes in files_to_pack.items()
    }
    checksums_bytes = json.dumps(checksums, indent=2, sort_keys=True).encode("utf-8")
    files_to_pack["checksums.json"] = checksums_bytes

    # 5. Detached signature of checksums
    key = signing_key or manifest.publisher.public_key
    sig = sign_payload(checksums_bytes, key)
    files_to_pack["signature.sig"] = sig.encode("utf-8")

    # 6. Build in-memory tar.gz
    archive_buf = io.BytesIO()
    with tarfile.open(fileobj=archive_buf, mode="w:gz") as tar:
        for fname, fbytes in files_to_pack.items():
            tarinfo = tarfile.TarInfo(name=fname)
            tarinfo.size = len(fbytes)
            tar.addfile(tarinfo, io.BytesIO(fbytes))

    return archive_buf.getvalue()


def unpack_and_validate_package(
    archive_bytes: bytes,
    signing_key: str | None = None,
    revoked_publishers: set[str] | None = None,
) -> WorkflowPackage:
    """Unpack .awp archive, verify checksums, validate signature, and return validated WorkflowPackage."""
    files: dict[str, bytes] = {}
    archive_buf = io.BytesIO(archive_bytes)

    try:
        with tarfile.open(fileobj=archive_buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                # Path traversal defense: reject absolute or directory-escaping file paths
                if member.name.startswith("/") or ".." in member.name:
                    raise PackageValidationError(
                        f"Malicious archive member path detected: '{member.name}'."
                    )
                f = tar.extractfile(member)
                if f is not None:
                    files[member.name] = f.read()
    except Exception as exc:
        raise PackageValidationError(f"Corrupt or invalid package archive: {exc}") from exc

    # Required files
    if "manifest.json" not in files:
        raise PackageValidationError("Package archive missing required 'manifest.json'.")
    if "checksums.json" not in files:
        raise PackageValidationError("Package archive missing required 'checksums.json'.")
    if "signature.sig" not in files:
        raise PackageValidationError("Package archive missing required 'signature.sig'.")

    # 1. Verify checksums
    try:
        checksums: dict[str, str] = json.loads(files["checksums.json"].decode("utf-8"))
    except Exception as exc:
        raise PackageIntegrityError(f"Corrupted checksums.json: {exc}") from exc

    for fname, expected_hash in checksums.items():
        if fname not in files:
            raise PackageIntegrityError(f"File '{fname}' listed in checksums.json is missing.")
        actual_hash = calculate_sha256(files[fname])
        if actual_hash != expected_hash:
            raise PackageIntegrityError(
                f"File '{fname}' checksum mismatch: expected {expected_hash}, got {actual_hash}."
            )

    # 2. Parse and validate manifest
    try:
        manifest_data: dict[str, Any] = json.loads(files["manifest.json"].decode("utf-8"))
        manifest = PackageManifest.model_validate(manifest_data)
    except Exception as exc:
        raise PackageValidationError(f"Invalid package manifest: {exc}") from exc

    # Check revoked publishers
    if revoked_publishers and manifest.publisher.publisher_id in revoked_publishers:
        raise PackageSignatureError(
            f"Publisher '{manifest.publisher.publisher_id}' has been revoked. Package cannot be verified."
        )

    # 3. Verify cryptographic signature
    sig = files["signature.sig"].decode("utf-8").strip()
    key = signing_key or manifest.publisher.public_key
    if not verify_payload_signature(files["checksums.json"], sig, key):
        raise PackageSignatureError(
            f"Invalid package signature for publisher '{manifest.publisher.publisher_id}'."
        )

    # 4. Parse workflow if present
    workflow: WorkflowGraphDefinition | None = None
    if "workflow.json" in files:
        try:
            wf_data = json.loads(files["workflow.json"].decode("utf-8"))
            workflow = WorkflowGraphDefinition.model_validate(wf_data)
            validate_workflow_dag_cycles(workflow)
        except Exception as exc:
            raise PackageValidationError(f"Invalid workflow graph definition: {exc}") from exc

    return WorkflowPackage(
        manifest=manifest,
        workflow=workflow,
        checksums=checksums,
        signature=sig,
        archive_bytes=archive_bytes,
    )

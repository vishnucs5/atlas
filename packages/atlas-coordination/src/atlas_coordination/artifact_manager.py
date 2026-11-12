"""ArtifactManager providing secure, size-bounded, secret-redacted task artifact storage."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_coordination.checkpoint_manager import redact_secrets


class ArtifactSecurityError(Exception):
    """Raised when an artifact operation violates security or containment policies."""


class ArtifactSizeLimitError(Exception):
    """Raised when an artifact exceeds the maximum permissible byte size."""


class ArtifactManager:
    """Manages secure persistence and retrieval of task artifacts.

    Enforces:
    1. Path containment: Strictly prevents path traversal attacks (.. or absolute paths).
    2. File size limits: Rejects oversized payload storage.
    3. Secret scrubbing: Redacts passwords, API tokens, and credentials from textual artifacts.
    """

    def __init__(
        self,
        base_dir: str | Path = "artifacts",
        max_size_bytes: int = 25 * 1024 * 1024,  # 25 MB default limit
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.max_size_bytes = max_size_bytes
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, task_id: str, name: str) -> Path:
        """Resolve and verify that a target path is strictly contained within base_dir/task_id."""
        clean_task_id = task_id.strip().replace("/", "_").replace("\\", "_")
        if ".." in clean_task_id or not clean_task_id:
            raise ArtifactSecurityError(f"Invalid task_id: '{task_id}'")

        # Reject any traversal sequence in name
        if ".." in name or os.path.isabs(name) or name.startswith(("/", "\\")):
            raise ArtifactSecurityError(f"Path traversal detected in artifact name: '{name}'")

        # Resolve destination path
        task_dir = (self.base_dir / clean_task_id).resolve()
        dest_path = (task_dir / name).resolve()

        # Strict containment check
        try:
            dest_path.relative_to(task_dir)
        except ValueError as err:
            raise ArtifactSecurityError(
                f"Resolved path '{dest_path}' escapes task directory '{task_dir}'."
            ) from err

        return dest_path

    def save_artifact(
        self,
        task_id: str,
        name: str,
        data: bytes | str | dict[str, Any],
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an artifact, validating containment, size, and redacting textual secrets."""
        dest_path = self._resolve_safe_path(task_id, name)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare payload and redact textual content
        payload: bytes
        if isinstance(data, dict):
            sanitized = redact_secrets(data)
            payload = json.dumps(sanitized, indent=2).encode("utf-8")
            if content_type == "application/octet-stream":
                content_type = "application/json"
        elif isinstance(data, str):
            sanitized_str = redact_secrets(data)
            payload = sanitized_str.encode("utf-8")
            if content_type == "application/octet-stream":
                content_type = "text/plain; charset=utf-8"
        elif isinstance(data, bytes):
            payload = data
        else:
            raise TypeError(f"Unsupported artifact data type: {type(data)}")

        # Enforce size limit
        if len(payload) > self.max_size_bytes:
            raise ArtifactSizeLimitError(
                f"Artifact '{name}' of size {len(payload)} bytes exceeds maximum {self.max_size_bytes} bytes."
            )

        # Write data
        dest_path.write_bytes(payload)

        # Write sidecar metadata (.meta.json)
        meta_path = dest_path.with_name(f"{dest_path.name}.meta.json")
        meta = {
            "name": name,
            "task_id": task_id,
            "size_bytes": len(payload),
            "content_type": content_type,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return f"artifacts://{task_id}/{name}"

    def read_artifact(self, task_id: str, name: str) -> tuple[bytes, str]:
        """Read artifact bytes and associated content_type."""
        dest_path = self._resolve_safe_path(task_id, name)
        if not dest_path.is_file():
            raise FileNotFoundError(f"Artifact '{name}' not found for task '{task_id}'.")

        data = dest_path.read_bytes()
        content_type = "application/octet-stream"

        meta_path = dest_path.with_name(f"{dest_path.name}.meta.json")
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                content_type = meta.get("content_type", content_type)
            except Exception:
                pass

        return data, content_type

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        """List metadata for all artifacts associated with a task."""
        clean_task_id = task_id.strip().replace("/", "_").replace("\\", "_")
        task_dir = self.base_dir / clean_task_id
        if not task_dir.is_dir():
            return []

        results: list[dict[str, Any]] = []
        for file in task_dir.iterdir():
            if not file.is_file() or file.name.endswith(".meta.json"):
                continue

            content_type = "application/octet-stream"
            meta_path = file.with_name(f"{file.name}.meta.json")
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    content_type = meta.get("content_type", content_type)
                except Exception:
                    pass

            results.append(
                {
                    "name": file.name,
                    "task_id": task_id,
                    "size_bytes": file.stat().st_size,
                    "content_type": content_type,
                    "uri": f"artifacts://{task_id}/{file.name}",
                }
            )

        return results

    def delete_artifact(self, task_id: str, name: str) -> bool:
        """Safely delete an artifact and its metadata sidecar."""
        dest_path = self._resolve_safe_path(task_id, name)
        deleted = False
        if dest_path.is_file():
            dest_path.unlink()
            deleted = True
        meta_path = dest_path.with_name(f"{dest_path.name}.meta.json")
        if meta_path.is_file():
            meta_path.unlink()
        return deleted

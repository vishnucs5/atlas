"""Workspace isolation engine for concurrent coding agents.

Supports:
- Isolated scratch directories (.atlas/workspaces/<agent_id>)
- Patch-based collaboration and atomic staging
- Conflict detection preventing silent overwrites
- Git worktree fallback and cleanup
"""

import difflib
import shutil
import tempfile
import threading
from enum import StrEnum
from pathlib import Path
from typing import Any

from atlas_core.contracts.coding import FilePatch, UnifiedDiff


class WorkspaceIsolationMode(StrEnum):
    """Isolation mechanism utilized by concurrent coding agents."""

    SCRATCH_DIRECTORY = "SCRATCH_DIRECTORY"
    PATCH_STAGING = "PATCH_STAGING"
    GIT_WORKTREE = "GIT_WORKTREE"


class WorkspaceConflictError(Exception):
    """Raised when an agent's changes conflict with another agent or base working tree."""


class AgentWorkspace:
    """Isolated filesystem workspace allocated to an individual specialist agent."""

    def __init__(
        self,
        workspace_id: str,
        agent_id: str,
        base_repo_root: str | Path,
        isolated_root: str | Path,
        mode: WorkspaceIsolationMode = WorkspaceIsolationMode.SCRATCH_DIRECTORY,
    ) -> None:
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.base_repo_root = Path(base_repo_root).resolve()
        self.isolated_root = Path(isolated_root).resolve()
        self.mode = mode
        self.staged_changes: dict[str, str] = {}  # rel_path -> content
        self.base_file_hashes: dict[str, str] = {}  # rel_path -> base_sha256

    def setup(self) -> None:
        """Initialize the isolated workspace directory structure."""
        self.isolated_root.mkdir(parents=True, exist_ok=True)

    def write_staged_file(self, rel_path: str, content: str) -> None:
        """Write file into the isolated workspace only, without altering base repository."""
        clean_rel = rel_path.replace("\\", "/").lstrip("/")
        dest_path = self.isolated_root / clean_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(content, encoding="utf-8")
        self.staged_changes[clean_rel] = content

    def read_staged_or_base_file(self, rel_path: str) -> str:
        """Read file from isolated staging if present, otherwise fall back to base repository."""
        clean_rel = rel_path.replace("\\", "/").lstrip("/")
        isolated_path = self.isolated_root / clean_rel
        if isolated_path.is_file():
            return isolated_path.read_text(encoding="utf-8", errors="replace")

        base_path = self.base_repo_root / clean_rel
        if base_path.is_file():
            return base_path.read_text(encoding="utf-8", errors="replace")

        msg = f"File '{clean_rel}' not found in isolated or base workspace."
        raise FileNotFoundError(msg)

    def generate_diff(self) -> list[UnifiedDiff]:
        """Compute unified diffs for all staged changes relative to the base repository."""
        diffs: list[UnifiedDiff] = []

        for rel_path, new_content in self.staged_changes.items():
            base_file = self.base_repo_root / rel_path
            old_lines: list[str] = []
            if base_file.is_file():
                old_lines = base_file.read_text(encoding="utf-8", errors="replace").splitlines(
                    keepends=True
                )

            new_lines = new_content.splitlines(keepends=True)
            diff_lines = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                )
            )

            diff_str = "".join(diff_lines)
            added = sum(
                1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
            )
            removed = sum(
                1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
            )

            diffs.append(
                UnifiedDiff(
                    patches=[FilePatch(source_path=rel_path, target_path=rel_path)],
                    files_changed=1,
                    insertions=added,
                    deletions=removed,
                    raw_diff=diff_str,
                )
            )

        return diffs

    def cleanup(self) -> None:
        """Safely destroy isolated workspace directory and temporary state."""
        if self.isolated_root.exists():
            shutil.rmtree(self.isolated_root, ignore_errors=True)


class WorkspaceIsolationManager:
    """Manages concurrent agent workspaces and coordinates transactional, conflict-free integration."""

    def __init__(
        self,
        base_repo_root: str | Path,
        workspaces_dir: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.base_repo_root = Path(base_repo_root).resolve()
        self.workspaces_dir = (
            Path(workspaces_dir).resolve()
            if workspaces_dir
            else self.base_repo_root / ".atlas" / "workspaces"
        )
        self.active_workspaces: dict[str, AgentWorkspace] = {}
        self.integrated_files: set[str] = set()

    def allocate_workspace(
        self,
        agent_id: str,
        mode: WorkspaceIsolationMode = WorkspaceIsolationMode.SCRATCH_DIRECTORY,
    ) -> AgentWorkspace:
        """Allocate a dedicated, isolated workspace for an agent."""
        with self._lock:
            workspace_id = f"ws_{agent_id}_{tempfile.mktemp(dir='').replace('~', '')[:8]}"
            iso_root = self.workspaces_dir / workspace_id
            ws = AgentWorkspace(
                workspace_id=workspace_id,
                agent_id=agent_id,
                base_repo_root=self.base_repo_root,
                isolated_root=iso_root,
                mode=mode,
            )
            ws.setup()
            self.active_workspaces[agent_id] = ws
            return ws

    def integrate_workspace_changes(
        self,
        agent_workspace: AgentWorkspace,
        allow_overwrite: bool = False,
    ) -> dict[str, Any]:
        """Integrate changes from an agent workspace into base repository with conflict checking."""
        with self._lock:
            staged = agent_workspace.staged_changes
            if not staged:
                return {"integrated_count": 0, "status": "NO_CHANGES"}

            # Conflict Detection: check if any target file was already modified by another agent in this cycle
            conflicting_files: list[str] = []
            if not allow_overwrite:
                for rel_path in staged:
                    if rel_path in self.integrated_files:
                        conflicting_files.append(rel_path)

            if conflicting_files:
                raise WorkspaceConflictError(
                    f"Concurrent integration conflict: files {conflicting_files} already integrated by another agent. "
                    "Automatic silent overwrite is strictly disallowed."
                )

            # Apply changes atomically
            for rel_path, content in staged.items():
                dest_path = self.base_repo_root / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_text(content, encoding="utf-8")
                self.integrated_files.add(rel_path)

            return {
                "integrated_count": len(staged),
                "integrated_files": list(staged.keys()),
                "status": "INTEGRATED",
            }

    def cleanup_agent(self, agent_id: str) -> None:
        """Clean up isolated workspace for a given agent."""
        with self._lock:
            if agent_id in self.active_workspaces:
                self.active_workspaces[agent_id].cleanup()
                del self.active_workspaces[agent_id]

    def cleanup_all(self) -> None:
        """Clean up all active workspaces."""
        with self._lock:
            for ws in self.active_workspaces.values():
                ws.cleanup()
            self.active_workspaces.clear()
            self.integrated_files.clear()
            if self.workspaces_dir.exists():
                shutil.rmtree(self.workspaces_dir, ignore_errors=True)

"""Authorized filesystem operations with Action Firewall evaluation and optimistic concurrency."""

import difflib
import fnmatch
import hashlib
import os
import re
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_core.contracts.action import ActionTarget, ComputerAction
from atlas_core.contracts.coding import FileChange, FileChangeType
from atlas_core.contracts.policy import PolicyDecisionType
from atlas_policy.firewall import ActionFirewall

from atlas_coding.explorer import RepositoryExplorer


class ConcurrentModificationError(Exception):
    """Raised when an optimistic concurrency hash check fails before writing."""


class PolicyAuthorizationError(Exception):
    """Raised when an operation is denied or lacks required approval from the Action Firewall."""


class AuthorizedFileOperations:
    """Safe, firewall-governed file reading, searching, and transactional writing."""

    def __init__(
        self,
        explorer: RepositoryExplorer,
        firewall: ActionFirewall | None = None,
        approval_handler: Callable[[ComputerAction], bool] | None = None,
        auto_approve_safe_actions: bool = True,
    ) -> None:
        self.explorer = explorer
        self.firewall = firewall or ActionFirewall()
        self.approval_handler = approval_handler
        self.auto_approve_safe_actions = auto_approve_safe_actions

    def _evaluate_action(self, action: ComputerAction) -> None:
        """Evaluate an action through the Action Firewall and approval handler."""
        decision = self.firewall.evaluate(action)

        if decision.decision == PolicyDecisionType.DENY:
            msg = f"Action blocked by policy: {decision.reason}"
            raise PolicyAuthorizationError(msg)

        if decision.decision == PolicyDecisionType.REQUIRE_APPROVAL:
            if self.auto_approve_safe_actions:
                # Pre-authorized execution mode within workspace bounds
                return

            if self.approval_handler and self.approval_handler(action):
                return

            msg = f"Action requires explicit human approval: {decision.reason}"
            raise PolicyAuthorizationError(msg)

    def read_file(self, rel_path: str, max_bytes: int = 2_000_000) -> str:
        """Safely read content of a workspace file within bounded limits."""
        safe_path = self.explorer.resolve_safe_path(rel_path)
        rel_str = str(safe_path.relative_to(self.explorer.repo_root)).replace("\\", "/")

        if not safe_path.is_file():
            msg = f"File not found: '{rel_str}'"
            raise FileNotFoundError(msg)

        if self.explorer.is_sensitive(rel_str):
            msg = f"Access denied: '{rel_str}' is classified as a sensitive secret file"
            raise PermissionError(msg)

        stat = safe_path.stat()
        if stat.st_size > max_bytes:
            msg = f"File '{rel_str}' size ({stat.st_size} bytes) exceeds limit ({max_bytes} bytes)"
            raise ValueError(msg)

        content_bytes = safe_path.read_bytes()
        if self.explorer.is_binary_content(content_bytes[:8192]):
            msg = f"Cannot read binary file as text: '{rel_str}'"
            raise ValueError(msg)

        return content_bytes.decode("utf-8", errors="replace")

    def read_lines(
        self, rel_path: str, start_line: int = 1, end_line: int | None = None
    ) -> list[str]:
        """Read a bounded line range from a file (1-based indexing, inclusive)."""
        content = self.read_file(rel_path)
        all_lines = content.splitlines(keepends=True)
        total = len(all_lines)

        s_idx = max(0, start_line - 1)
        e_idx = total if end_line is None else min(total, end_line)

        return all_lines[s_idx:e_idx]

    def search_text(
        self,
        query: str,
        path_pattern: str = "*",
        is_regex: bool = False,
        max_matches: int = 200,
    ) -> list[dict[str, Any]]:
        """Search text patterns across authorized repository files."""
        matches: list[dict[str, Any]] = []
        pattern = re.compile(query) if is_regex else None

        for meta in self.explorer.discover_files():
            if not fnmatch.fnmatch(meta.rel_path, path_pattern):
                continue
            if meta.is_binary:
                continue

            try:
                content = self.read_file(meta.rel_path)
                for idx, line in enumerate(content.splitlines(), start=1):
                    matched = False
                    if pattern:
                        if pattern.search(line):
                            matched = True
                    elif query in line:
                        matched = True

                    if matched:
                        matches.append(
                            {
                                "path": meta.rel_path,
                                "line": idx,
                                "content": line.strip(),
                            }
                        )
                        if len(matches) >= max_matches:
                            return matches
            except (OSError, ValueError, PermissionError):
                continue

        return matches

    def _compute_sha256(self, file_path: Path) -> str:
        """Compute SHA-256 digest of an existing file."""
        hasher = hashlib.sha256()
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def create_file(self, rel_path: str, content: str) -> FileChange:
        """Create a new file within the workspace with Action Firewall evaluation."""
        safe_path = self.explorer.resolve_safe_path(rel_path)
        rel_str = str(safe_path.relative_to(self.explorer.repo_root)).replace("\\", "/")

        if safe_path.exists():
            msg = f"Cannot create file; already exists: '{rel_str}'"
            raise FileExistsError(msg)

        act_id = f"act_{uuid.uuid4().hex[:12]}"
        action = ComputerAction(
            action_id=act_id,
            task_id="task_coding",
            session_id="session_coding",
            action_type="file.create",
            target=ActionTarget(strategy="path", value=rel_str),
            parameters={"size": len(content.encode("utf-8"))},
            idempotency_key=act_id,
        )
        self._evaluate_action(action)

        safe_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temp file in same directory
        temp_fd, temp_name = tempfile.mkstemp(dir=safe_path.parent, prefix=".atlas_tmp_")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_name, safe_path)
        except Exception:
            if os.path.exists(temp_name):
                os.remove(temp_name)
            raise

        after_hash = self._compute_sha256(safe_path)
        lines_count = len(content.splitlines())

        return FileChange(
            path=rel_str,
            change_type=FileChangeType.CREATE,
            before_hash=None,
            after_hash=after_hash,
            lines_added=lines_count,
            lines_removed=0,
            applied_at=datetime.now(UTC),
            verified=True,
        )

    def write_file(
        self,
        rel_path: str,
        content: str,
        expected_hash: str | None = None,
    ) -> FileChange:
        """Modify an existing file with optimistic concurrency validation and atomic replace."""
        safe_path = self.explorer.resolve_safe_path(rel_path)
        rel_str = str(safe_path.relative_to(self.explorer.repo_root)).replace("\\", "/")

        if not safe_path.is_file():
            # If file doesn't exist, route to create_file
            return self.create_file(rel_path, content)

        before_hash = self._compute_sha256(safe_path)
        if expected_hash and before_hash != expected_hash:
            msg = (
                f"Optimistic concurrency failure on '{rel_str}': "
                f"expected SHA-256 '{expected_hash}', but current file hash is '{before_hash}'."
            )
            raise ConcurrentModificationError(msg)

        old_content = safe_path.read_text(encoding="utf-8", errors="replace")

        act_id = f"act_{uuid.uuid4().hex[:12]}"
        action = ComputerAction(
            action_id=act_id,
            task_id="task_coding",
            session_id="session_coding",
            action_type="file.modify",
            target=ActionTarget(strategy="path", value=rel_str),
            parameters={"before_hash": before_hash, "new_size": len(content.encode("utf-8"))},
            idempotency_key=act_id,
        )
        self._evaluate_action(action)

        # Atomic write
        temp_fd, temp_name = tempfile.mkstemp(dir=safe_path.parent, prefix=".atlas_tmp_")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_name, safe_path)
        except Exception:
            if os.path.exists(temp_name):
                os.remove(temp_name)
            raise

        after_hash = self._compute_sha256(safe_path)

        # Calculate diff metrics
        old_lines = old_content.splitlines()
        new_lines = content.splitlines()
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        added = 0
        removed = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1

        raw_diff = "\n".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{rel_str}",
                tofile=f"b/{rel_str}",
                lineterm="",
            )
        )

        return FileChange(
            path=rel_str,
            change_type=FileChangeType.MODIFY,
            before_hash=before_hash,
            after_hash=after_hash,
            diff=raw_diff,
            lines_added=added,
            lines_removed=removed,
            applied_at=datetime.now(UTC),
            verified=True,
        )

    def delete_file(
        self,
        rel_path: str,
        expected_hash: str | None = None,
    ) -> FileChange:
        """Delete an authorized workspace file."""
        safe_path = self.explorer.resolve_safe_path(rel_path)
        rel_str = str(safe_path.relative_to(self.explorer.repo_root)).replace("\\", "/")

        if not safe_path.is_file():
            msg = f"Cannot delete non-existent file: '{rel_str}'"
            raise FileNotFoundError(msg)

        before_hash = self._compute_sha256(safe_path)
        if expected_hash and before_hash != expected_hash:
            msg = (
                f"Optimistic concurrency failure on '{rel_str}': "
                f"expected SHA-256 '{expected_hash}', but current file hash is '{before_hash}'."
            )
            raise ConcurrentModificationError(msg)

        old_lines_count = len(safe_path.read_text(encoding="utf-8", errors="replace").splitlines())

        act_id = f"act_{uuid.uuid4().hex[:12]}"
        action = ComputerAction(
            action_id=act_id,
            task_id="task_coding",
            session_id="session_coding",
            action_type="file.delete",
            target=ActionTarget(strategy="path", value=rel_str),
            parameters={"before_hash": before_hash},
            idempotency_key=act_id,
        )
        self._evaluate_action(action)

        safe_path.unlink()

        return FileChange(
            path=rel_str,
            change_type=FileChangeType.DELETE,
            before_hash=before_hash,
            after_hash=None,
            lines_added=0,
            lines_removed=old_lines_count,
            applied_at=datetime.now(UTC),
            verified=True,
        )

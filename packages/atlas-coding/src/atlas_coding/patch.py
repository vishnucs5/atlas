"""Structured unified diff parser and transactional multi-file patch engine."""

import re
from typing import Any

from atlas_core.contracts.coding import (
    FileChange,
    FileChangeType,
    FilePatch,
    PatchHunk,
    UnifiedDiff,
)

from atlas_coding.file_ops import AuthorizedFileOperations

HUNK_HEADER_PATTERN = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


class PatchConflictError(Exception):
    """Raised when a patch hunk cannot be applied due to conflict or line mismatch."""


class PatchEngine:
    """Parser and transactional executor for unified diffs."""

    def __init__(self, file_ops: AuthorizedFileOperations) -> None:
        self.file_ops = file_ops

    @staticmethod
    def parse_unified_diff(diff_text: str) -> UnifiedDiff:
        """Parse raw unified diff text into structured UnifiedDiff model."""
        lines = diff_text.splitlines()
        patches: list[FilePatch] = []
        current_patch: FilePatch | None = None
        current_hunk: PatchHunk | None = None

        total_insertions = 0
        total_deletions = 0

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]

            # Check for file headers
            if line.startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ "):
                if current_patch is not None:
                    if current_hunk is not None:
                        current_patch.hunks.append(current_hunk)
                        current_hunk = None
                    patches.append(current_patch)

                src_line = line[4:].strip()
                dst_line = lines[i + 1][4:].strip()

                # Strip a/ and b/ prefixes if present
                clean_src = src_line[2:] if src_line.startswith(("a/", "b/")) else src_line
                clean_dst = dst_line[2:] if dst_line.startswith(("a/", "b/")) else dst_line

                is_new = src_line in ("/dev/null", "dev/null", "")
                is_del = dst_line in ("/dev/null", "dev/null", "")

                current_patch = FilePatch(
                    source_path=clean_src,
                    target_path=clean_dst,
                    is_new=is_new,
                    is_deleted=is_del,
                    hunks=[],
                )
                i += 2
                continue

            # Check for hunk header
            match = HUNK_HEADER_PATTERN.match(line)
            if match and current_patch is not None:
                if current_hunk is not None:
                    current_patch.hunks.append(current_hunk)

                old_start = int(match.group(1))
                old_lines = int(match.group(2)) if match.group(2) else 1
                new_start = int(match.group(3))
                new_lines = int(match.group(4)) if match.group(4) else 1

                current_hunk = PatchHunk(
                    old_start=old_start,
                    old_lines=old_lines,
                    new_start=new_start,
                    new_lines=new_lines,
                    lines=[],
                )
                i += 1
                continue

            # Accumulate hunk lines
            if current_hunk is not None:
                if line.startswith(("+", "-", " ")):
                    current_hunk.lines.append(line)
                    if line.startswith("+"):
                        total_insertions += 1
                    elif line.startswith("-"):
                        total_deletions += 1
                elif line.startswith("\\ No newline"):
                    # Ignore trailing newline notice
                    pass
                else:
                    # Non-hunk line encountered
                    if current_patch is not None:
                        current_patch.hunks.append(current_hunk)
                        current_hunk = None

            i += 1

        if current_patch is not None:
            if current_hunk is not None:
                current_patch.hunks.append(current_hunk)
            patches.append(current_patch)

        return UnifiedDiff(
            patches=patches,
            files_changed=len(patches),
            insertions=total_insertions,
            deletions=total_deletions,
            raw_diff=diff_text,
        )

    def _simulate_patch_on_lines(
        self,
        file_path: str,
        lines: list[str],
        hunks: list[PatchHunk],
    ) -> list[str]:
        """Apply hunks sequentially to an in-memory list of lines."""
        result = list(lines)

        # Track line offset caused by additions/deletions in previous hunks
        offset = 0

        for hunk_idx, hunk in enumerate(hunks, start=1):
            expected_start = (hunk.old_start - 1) + offset

            # Prepare expected removal lines and new lines
            expected_context: list[str] = []
            replacement_lines: list[str] = []
            expected_old_len = 0

            for hline in hunk.lines:
                marker = hline[0] if hline else " "
                text = hline[1:]
                if marker == " ":
                    expected_context.append(text)
                    replacement_lines.append(text)
                    expected_old_len += 1
                elif marker == "-":
                    expected_context.append(text)
                    expected_old_len += 1
                elif marker == "+":
                    replacement_lines.append(text)

            # Check if expected lines match at expected_start
            match_pos = -1
            # Try exact position
            if expected_start >= 0 and expected_start + expected_old_len <= len(result):
                slice_candidate = [
                    s.rstrip("\r\n")
                    for s in result[expected_start : expected_start + expected_old_len]
                ]
                clean_context = [c.rstrip("\r\n") for c in expected_context]
                if slice_candidate == clean_context:
                    match_pos = expected_start

            # If not exact match, try small fuzz window (-5 to +5)
            if match_pos == -1:
                fuzz_range = 5
                low = max(0, expected_start - fuzz_range)
                high = min(len(result) - expected_old_len + 1, expected_start + fuzz_range + 1)
                clean_context = [c.rstrip("\r\n") for c in expected_context]
                for pos in range(low, max(low, high)):
                    if pos + expected_old_len <= len(result):
                        candidate = [s.rstrip("\r\n") for s in result[pos : pos + expected_old_len]]
                        if candidate == clean_context:
                            match_pos = pos
                            break

            if match_pos == -1:
                msg = (
                    f"Patch conflict in '{file_path}' at hunk #{hunk_idx} "
                    f"(line {hunk.old_start}). Target content does not match hunk context."
                )
                raise PatchConflictError(msg)

            # Apply replacement
            result[match_pos : match_pos + expected_old_len] = [
                r if r.endswith("\n") else f"{r}\n" for r in replacement_lines
            ]
            offset += len(replacement_lines) - expected_old_len

        return result

    def apply_patch(
        self,
        unified_diff: UnifiedDiff | str,
        dry_run: bool = False,
    ) -> list[FileChange]:
        """Apply a multi-file unified diff transactionally with dry-run verification and rollback."""
        parsed = (
            self.parse_unified_diff(unified_diff) if isinstance(unified_diff, str) else unified_diff
        )

        if not parsed.patches:
            return []

        # Step 1: Dry-run validation across all files
        planned_changes: list[dict[str, Any]] = []

        for patch in parsed.patches:
            target_path = patch.target_path if not patch.is_deleted else patch.source_path

            if patch.is_new:
                # Target should not exist or be empty
                try:
                    existing = self.file_ops.read_file(target_path)
                    if existing.strip():
                        msg = f"Cannot apply new file patch; '{target_path}' already exists and is non-empty."
                        raise PatchConflictError(msg)
                except FileNotFoundError:
                    pass

                new_lines = []
                for hunk in patch.hunks:
                    for hline in hunk.lines:
                        if hline.startswith("+"):
                            new_lines.append(hline[1:])
                content = "\n".join(new_lines) + ("\n" if new_lines else "")
                planned_changes.append(
                    {
                        "path": target_path,
                        "action": "CREATE",
                        "content": content,
                        "before_hash": None,
                    }
                )

            elif patch.is_deleted:
                original_content = self.file_ops.read_file(target_path)
                safe_path = self.file_ops.explorer.resolve_safe_path(target_path)
                before_hash = self.file_ops._compute_sha256(safe_path)
                planned_changes.append(
                    {
                        "path": target_path,
                        "action": "DELETE",
                        "content": original_content,
                        "before_hash": before_hash,
                    }
                )

            else:
                original_content = self.file_ops.read_file(target_path)
                safe_path = self.file_ops.explorer.resolve_safe_path(target_path)
                before_hash = self.file_ops._compute_sha256(safe_path)

                orig_lines = original_content.splitlines(keepends=True)
                updated_lines = self._simulate_patch_on_lines(target_path, orig_lines, patch.hunks)
                new_content = "".join(updated_lines)

                planned_changes.append(
                    {
                        "path": target_path,
                        "action": "MODIFY",
                        "content": new_content,
                        "before_hash": before_hash,
                        "original_content": original_content,
                    }
                )

        if dry_run:
            # Return dry-run simulated FileChanges
            results: list[FileChange] = []
            for item in planned_changes:
                c_type = FileChangeType(item["action"])
                results.append(
                    FileChange(
                        path=item["path"],
                        change_type=c_type,
                        before_hash=item["before_hash"],
                        after_hash=None,
                        verified=False,
                    )
                )
            return results

        # Step 2: Transactional Execution with Rollback
        rollback_log: list[dict[str, Any]] = []
        applied_file_changes: list[FileChange] = []

        try:
            for item in planned_changes:
                action_type = item["action"]
                path = item["path"]

                if action_type == "CREATE":
                    rollback_log.append({"action": "DELETE", "path": path})
                    fc = self.file_ops.create_file(path, item["content"])
                    applied_file_changes.append(fc)

                elif action_type == "MODIFY":
                    rollback_log.append(
                        {
                            "action": "RESTORE",
                            "path": path,
                            "content": item["original_content"],
                        }
                    )
                    fc = self.file_ops.write_file(
                        path, item["content"], expected_hash=item["before_hash"]
                    )
                    applied_file_changes.append(fc)

                elif action_type == "DELETE":
                    rollback_log.append(
                        {
                            "action": "RESTORE",
                            "path": path,
                            "content": item["content"],
                        }
                    )
                    fc = self.file_ops.delete_file(path, expected_hash=item["before_hash"])
                    applied_file_changes.append(fc)

            return applied_file_changes

        except Exception as err:
            # Transaction failed during write - execute rollback
            for rb in reversed(rollback_log):
                try:
                    if rb["action"] == "DELETE":
                        safe_p = self.file_ops.explorer.resolve_safe_path(rb["path"])
                        if safe_p.exists():
                            safe_p.unlink()
                    elif rb["action"] == "RESTORE":
                        safe_p = self.file_ops.explorer.resolve_safe_path(rb["path"])
                        safe_p.write_text(rb["content"], encoding="utf-8")
                except Exception:
                    pass

            msg = f"Transactional patch application failed and was rolled back: {err}"
            raise PatchConflictError(msg) from err

# ATLAS CLI — Authorized File Operations Specification

## 1. Overview and Security Guardrails

The `AuthorizedFileOperations` engine (`atlas_coding.file_ops`) provides secure, bounded, and audited filesystem access for the ATLAS Autonomous Coding Engine.

### Core Security Controls
- **Boundary Containment**: All file operations resolve relative paths against `repo_root` using `RepositoryExplorer.resolve_safe_path()`. Attempted path traversals (e.g. `../../etc/passwd` or Windows drive letter escapes) immediately raise `ValueError`.
- **Sensitive File Exclusion**: Files matching `.env*`, `*.pem`, `*.key`, `*id_rsa*`, and credential patterns are prohibited from reading, preventing secret leakage into model context.
- **Binary File Detection**: Files containing null bytes (`b'\x00'`) in initial chunks are rejected from text reading and unified diffing.
- **Bounded Range Reading**: `read_lines(start_line, end_line)` uses 1-based indexing with strict boundary clamps to prevent runaway token usage.
- **Atomic Writes**: All file modifications and creations write to a hidden temporary file within the target directory before invoking `os.replace` (atomic file swap).
- **Optimistic Concurrency**: `write_file` and `delete_file` verify the current SHA-256 hash matches the expected pre-condition hash. If the file was changed concurrently, a `ConcurrentModificationError` is raised.

---

## 2. Action Firewall Gating

Every mutating operation generates a structured `ComputerAction`:

```python
action = ComputerAction(
    action_id=f"act_{uuid.uuid4().hex[:12]}",
    task_id=task.task_id,
    session_id=session.session_id,
    action_type="file.modify",  # or file.create, file.delete
    target=ActionTarget(strategy="path", value="src/module.py"),
    parameters={"before_hash": before_hash, "new_size": len(content)},
    idempotency_key=action_id,
)
```

The action is submitted to `ActionFirewall.evaluate(action)`. If the firewall returns `DENY` or `REQUIRE_APPROVAL` without valid authorization, execution halts immediately with `PolicyAuthorizationError`.

---

## 3. Cryptographic Verification & Audit Records

Every file change produces a verified `FileChange` contract:

| Field | Description |
|---|---|
| `path` | Normalized relative workspace path |
| `change_type` | `CREATE`, `MODIFY`, `DELETE`, or `RENAME` |
| `before_hash` | SHA-256 before modification (`None` for creations) |
| `after_hash` | SHA-256 after modification (`None` for deletions) |
| `diff` | Unified diff of applied changes |
| `lines_added` | Count of inserted lines |
| `lines_removed` | Count of deleted lines |
| `applied_at` | UTC timestamp |
| `verified` | Deterministic boolean confirmation |

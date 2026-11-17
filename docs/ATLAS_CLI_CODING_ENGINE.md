# ATLAS CLI — Autonomous Coding Engine Architecture

## 1. Architectural Mission and Invariants

The ATLAS CLI Autonomous Coding Engine (`atlas-coding`) establishes a native software engineering agent runtime built directly on the ATLAS core execution authority and Action Firewall.

### Core Architectural Invariants
1. **Core Ownership**: `atlas-core` defines the contracts (`CodingTask`, `FileChange`, `UnifiedDiff`, `TestResultSummary`). The CLI and coding engine adapt these contracts; they never duplicate orchestration or planner state machines.
2. **Action Firewall Gate**: Every file modification, deletion, and terminal execution passes through `ActionFirewall.evaluate(action)`. Zero unvetted model-to-OS execution paths.
3. **Optimistic Concurrency**: Stale writes are strictly rejected by verifying SHA-256 pre-hashes before committing any modifications.
4. **Deterministic Verification Invariant**: No coding task is marked `COMPLETED` without post-condition verification confirming file existence, hash integrity, and test suite passage.
5. **Zero-Dependency Core**: `packages/atlas-core` imports only Python standard library modules and Pydantic. `packages/atlas-coding` isolates filesystem, git, and terminal drivers.

---

## 2. Coding Lifecycle State Machine

The coding engine executes through an immutable 8-phase lifecycle:

```
[OBSERVE]
    │ Repository exploration, manifest discovery, git status inspection
    ▼
[PLAN]
    │ Heuristic file identification, multi-phase plan synthesis, risk classification
    ▼
[FIREWALL]
    │ ActionFirewall evaluates proposed file/terminal actions against policy rules
    ▼
[APPROVAL]
    │ Human-in-the-loop gating for HIGH/CRITICAL risk operations or pre-authorized policies
    ▼
[EXECUTE]
    │ Atomic file writes, transactional patch application, safe subprocess invocation
    ▼
[VERIFY]
    │ SHA-256 hash validation, syntax and test execution assertions
    ▼
[CHECKPOINT]
    │ Action history and state recorded to persistent storage
    ▼
[COMPLETE / FAIL]
    │ Deterministic verdict rendered
```

---

## 3. Package Structure

```
packages/atlas-coding/
├── pyproject.toml
├── README.md
└── src/atlas_coding/
    ├── __init__.py           # Unified exports
    ├── explorer.py           # Workstream 2: Boundary containment & secret exclusion
    ├── file_ops.py           # Workstream 3: Bounded read, search & atomic writes
    ├── patch.py              # Workstream 4: Unified diff parser & rollback engine
    ├── terminal.py           # Workstream 5: Process isolation & credential redaction
    ├── git.py                # Workstream 6: Read-only porcelain inspection
    ├── planner.py            # Workstream 7: Risk profile & plan synthesis
    ├── test_runner.py        # Workstream 9: Automated framework detection & QA
    └── engine.py             # Workstream 8: CodingEngine lifecycle coordinator
```

---

## 4. Verification Evidence

All 12 unit and integration test assertions pass deterministically (`tests/unit/test_coding_engine.py`):
- Path traversal prevention (`../../` blocked)
- Secret file exclusion (`.env`, `*id_rsa*` excluded from model context)
- Optimistic concurrency conflict rejection (`ConcurrentModificationError`)
- Transactional patch dry-run and rollback
- Destructive command detection via Action Firewall (`rm -rf`, `del /s /q`)
- Secret redaction in terminal output
- End-to-end task lifecycle and verification invariant enforcement

# Test Results & Verification Ledger

## 1. Test Strategy & Protocol

ATLAS maintains a strict testing regime across all workspace packages. Testing invariants:
- **No Placeholder Tests**: Every test must verify concrete behavior and deterministic assertions.
- **Coverage Target**: Minimum 85% line coverage on domain and engine packages (`atlas-core`, `atlas-storage`, `atlas-policy`, `atlas-observability`).
- **Determinism**: No network calls, unpredictable timings, or unseeded random state in unit tests.

### Execution Command

```bash
uv run pytest -v --cov=packages --cov=apps
```

---

## 2. Test Suites Matrix

| Test Suite File | Package / Component | Description | Status | Pass / Total |
| :--- | :--- | :--- | :--- | :--- |
| `tests/unit/test_contracts.py` | `atlas-core` | Pydantic v2 immutability, validation, and JSON round-trips | Planned (Task 2) | - |
| `tests/unit/test_state_machine.py` | `atlas-core` | 14-state transitions, invalid transition rejections, events | Planned (Task 3) | - |
| `tests/unit/test_sqlite_storage.py` | `atlas-storage` | SQLite WAL mode, sequential events, materialized task reads | Planned (Task 4) | - |
| `tests/unit/test_policy_firewall.py` | `atlas-policy` | Rule sets (ALLOW, REQUIRE_APPROVAL, BLOCK, DRY_RUN) | Planned (Task 5) | - |
| `tests/unit/test_observability.py` | `atlas-observability` | JSON structured formatting, contextual binding, secret masking | Planned (Task 6) | - |
| `tests/unit/test_api_health.py` | `apps/api` | `/healthz`, `/readyz`, `/api/v1/status` endpoints | Planned (Task 7) | - |
| `tests/integration/test_cli.py` | `apps/cli` | `atlas doctor`, `atlas init`, `atlas task` CLI operations | Planned (Task 8) | - |
| `tests/integration/test_end_to_end.py` | Full System | End-to-end task lifecycle integration suite | Planned (Task 10) | - |

---

## 3. Phase 1 Acceptance Criteria Checklist

| ID | Acceptance Criterion | Target Suite | Status |
| :--- | :--- | :--- | :--- |
| **AC-01** | `uv sync` resolves all workspace packages without dependency conflicts | Workspace / CI | Planned |
| **AC-02** | `atlas-core` imports standard library + `pydantic` only | Static Analysis / Tests | Planned |
| **AC-03** | Core contracts validate schema version `"1.0"` and reject malformed schemas | `test_contracts.py` | Planned |
| **AC-04** | State machine transitions across all 14 states and raises `InvalidStateTransitionError` on illegal moves | `test_state_machine.py` | Planned |
| **AC-05** | State machine emits an `ExecutionEvent` for every valid transition | `test_state_machine.py` | Planned |
| **AC-06** | SQLite storage operates in WAL mode and supports concurrent readers | `test_sqlite_storage.py` | Planned |
| **AC-07** | Event store enforces strictly increasing sequence numbers per task | `test_sqlite_storage.py` | Planned |
| **AC-08** | Materialized task view accurately reflects latest state after event replay | `test_sqlite_storage.py` | Planned |
| **AC-09** | Action Firewall correctly tags safe, sensitive, dangerous, and dry-run actions | `test_policy_firewall.py` | Planned |
| **AC-10** | Structured logging outputs JSON with `task_id`, `session_id`, and `step_id` | `test_observability.py` | Planned |
| **AC-11** | Secret masking sanitizes API keys, tokens, and passwords | `test_observability.py` | Planned |
| **AC-12** | FastAPI `/healthz` and `/readyz` report valid HTTP 200 health status | `test_api_health.py` | Planned |
| **AC-13** | `atlas doctor` exits 0 on valid environment and reports diagnostics | `test_cli.py` | Planned |
| **AC-14** | `atlas init` and `atlas task` initialize database and execute lifecycle tasks | `test_cli.py` | Planned |

---

## 4. Test Run Log

### Run 001 - 2026-11-12
- **Scope**: Task 1 Monorepo Scaffolding
- **Result**: PASSED (Workspace configuration, linting rules, and documentation verified)
- **Notes**: Package code directories and test suites will be introduced in Task 2.

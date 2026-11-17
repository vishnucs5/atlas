# ATLAS Phase 16.7 — Monorepo Regression & Static Analysis Reproduction Report

## 1. Executive Summary

This report documents the independent reproduction and execution of the full ATLAS monorepo test suite, dedicated phase suites, and static analysis linters for Phase 16.7.

## 2. Test Execution Matrix & Captured Evidence

| Test Suite | Command Executed | Exit Code | Collected | Passed | Failed | Skipped | Duration |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Monorepo Full Regression** | `uv run pytest -q` | **1** | 905 | 904 | **1** | 0 | 89.08s |
| **Phase 16 Acceptance Suite** | `uv run pytest tests/acceptance/test_phase16_acceptance.py -v` | **1** | 45 | 44 | **1** | 0 | 0.35s |
| **Phase 16.2 Remediation Suite** | `uv run pytest (Get-ChildItem -Filter '*phase16_2*.py' -Recurse tests).FullName -v` | **0** | 37 | 37 | 0 | 0 | 5.00s |
| **Phase 16.4 Remediation Suite** | `uv run pytest (Get-ChildItem -Filter '*phase16_4*.py' -Recurse tests).FullName -v` | **0** | 47 | 47 | 0 | 0 | 6.77s |
| **Phase 16.6 Approvals Concurrency** | `uv run pytest tests/unit/test_phase16_6_approvals_concurrency.py -v` | **0** | 6 | 6 | 0 | 0 | 0.37s |
| **Phase 16.6 Durable Idempotency** | `uv run pytest tests/unit/test_phase16_6_idempotency.py -v` | **0** | 15 | 15 | 0 | 0 | 0.39s |
| **Phase 16.6 Lease Race Concurrency** | `uv run pytest tests/unit/test_phase16_6_lease_race.py -v` | **0** | 8 | 8 | 0 | 0 | 0.40s |
| **Phase 16.6 DNS Rebinding & SSRF** | `uv run pytest tests/unit/test_phase16_6_dns_rebinding.py -v` | **0** | 7 | 7 | 0 | 0 | 0.47s |
| **Phase 16.6 PostgreSQL Hardening** | `uv run pytest tests/integration/test_phase16_6_postgres_hardening.py -v` | **0** | 4 | 4 | 0 | 0 | 4.08s |
| **Phase 16.4 PostgreSQL Full Suite** | `uv run pytest tests/integration/test_phase16_4_postgres_full.py -v` | **0** | 6 | 6 | 0 | 0 | 4.87s |

---

## 3. Detailed Failure Analysis: Acceptance Test `PROC-29`

During the independent reproduction of the full monorepo suite and Phase 16 acceptance suite, **1 test failed**:

**Failed Test:** `tests/acceptance/test_phase16_acceptance.py::test_proc29_unknown_outcome_reconciliation`

### Raw Traceback:
```text
_________________ test_proc29_unknown_outcome_reconciliation __________________

    def test_proc29_unknown_outcome_reconciliation() -> None:
        coordinator = SagaCoordinator()
        saga = coordinator.create_saga("pinst_banking_1")
        step = SagaStep(name="external_wire_transfer", is_idempotent=False)
    
        def timing_out_call(p: dict) -> dict:
            raise TimeoutError("Socket timeout waiting for payment gateway")
    
        with pytest.raises(ReconciliationRequiredError):
>           coordinator.execute_step(saga.saga_id, step, timing_out_call)

tests\acceptance\test_phase16_acceptance.py:872: 
...
packages\atlas-process\src\atlas_process\transactions.py:227: ReconciliationRequiredError
E   atlas_process.transactions.ReconciliationRequiredError: Step 'external_wire_transfer' entered RECONCILIATION_REQUIRED: outcome unknown after timeout.
```

### Root Cause Analysis:
1. `packages/atlas-process/src/atlas_process/transactions.py:56` declares:
   ```python
   class ReconciliationRequiredError(SagaError):
       """Raised when an operation's outcome is unknown (e.g. timeout) and requires reconciliation."""
   ```
2. `packages/atlas-process/src/atlas_process/idempotency.py:47` declares:
   ```python
   class ReconciliationRequiredError(IdempotencyError):
       """Raised when an operation outcome is unknown and requires reconciliation before retry."""
   ```
3. In `packages/atlas-process/src/atlas_process/__init__.py:59`, the package root imports:
   ```python
   from atlas_process.idempotency import (
       ...
       ReconciliationRequiredError,
       ...
   )
   ```
   This overwrote the previous import of `ReconciliationRequiredError` from `atlas_process.transactions`.
4. In `tests/acceptance/test_phase16_acceptance.py:53`, the test imports:
   ```python
   from atlas_process import (
       ...
       ReconciliationRequiredError,
       ...
   )
   ```
5. When `SagaCoordinator.execute_step()` raises `atlas_process.transactions.ReconciliationRequiredError`, `pytest.raises(ReconciliationRequiredError)` expects the `atlas_process.idempotency.ReconciliationRequiredError` class. Because the two classes reside in different module hierarchies (`SagaError` vs `IdempotencyError`), `pytest.raises` fails to catch it, failing the test.

---

## 4. Static Analysis & Linter Reproduction

### 4.1 Ruff Lint Check
**Command:** `uv run ruff check .`
```text
All checks passed!
```
**Exit Code:** `0`

### 4.2 Ruff Format Check
**Command:** `uv run ruff format --check .`
```text
unformatted: File would be reformatted
   --> docs\PHASE_16_6_DURABLE_IDEMPOTENCY.md:105:54
1 file would be reformatted, 536 files already formatted
```
**Exit Code:** `1` (Formatting discrepancy in markdown doc string code block).

### 4.3 Mypy Static Type Analysis
**Command:** `uv run mypy packages/atlas-process/src --ignore-missing-imports`
```text
Success: no issues found in 19 source files
```
**Exit Code:** `0`

### 4.4 Runtime Warnings
- Coroutine warnings: **0** unawaited coroutine warnings.
- Deprecation warning: 1 warning from `starlette.testclient` (`Using httpx with starlette.testclient is deprecated; install httpx2 instead`).

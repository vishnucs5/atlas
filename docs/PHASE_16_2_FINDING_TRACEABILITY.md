# ATLAS Phase 16.2 — Finding Traceability Matrix

**Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**Date:** 2026-11-17  

---

## Traceability Catalog

### REM-16.1-01: No Durable Database Persistence & Crash Durability Failure
- **Finding ID:** REM-16.1-01 (Priority: P0)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/engine.py` (lines 40–55, 230–250)
- **Reproduction Steps:**
  1. Instantiate `ProcessExecutionEngine()`.
  2. Start process instance `inst-1` and advance to `RUNNING`.
  3. Simulate process termination and instantiate a new `ProcessExecutionEngine()`.
  4. Call `recover_after_restart()`.
  5. Observed: `_instances` is `{}`; zero instances are recovered.
- **Root Cause:**
  `ProcessExecutionEngine` stores definitions, instances, checkpoints, and leases exclusively in in-memory Python dictionaries. No database tables or queries exist.
- **Proposed Fix:**
  Implement `ProcessStorageProtocol` and `PostgresProcessStorage` backed by PostgreSQL (and `SqliteProcessStorage` for embedded/local durability). Persist state transitions before acknowledging execution. Query unfinished instances on startup.
- **Regression Test:** `tests/integration/test_phase16_2_persistence.py::test_process_crash_and_restart_recovery`
- **Verification Evidence:** Pending verification in Milestone M1.

---

### REM-16.1-02: Silent / Phantom Saga Compensation on Missing Handlers
- **Finding ID:** REM-16.1-02 (Priority: P0)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/transactions.py` (lines 156–167)
- **Reproduction Steps:**
  1. Create a saga with completed step `payment_step`.
  2. Invoke `compensate_saga(saga_id, compensation_handlers={})` (empty handler dictionary).
  3. Observed: `success` defaults to `True`, step status set to `SagaStepStatus.COMPENSATED`, and saga status set to `SagaStatus.COMPENSATED`.
- **Root Cause:**
  `handler = handlers.get(step.name)` evaluates to `None`. The variable `success` is initialized to `True` and never changed if `handler` is absent.
- **Proposed Fix:**
  If `handler` is None, set `success = False`, record error as `"Missing compensation handler"`, mark step as `SagaStepStatus.COMPENSATION_FAILED`, and transition saga to `SagaStatus.PARTIAL_FAILURE` or `SagaStatus.RECONCILIATION_REQUIRED`.
- **Regression Test:** `tests/unit/test_phase16_2_saga_integrity.py::test_missing_handler_fails_compensation`
- **Verification Evidence:** Reproduced in `scratch/reproduce_findings.py` (`success=True, saga.status=COMPENSATED`).

---

### REM-16.1-03: Unauthenticated and Cross-Tenant API Access
- **Finding ID:** REM-16.1-03 (Priority: P0)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/api.py` (lines 47–118)
- **Reproduction Steps:**
  1. Issue `POST /api/v1/processes/definitions` or `POST /api/v1/processes/instances` without Authorization header.
  2. Issue `GET /api/v1/processes/instances/{instance_id}` for an instance belonging to another tenant.
  3. Issue `POST /api/v1/processes/approvals/{approval_id}/decide` specifying arbitrary `approver_id`.
  4. Observed: All requests execute successfully with zero authentication or tenant checks.
- **Root Cause:**
  FastAPI route handlers declare no security dependencies (`Depends(verify_caller)`).
- **Proposed Fix:**
  Implement `get_current_identity` dependency integrating with `atlas_enterprise.iam.EnterpriseIAMManager` and `SessionToken`. Enforce tenant ownership (`caller.tenant_id == resource.tenant_id`). Disallow caller impersonation in approval decisions.
- **Regression Test:** `tests/unit/test_phase16_2_api_auth.py::test_unauthenticated_requests_rejected`
- **Verification Evidence:** Reproduced in manual route inspection.

---

### REM-16.1-04: Conditional Branching Evaluation Hardcoded Stub
- **Finding ID:** REM-16.1-04 (Priority: P0)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/engine.py` (lines 208–216)
- **Reproduction Steps:**
  1. Define a conditional task with condition `expression="amount > 1000000"`.
  2. Create an instance with `variables={"amount": 50}`.
  3. Call `_evaluate_conditions(tdef, instance)`.
  4. Observed: Returns `True`.
- **Root Cause:**
  The implementation loop contains `pass` and unconditionally returns `True`.
- **Proposed Fix:**
  Implement `SafeExpressionEvaluator` utilizing Python AST parsing with an allowlisted subset of operators (comparisons, boolean logic, literals, variable lookups).
- **Regression Test:** `tests/unit/test_phase16_2_evaluator.py::test_conditional_branching_ast`
- **Verification Evidence:** Reproduced in `scratch/reproduce_findings.py` (`evaluated to -> True`).

---

### REM-16.1-05: Approval Decision State Inversion & Lack of Terminal State Lock
- **Finding ID:** REM-16.1-05 (Priority: P1)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/approvals.py` (lines 140–188)
- **Reproduction Steps:**
  1. Request an approval requiring 2 approvals.
  2. Operator 1 rejects the request $\to$ status transitions to `REJECTED`.
  3. Operator 2 and Operator 3 submit approval $\to$ status transitions to `APPROVED`.
- **Root Cause:**
  `decide()` does not check if `req.status != ApprovalDecision.PENDING`. Once `approved_count >= req.required_approvals`, status is overwritten without respecting prior rejections.
- **Proposed Fix:**
  Enforce state lock: if `req.status != ApprovalDecision.PENDING`, raise `ApprovalError("Approval request is already resolved")`. Once `REJECTED`, permanently lock request.
- **Regression Test:** `tests/unit/test_phase16_2_approvals.py::test_rejection_cannot_be_inverted`
- **Verification Evidence:** Reproduced in `scratch/reproduce_findings.py` (`status=APPROVED`).

---

### REM-16.1-06: Static Fallback HMAC Secret in Event Triggers
- **Finding ID:** REM-16.1-06 (Priority: P1)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/triggers.py` (lines 61–74)
- **Reproduction Steps:**
  1. Instantiate `EventTriggerEngine()`.
  2. Compute signature for payload using default key.
  3. Submit webhook for an arbitrary tenant $\to$ signature is accepted.
- **Root Cause:**
  Constructor defaults `secret_key` to `"atlas-process-trigger-secret-v16"`.
- **Proposed Fix:**
  Remove default secret parameter. Require explicitly provisioned per-tenant webhook secret store. Raise `ValueError` if secret is unconfigured.
- **Regression Test:** `tests/unit/test_phase16_2_triggers.py::test_missing_tenant_secret_fails`
- **Verification Evidence:** Reproduced in `scratch/reproduce_findings.py` (`event.signature=6f3ea88e...`).

---

### REM-16.1-07: In-Memory Single-Process Concurrency Control
- **Finding ID:** REM-16.1-07 (Priority: P1)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/engine.py` (line 48)
- **Reproduction Steps:**
  1. Instantiate two engine instances in separate worker threads/processes sharing same backend.
  2. Execute tasks concurrently $\to$ process-local `asyncio.Lock()` cannot prevent race conditions.
- **Root Cause:**
  Coordination relies purely on in-process `asyncio.Lock()`.
- **Proposed Fix:**
  Implement database row-level locking / advisory locks and monotonic fencing tokens in `storage.py` to reject stale worker commits.
- **Regression Test:** `tests/integration/test_phase16_2_coordination.py::test_distributed_fencing_rejection`
- **Verification Evidence:** Verified via code inspection.

---

### REM-16.1-08: Plaintext Connector Credential Storage
- **Finding ID:** REM-16.1-08 (Priority: P2)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/connectors.py` (lines 96–100)
- **Reproduction Steps:**
  1. Call `connector.set_credentials({"api_key": "secret123"})`.
  2. Inspect `connector._credentials` or string representation $\to$ raw secret is visible.
- **Root Cause:**
  Credentials stored in plaintext Python `dict[str, str]`.
- **Proposed Fix:**
  Use `SecretStr` / encrypted credential store. Mask values in `__repr__` and logs.
- **Regression Test:** `tests/unit/test_phase16_2_connectors.py::test_credentials_masked_in_repr`
- **Verification Evidence:** Verified via code inspection.

---

### REM-16.1-09: Enterprise Connectors Lack Verified Real HTTP Transport
- **Finding ID:** REM-16.1-09 (Priority: P2)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/connectors.py` (lines 140–250)
- **Reproduction Steps:**
  1. Call `ERPConnector.execute_action("create_purchase_order", ...)`.
  2. Inspect network traffic $\to$ zero socket operations; returns static dict.
- **Root Cause:**
  Connector logic is simulated using hardcoded dictionary fixtures.
- **Proposed Fix:**
  Implement `httpx.AsyncClient` transport with configurable timeouts, bounded retries with exponential backoff, circuit breaker state machine, and connection pooling.
- **Regression Test:** `tests/integration/test_phase16_2_connectors.py::test_connector_http_transport`
- **Verification Evidence:** Verified via code inspection.

---

### REM-16.1-10: In-Memory Historical Accumulation Without Bounded Archival
- **Finding ID:** REM-16.1-10 (Priority: P2)
- **Source File & Location:** `packages/atlas-process/src/atlas_process/engine.py` & `analytics.py`
- **Reproduction Steps:**
  1. Execute 10,000 process instances.
  2. Inspect memory $\to$ all 10,000 instances retained in `_instances` indefinitely.
- **Root Cause:**
  No pagination, archival, or memory eviction mechanism exists.
- **Proposed Fix:**
  Implement database-backed pagination (`list_instances(limit, offset, status)`) and an archival method (`archive_completed_instances(cutoff_timestamp)`).
- **Regression Test:** `tests/unit/test_phase16_2_archival.py::test_pagination_and_archival`
- **Verification Evidence:** Verified via code inspection.

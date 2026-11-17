# ATLAS Phase 16.7 — Distributed Approval Concurrency Audit Report

## 1. Executive Summary

This report delivers the independent technical audit of **FINDING-16.5-01** (Multi-Worker Approval In-Memory Cache Divergence) in ATLAS Phase 16.6 at commit `c309ec4e5be6cf438aa7ee038e5a34c2d8e37d57`.

The audit evaluated whether the migration of approval quorum evaluation to relational row-locked queries (`SELECT ... FOR UPDATE`) deterministically eliminates split-brain approvals and guarantees cluster-wide consistency across distributed worker nodes.

## 2. Code Inspection & Line-Level Verification

### 2.1 Database Row Locking in `storage.py`

#### PostgreSQL Implementation (`packages/atlas-process/src/atlas_process/storage.py:2506-2622`):
```python
cur.execute(
    """
    SELECT approval_id, process_instance_id, task_def_id, action_name, target_resource,
           parameters, parameter_hash, requesting_identity, allowed_approver_ids,
           allowed_approver_roles, required_approvals, risk_classification, status,
           expires_at, created_at, resolved_at
    FROM process_approval_requests
    WHERE approval_id = %s
    FOR UPDATE
    """,
    (approval_id,),
)
```
- **Transaction Scope**: The query executes inside `with pool.connection() as conn: with conn.cursor() as cur:`.
- **Row-Level Mutex**: The `FOR UPDATE` clause instructs PostgreSQL to acquire an exclusive row-level lock on the `process_approval_requests` record. Any concurrent transaction attempting to decide on the same `approval_id` blocks until the active transaction commits.
- **Terminal State Lock (`storage.py:2541-2545`)**:
  ```python
  if status != "PENDING":
      raise ApprovalError(
          f"Approval request '{approval_id}' has already been resolved with status '{status}' "
          "and cannot accept further decisions."
      )
  ```
- **Dynamic Quorum Calculation (`storage.py:2592-2616`)**:
  ```python
  cur.execute(
      "SELECT decision FROM process_approval_decisions WHERE approval_id = %s",
      (approval_id,),
  )
  all_decisions = [r[0] for r in cur.fetchall()]
  if decision_val == "REJECTED":
      new_status = "REJECTED"
      resolved_at = now
  elif decision_val == "APPROVED":
      approved_count = sum(1 for d in all_decisions if d == "APPROVED")
      if approved_count >= required_approvals:
          new_status = "APPROVED"
          resolved_at = now
  ```
  Quorum is computed from the database table `process_approval_decisions` under the row lock, never from in-memory arrays.

### 2.2 Cache-Through Engine Read in `approvals.py`

#### Read Cache Invalidation (`packages/atlas-process/src/atlas_process/approvals.py:230-238`):
```python
def get_approval(self, approval_id: str) -> ApprovalRequest | None:
    with self._lock:
        if self.storage and hasattr(self.storage, "get_approval"):
            appr = self.storage.get_approval(approval_id)
            if appr:
                self._approvals[approval_id] = appr
                return appr
        return self._approvals.get(approval_id)
```
- Previously, `get_approval()` returned `self._approvals.get(approval_id)` without querying storage if present.
- In Phase 16.6, `self.storage.get_approval(approval_id)` is invoked first on every read. If present in storage, the local process memory is updated with the authoritative database record.
- In `decide()` (`approvals.py:145-155`), decisions are delegated directly to `self.storage.decide_approval(...)`.

## 3. Concurrency & Fault Verification Scenarios

### Scenario 1: Multi-Node Approval Cache Divergence
- **Test File**: `tests/unit/test_phase16_6_approvals_concurrency.py::test_approval_multi_node_cache_consistency`
- **Execution**: Node A creates request requiring 2 approvals. Node B reads before any votes. Approver 1 votes on Node A. Approver 2 votes on Node B.
- **Observed Behavior**: Node B fetches authoritative state via row-lock, observes Approver 1's vote in storage, records Approver 2's vote, calculates 2 of 2 approvals, and transitions status to `APPROVED`.
- **Verdict**: **PASSED**.

### Scenario 2: Native PostgreSQL Row-Locked Multi-Worker Consensus
- **Test File**: `tests/integration/test_phase16_6_postgres_hardening.py::test_pg_16_6_02_approval_concurrency_row_locking`
- **Environment**: Native PostgreSQL 18.6 with live database socket connections.
- **Execution**: Two separate `HumanApprovalEngine` instances connected via `psycopg` pool. Approver 1 votes on Node 1; Approver 2 votes on Node 2.
- **Observed Behavior**: Both votes committed to `process_approval_decisions`. Status atomically resolved to `APPROVED`. Subsequent query on Node 1 returns `APPROVED`.
- **Verdict**: **PASSED**.

### Scenario 3: Terminal Rejection Preemption
- **Test File**: `tests/unit/test_phase16_6_approvals_concurrency.py::test_approval_terminal_rejection_preempts_across_nodes`
- **Observed Behavior**: Rejection on Node A immediately transitions request to `REJECTED`. Node B subsequent approval attempt is blocked with `ApprovalError("has already been resolved...")`.
- **Verdict**: **PASSED**.

### Scenario 4: Duplicate Vote Detection Across Nodes
- **Test File**: `tests/unit/test_phase16_6_approvals_concurrency.py::test_approval_duplicate_vote_rejection_across_nodes`
- **Observed Behavior**: Approver 1 votes on Node A. Approver 1 attempts to vote on Node B. Node B detects existing row in `process_approval_decisions` and raises `ApprovalError("already submitted a decision")`.
- **Verdict**: **PASSED**.

## 4. Audit Assessment & Closure Status

| Audit Criterion | Required Guarantee | Implementation Assessment | Status |
| :--- | :--- | :--- | :---: |
| **Row-Level Mutex** | Concurrent decisions serialized across nodes | `SELECT ... FOR UPDATE` verified in PostgreSQL | **VERIFIED** |
| **Dynamic Quorum** | Quorum calculated from DB table | Evaluated via `SELECT decision FROM process_approval_decisions` | **VERIFIED** |
| **Cache Linearizability** | No stale in-memory read returns | Cache-through `storage.get_approval()` on every read | **VERIFIED** |
| **Terminal Lock** | No votes accepted post-resolution | Verified `status != 'PENDING'` check | **VERIFIED** |
| **SoD & Tamper Check** | Evaluated under row lock | Verified before vote insertion | **VERIFIED** |

**FINDING-16.5-01 Final Status:** **VERIFIED CLOSED**

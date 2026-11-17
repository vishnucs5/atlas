# Phase 16.6 — Multi-Worker Approval Consistency & Row-Locked Quorum Resolution

## 1. Executive Summary

This document details the architectural remediation of **FINDING-16.5-01** (Multi-Worker Approval In-Memory Cache Divergence).

In Phase 16.5, the independent audit discovered that when multiple application instances connect to a shared PostgreSQL database, `HumanApprovalEngine` cached approval requests in local process memory (`self._approvals[approval_id]`). When Approver 1 submitted an approval decision on Worker Node 1 and Approver 2 submitted an approval decision on Worker Node 2:
- Worker Node 2 evaluated quorum solely against its local in-memory view (which held 0 prior votes).
- As a consequence, even though 2 votes existed in the relational database table `process_approval_decisions`, neither worker evaluated quorum to completion, leaving the workflow permanently stuck in `PENDING`.

## 2. Root Cause Analysis

1. **Local State Primacy**: `HumanApprovalEngine.get_approval()` returned `self._approvals.get(approval_id)` if present in process RAM, bypassing the persistent database without re-validating state freshness.
2. **Missing Transactional Mutex across Distributed Nodes**: Decisions were submitted locally, calculated quorum in Python memory, and only flushed to disk after decision calculation.
3. **Split-Brain Voting**: In clustered deployments (e.g. Kubernetes with multiple replicas), each pod operated on an isolated approval cache, violating cluster-wide linearizability.

## 3. Implemented Architecture & Remediation

### 3.1 Authoritative Relational Storage Resolution (`decide_approval`)

In `PostgresProcessStorage`, `SqliteProcessStorage`, and `InMemoryProcessStorage`, approval quorum calculation was moved directly into the persistence layer inside a row-level transaction:

```sql
SELECT approval_id, process_instance_id, task_def_id, action_name,
       target_resource, parameters, parameter_hash, requesting_identity,
       allowed_approver_ids, allowed_approver_roles, required_approvals,
       risk_classification, status, expires_at, created_at, resolved_at
FROM process_approval_requests
WHERE approval_id = %s
FOR UPDATE;
```

#### Atomic Verification Sequence under Row Lock:
1. **Row-Level Lock Acquisition**: `SELECT ... FOR UPDATE` locks the target approval row, serializing concurrent decisions across all cluster nodes.
2. **Terminal State Lock**: If status is already `APPROVED`, `REJECTED`, or `CANCELLED`, rejects the vote immediately with `ApprovalError("has already been resolved...")`.
3. **Expiration Check**: If current timestamp exceeds `expires_at`, marks request `EXPIRED` and raises `ApprovalExpiredError`.
4. **Duplicate Approver Check**: Queries `process_approval_decisions WHERE approval_id = %s AND approver_id = %s`. If a record exists, raises `ApprovalError("already submitted a decision")`.
5. **Vote Insertion**: Inserts the new decision vote into `process_approval_decisions` atomically.
6. **Dynamic Quorum Calculation**: Queries all recorded decisions for this approval ID:
   - If any decision is `REJECTED`, the status immediately transitions to `REJECTED` (permanent veto).
   - If total `APPROVED` decisions reach or exceed `required_approvals`, status transitions to `APPROVED` and records `resolved_at`.
   - Otherwise, status remains `PENDING`.
7. **Commit & Return**: The updated state is committed and returned to the caller.

### 3.2 Cache-Through Engine Delegation

In `packages/atlas-process/src/atlas_process/approvals.py`:
- `HumanApprovalEngine.get_approval(approval_id)` always attempts to read from `self.storage.get_approval(approval_id)` first, keeping local process memory in sync with authoritative database state.
- `HumanApprovalEngine.decide(...)` delegates directly to `self.storage.decide_approval(...)`. Process-local RAM serves strictly as a temporary scratchpad and is updated after database resolution.

## 4. Verification Evidence

1. **Unit Multi-Node Test**: `tests/unit/test_phase16_6_approvals_concurrency.py`
   - `test_approval_multi_node_cache_consistency`: PASSED (Node A and Node B vote independently; quorum successfully resolves to `APPROVED`).
   - `test_approval_terminal_rejection_preempts_across_nodes`: PASSED (Terminal rejection on Node A immediately preempts Node B).
   - `test_approval_duplicate_vote_rejection_across_nodes`: PASSED.
   - `test_approval_separation_of_duties_enforced`: PASSED.
   - `test_approval_parameter_tampering_rejected`: PASSED.
   - `test_approval_expiration_handling`: PASSED.

2. **Live PostgreSQL Integration Test**: `tests/integration/test_phase16_6_postgres_hardening.py`
   - `test_pg_16_6_02_approval_concurrency_row_locking`: PASSED against native PostgreSQL 18.6 with live row-level locks.

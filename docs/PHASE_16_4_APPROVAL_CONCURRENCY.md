# Phase 16.4 — Human Approval Concurrency, Quorum & Multi-Approver Persistence

## 1. Executive Summary

This document details the architectural remediation of **NEW-16.3-03** (Human Approval In-Memory Votes and Race Conditions).

In Phase 16.2, multi-person approval voting (`ApprovalRequest.decisions`) was held only in memory. When an approval required 2 of 3 managers to approve, a service restart after the 1st manager voted wiped that vote. The approval remained `PENDING`, but the first vote was gone, preventing legitimate quorum completion. Furthermore, `HumanApprovalEngine` lacked thread locking, exposing multi-approver workflows to race conditions.

## 2. Root Cause Analysis

1. **Unpersisted Votes Table**: Database migration `016_enterprise_process.sql` created table `process_approval_requests`, but did not persist individual approver decision votes into `process_approval_decisions`.
2. **Missing Concurrency Synchronization**: `HumanApprovalEngine.decide` executed without mutual exclusion, allowing concurrent requests from different approvers to interleave and overwrite each other's decisions.
3. **Missing Terminal Lock**: Decisions could theoretically be submitted after an approval had already reached terminal `APPROVED` or `REJECTED` status.

## 3. Implemented Remediation

### 3.1 Relational Approval Decisions Table
- In `PostgresProcessStorage` and `SqliteProcessStorage`:
  - `save_approval(approval)` persists the main request record to `process_approval_requests`.
  - Iterates over `approval.decisions` (`ApprovalRecord`) and inserts/updates each vote in `process_approval_decisions`:
    ```sql
    INSERT INTO process_approval_decisions (
        approval_id, approver_id, decision, decided_at, comments
    ) VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (approval_id, approver_id) DO UPDATE SET
        decision = EXCLUDED.decision,
        decided_at = EXCLUDED.decided_at,
        comments = EXCLUDED.comments;
    ```
  - `get_approval(approval_id)` queries `process_approval_requests` and joins all votes from `process_approval_decisions`, reconstructing `ApprovalRequest.decisions`.

### 3.2 Thread-Safe Quorum Engine
- Added `threading.RLock()` to `HumanApprovalEngine`.
- In `decide()`:
  1. Entire evaluation and write is guarded under `with self._lock:`.
  2. Fallback to `self.storage.get_approval(approval_id)` if request is not cached in RAM.
  3. Terminal State Lock: If `req.status != ApprovalDecision.PENDING`, immediately raise `ApprovalError`.
  4. Duplicate Check: If `any(d.approver_id == approver_id for d in req.decisions)`, raise `ApprovalError`.
  5. Quorum Calculation: Sum of all `ApprovalDecision.APPROVED` votes evaluated against `req.required_approvals`. Single `REJECTED` vote immediately transitions status to `REJECTED` (permanent veto).
  6. Atomic flush to `self.storage.save_approval(req)`.

## 4. Verification Evidence

- `tests/unit/test_phase16_4_approvals.py`: 8/8 passed.
- `tests/integration/test_phase16_4_postgres_full.py::test_pg_16_4_05_approval_quorum_persistence`: PASSED against native PostgreSQL.

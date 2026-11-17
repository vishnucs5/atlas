# ATLAS Phase 16.5 — Human Approval Concurrency & Quorum Audit

## 1. Executive Summary

This audit evaluated human approval lifecycle management, separation of duties, parameter tamper protection, and concurrent multi-party quorum voting in `HumanApprovalEngine` (`packages/atlas-process/src/atlas_process/approvals.py`) and PostgreSQL storage.

Finding `NEW-16.3-03` (unpersisted approval decisions lost upon engine restart) is **REMEDIATED** for single-node deployments. Decisions, timestamps, and comments are durably stored in PostgreSQL table `process_approval_decisions` with full restart survival.

However, an independent multi-process concurrency probe uncovered a **CRITICAL race condition in multi-worker / clustered deployments** caused by stale in-memory caching.

---

## 2. In-Process Security & Tamper Controls

In `HumanApprovalEngine`:
1. **Separation of Duties (SoD)**:
   `if approver_id == req.requesting_identity: raise SeparationOfDutiesViolationError`
   Requestors are strictly prohibited from approving their own actions.
2. **Parameter Tamper Resistance**:
   Approval requests compute a SHA-256 hash of their material parameters upon creation (`parameter_hash`). When deciding, `current_parameters` is re-hashed; any divergence raises `ParameterTamperedError`.
3. **Permanent Rejection Veto**:
   A single rejection vote by an authorized approver immediately transitions the request to `REJECTED`, locking it permanently against future overrides.
4. **Single-Process Thread Safety**:
   `self._lock = threading.RLock()` wraps all state evaluations and storage writes, preventing race conditions among threads within the same Python process.

---

## 3. Clustered Multi-Worker Concurrency Failure (Empirical Probe)

In enterprise deployments, multiple engine nodes run behind a load balancer (Scope C and Scope D).

An independent empirical probe was executed simulating two independent worker nodes (`Node A` and `Node B`) operating against the same PostgreSQL database:
- Required approvals: 2.
- Authorized approvers: `approver_1`, `approver_2`, `approver_3`.

### Probe Execution Steps:
1. `Node A` created an approval request (ID: `appr_...`, required=2).
2. `Node B` fetched/viewed the request via `get_approval()`, loading it into `Node B`'s in-memory `self._approvals` dictionary (with 0 votes).
3. `Approver 1` submitted an approval decision on `Node A`.
   - `Node A` recorded the vote, incremented `approved_count = 1`, and saved `status = PENDING` to PostgreSQL.
4. `Approver 2` submitted an approval decision on `Node B`.
   - `Node B` retrieved the request using `self.get_approval(appr_id)`.
   - Because `self._approvals.get(appr_id)` was found in memory, **`Node B` returned its stale cached object and did NOT query PostgreSQL!**
   - `Node B` appended `Approver 2`'s decision to its local copy.
   - `Node B` counted `approved_count = 1` (blind to `Approver 1`'s vote on `Node A`).
   - Because `1 < 2`, `Node B` set `status = PENDING`.
   - `Node B` executed `save_approval(req)`, issuing `UPDATE process_approval_requests SET status = 'PENDING'`.

### Empirical Probe Results
```text
Node B initial view decisions count: 0
Node A after approver 1 vote decisions count: 1 status: PENDING
Node B after approver 2 vote decisions count: 1 status: PENDING
Database final status: PENDING decisions count: 2
  - Vote by: approver_1 decision: APPROVED
  - Vote by: approver_2 decision: APPROVED
```

### Analysis of the Failure
1. **Silent Stalled Approvals**:
   Both required approvers voted `APPROVED`. Both votes were recorded in `process_approval_decisions`. However, the overall status in `process_approval_requests` is **permanently stuck in `PENDING`**!
2. **Root Cause**:
   In `HumanApprovalEngine.get_approval()`:
   ```python
   def get_approval(self, approval_id: str) -> ApprovalRequest | None:
       with self._lock:
           appr = self._approvals.get(approval_id)
           if not appr and self.storage and hasattr(self.storage, "get_approval"):
               appr = self.storage.get_approval(approval_id)
               if appr:
                   self._approvals[approval_id] = appr
           return appr
   ```
   The engine prioritizes its process-local cache over the database. In a multi-worker cluster, cache entries are never invalidated or synchronized.
3. **Database Concurrency Defect**:
   Even if the in-memory cache were removed, `PostgresProcessStorage.get_approval()` executes a plain `SELECT` without row-level locking (`FOR UPDATE`). Two simultaneous votes across nodes would still experience a write race.

---

## 4. Remediation Requirements for Clustered Deployment

To support multi-worker PostgreSQL deployments (Scope C) or multi-tenant deployments (Scope D):
1. **Eliminate Stale In-Memory Cache**: `HumanApprovalEngine` must fetch the latest approval request from persistent storage inside `decide()`, or implement distributed cache invalidation (e.g. Redis pub/sub or PostgreSQL `LISTEN/NOTIFY`).
2. **Row-Level Transactional Locking**: In `PostgresProcessStorage.decide_approval()`, acquire an exclusive lock:
   `SELECT ... FROM process_approval_requests WHERE approval_id = %s FOR UPDATE;`
   Evaluate quorum inside the database transaction before committing the final state.

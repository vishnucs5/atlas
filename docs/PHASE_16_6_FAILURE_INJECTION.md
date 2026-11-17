# Phase 16.6 — Failure Injection & Chaos Verification Report

## 1. Executive Summary

This report documents the rigorous failure injection testing conducted to verify ATLAS Phase 16.6 hardening under severe operational fault conditions, network partition simulations, concurrency races, and unexpected engine host terminations.

## 2. Failure Scenarios & Invariant Verification

### Scenario 1: Mid-Flight Host Crash During Non-Idempotent Bank Payout (`FINDING-16.5-02`)

- **Chaos Action**: A digital worker executes a high-value bank wire payout task (`task_payout`). The operation is marked `IN_PROGRESS` in the relational database. Mid-flight, the host process is violently terminated (simulating host crash / OOM kill / hardware failure).
- **Previous Unhardened Behavior**: Upon reboot, `recover_after_restart()` observed an expired lease and unconditionally reset the task status back to `READY`. A subsequent worker automatically launched the payout again, causing double disbursement.
- **Phase 16.6 Hardened Behavior**:
  1. Engine restarts and executes `recover_after_restart()`.
  2. Inspects `has_in_progress_operation(tenant_id, instance_id, task_def_id)` against authoritative durable storage.
  3. Finds the unconfirmed in-flight operation record.
  4. Calls `mark_task_operations_unknown()`, transitioning operation status to `UNKNOWN_OUTCOME` / `RECONCILIATION_REQUIRED`.
  5. Sets task status to `SUSPENDED` with error details: `"Operation outcome unknown after host crash. Reconciliation required before retry."`.
  6. Sets parent process instance status to `SUSPENDED`.
  7. Returns `recovered_count = 0` (task is NOT re-queued).
- **Verification Result**: **PASSED**. Confirmed in `test_restart_recovery_suspends_interrupted_operation` and `test_pg_16_6_04_durable_idempotency_and_crash_recovery_in_postgres`.

---

### Scenario 2: Dynamic DNS Rebinding Attack at TCP Connect Time (`FINDING-16.5-04`)

- **Chaos Action**: An external attacker targets an HTTP connector endpoint by configuring a domain `malicious-rebind.com` with TTL = 0. During the initial application URL check, the DNS resolver returns a benign public IP `93.184.216.34`. When `httpx` dials the socket, the attacker's authoritative DNS server responds with `169.254.169.254` (cloud metadata service).
- **Previous Unhardened Behavior**: The socket connection was initiated directly by the standard HTTP library, fetching private instance credentials from the metadata endpoint.
- **Phase 16.6 Hardened Behavior**:
  1. `PinnedResolutionNetworkBackend.connect_tcp` intercepts the connection attempt at the transport boundary.
  2. Resolves DNS at connection time and inspects all returned IPs against `SSRFValidator.is_ip_blocked()`.
  3. Detects `169.254.169.254` as an RFC 3927 link-local / cloud metadata address.
  4. Immediately aborts and raises `SSRFSecurityError: SSRF violation: Host 'malicious-rebind.com' resolves to blocked private/internal IP 169.254.169.254`.
  5. The underlying TCP socket is NEVER created or dialed.
- **Verification Result**: **PASSED**. Confirmed in `test_dns_rebinding_attack_prevented_at_connection_time`.

---

### Scenario 3: 10-Worker Initial Lease Storm on Brand-New Task (`FINDING-16.5-03`)

- **Chaos Action**: 10 worker threads simultaneously attempt to acquire the initial lease on a freshly scheduled task that has never had a row in `process_worker_leases`.
- **Previous Unhardened Behavior**: `SELECT ... FOR UPDATE` matched 0 rows, locking nothing. Multiple competing workers fell through to `INSERT (..., fencing_token=1)` and both received `fencing_token = 1`, resulting in concurrent execution.
- **Phase 16.6 Hardened Behavior**:
  1. All 10 workers execute `INSERT ... ON CONFLICT (task_instance_id) DO UPDATE SET fencing_token = process_worker_leases.fencing_token + 1 RETURNING fencing_token, lease_token`.
  2. PostgreSQL serializes the inserts through index lock arbitration.
  3. Each worker receives a strictly unique, monotonically increasing fencing generation token `1, 2, 3, 4, 5, 6, 7, 8, 9, 10`.
  4. Only the worker with `fencing_token = 10` is valid in the database; all other 9 workers fail subsequent lease checks (`verify_lease() == False`).
- **Verification Result**: **PASSED**. Confirmed across 10 threads in `test_concurrent_initial_lease_race_strictly_monotonic` and `test_pg_16_6_03_concurrent_initial_worker_leases_in_postgres`.

---

### Scenario 4: Concurrent Multi-Node Approval Voting & Stale Vote Attempt (`FINDING-16.5-01`)

- **Chaos Action**: Two independent application pods receive votes from different approvers. Approver Alice votes on Pod 1, then attempts to vote again on Pod 2. Approver Bob votes on Pod 2.
- **Previous Unhardened Behavior**: Pod 2 evaluated quorum using only its local in-memory votes (0), ignoring Alice's vote in PostgreSQL. Approvals required 2 votes but were stuck in `PENDING` forever.
- **Phase 16.6 Hardened Behavior**:
  1. Pod 1 acquires row lock via `SELECT ... FOR UPDATE`, records Alice's vote, and updates status to `PENDING` (1 of 2).
  2. When Alice attempts to vote again on Pod 2, Pod 2 locks the row, detects Alice's existing vote in `process_approval_decisions`, and rejects the submission with `ApprovalError("already submitted a decision")`.
  3. When Bob votes on Pod 2, Pod 2 locks the row, loads all recorded votes from storage (Alice + Bob = 2), evaluates quorum against `required_approvals = 2`, and transitions status to `APPROVED`.
  4. Any subsequent vote attempt on Pod 1 or Pod 2 is immediately rejected with `ApprovalError("has already been resolved...")`.
- **Verification Result**: **PASSED**. Confirmed in `test_approval_multi_node_cache_consistency` and `test_pg_16_6_02_approval_concurrency_row_locking`.

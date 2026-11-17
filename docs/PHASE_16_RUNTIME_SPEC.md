# ATLAS Phase 16 Runtime & Orchestration Specification

Details runtime execution semantics, durable checkpointing, worker leases, monotonic fencing tokens, and crash recovery.

## 1. Lifecycle Progression
- Processes start in `PENDING` and immediately transition to `RUNNING`.
- Initial tasks with no dependencies transition to `READY`.
- Workers claim `READY` tasks by acquiring a lease, moving the task to `RUNNING`.
- Task completion refreshes downstream dependencies. Once all tasks finish, process transitions to `COMPLETED`.
- Unhandled failure transitions the process to `FAILED` or `COMPENSATING`.

## 2. Worker Leases & Fencing Tokens
- Each acquired lease issues a unique lease token and a monotonically increasing `lease_fencing_token`.
- On task completion or failure reporting, the worker must submit its fencing token.
- If the token is less than the active token on the task instance, the commit is rejected with `StaleWorkerFencingError`.
- If the lease expired before commit, it is rejected with `LeaseExpiredError`.

## 3. Crash Recovery
- Upon process engine restart, `recover_after_restart()` scans all `RUNNING` instances.
- Tasks with expired worker leases are transitioned back to `READY` and unassigned, ready for pickup by active workers.

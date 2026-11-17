# ATLAS Worker Pool Recovery Runbook

## 1. Overview & Failure Modes

ATLAS digital workers operate as stateless worker nodes competing for atomic database task leases.
Primary failure scenarios:
1. Worker node out-of-memory (OOM) or hardware termination.
2. Worker process network partition or split-brain.
3. Slow worker lease expiration followed by late execution attempt.

---

## 2. Automatic Recovery Guarantees

1. **Heartbeat Expiry:** When a worker crashes, its heartbeat ceases. Within 30 seconds (default TTL), the lease record expires.
2. **Fencing Token Guard:** When a new worker acquires the lease, the database increments the fencing token (e.g. from 1 to 2). If the crashed worker recovers and attempts to complete the task, its submission with token 1 is strictly rejected.
3. **Double-Execution Guard:** Interrupted operations in `IN_PROGRESS` state are caught by engine restart recovery and suspended with `UNKNOWN_OUTCOME`.

---

## 3. Manual Operator Interventions

### Inspecting Crashed / Stalled Workers:
```bash
# List worker nodes and heartbeat health
kubectl get pods -l app=atlas-worker -n atlas-staging -o wide
```

### Forcing Lease Reclaim for Stalled Task:
If a task is blocked on a stalled worker whose lease has not expired:
```sql
UPDATE process_worker_leases
SET expires_at = NOW() - INTERVAL '1 second'
WHERE task_instance_id = 'ptask_target_id';
```

### Resuming a Suspended Reconciled Task:
Once an operator verifies with the downstream provider (e.g. ERP, payment gateway) that the operation succeeded or was safely cancelled:
```bash
# Mark operation as reconciled and resume instance
curl -X POST http://localhost:8000/api/v1/operations/reconcile \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "staging_pilot", "idempotency_key": "key_123", "resolved_status": "SUCCEEDED"}'
```

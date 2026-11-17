# ATLAS Phase 16.13 — Staging Canary Deployment & Validation Plan

## 1. Executive Summary & Gating Notice

As required by ATLAS Engineering Constitution Rule 2 (*Action Firewall*) and Rule 7 (*Deterministic Post-Condition Verification*), this staging canary plan establishes the operational blueprint for validating ATLAS Release Candidate v0.16.8 prior to enterprise production deployment.

> [!WARNING]
> **GOVERNANCE MANDATE:** Do not provision infrastructure, deploy container services, expose public endpoints, or issue real credentials without explicit, written human authorization. This document represents a staging preparation plan; execution is gated behind human governance approval.

---

## 2. Infrastructure & Environment Pre-Flight Verification

Before canary deployment commences, the staging infrastructure must be verified against the following checklist:

| Verification Area | Required Specification | Pre-Flight Status |
| :--- | :--- | :---: |
| **Compute Namespace** | Kubernetes v1.28+ namespace `atlas-staging-canary` | Prepared (Specs ready) |
| **Database Engine** | PostgreSQL 18.6+ dedicated staging instance with WAL archiving | Prepared |
| **Secret Management** | Synthetic secrets injected via Vault / SealedSecrets (`STAGING_KEY_*`) | Prepared |
| **Network Egress** | Strict Kubernetes `NetworkPolicy` blocking all outbound public internet | Prepared |
| **Worker Enrollment** | Restricted enrollment (maximum 2 worker pods with unique worker IDs) | Prepared |
| **Database Migrations** | Forward Migrations `001` through `018` verified in dry-run mode | Prepared |
| **Telemetry & Observability**| Prometheus scraping `atlas_` metrics every 5s; Grafana canary dashboard | Prepared |

---

## 3. Ten Elements of the Staging Canary Deployment

### 3.1 Isolated Staging Environment
- Deploy exclusively into Kubernetes namespace `atlas-staging-canary`.
- Dedicated PostgreSQL database: `atlas_staging_canary_db` (completely isolated from production or shared multi-tenant instances).
- Dedicated service accounts with zero IAM permissions to external cloud resources.

### 3.2 Dedicated Synthetic Tenant
- All canary workflows execute under tenant identifier `tenant_synthetic_canary`.
- Database queries enforce `tenant_id = 'tenant_synthetic_canary'`.
- Storage partitions and lease keys are strictly namespaced.

### 3.3 Restricted Worker Enrollment
- Canary fleet is capped at exactly **2 worker pods**:
  - `canary-worker-01`
  - `canary-worker-02`
- Worker pods enroll using distinct pre-shared worker tokens. Unauthorized worker registration is rejected.

### 3.4 Non-Destructive Synthetic Workflows
- Only non-destructive workflow definitions are permitted:
  - `canary_order_processing_v1`: Simulates customer order creation, mock credit validation, and automated fulfillment.
  - `canary_human_escalation_v1`: Simulates multi-vote approval pausing and escalation.
  - `canary_saga_reconciliation_v1`: Simulates step compensation and idempotency reconciliation.
- **Zero Real External Calls**: Connectors communicate exclusively with in-cluster synthetic mock servers (`http://mock-erp.atlas-staging-canary.svc.cluster.local`).

### 3.5 Synthetic Credentials & Key Isolation
- Webhook secret: `canary_synthetic_hmac_secret_2026`
- API Bearer Token: `canary_jwt_synthetic_operator_token`
- Database Credentials: Least-privilege user `atlas_canary_user` with access restricted to `atlas_staging_canary_db`.

### 3.6 Controlled Workload Progression
The canary workload runs over a structured 4-hour window:
1. **Hour 1 (Warmup):** 1 workflow/second (Single worker active; 50 total workflows).
2. **Hour 2 (Concurrency):** 5 workflows/second (Both workers active; lease contention testing).
3. **Hour 3 (Peak Load):** 10 workflows/second (50 concurrent workflows; connection pool saturation testing).
4. **Hour 4 (Cooldown & Replay):** Zero new workflows; verification of in-flight queue drain and audit log integrity.

### 3.7 Monitoring Metrics & Alert Thresholds
- **Process Start Latency P95**: $< 50\text{ ms}$
- **Approval Decision Latency P95**: $< 100\text{ ms}$
- **Task Dispatch Latency P95**: $< 20\text{ ms}$
- **Error Rate**: $< 0.01\%$ (Zero unhandled runtime exceptions)
- **Database Connection Pool Checkout**: $< 70\%$ of available pool capacity
- **Fencing Token Rejection Spike**: Alert if $> 2\text{ rejections/min}$ (indicates unexpected clock drift or starvation).

### 3.8 Failure-Injection Scenarios (Chaos Tests)
During Hour 2 and Hour 3, four controlled failure injections are triggered:
1. **Worker Crash Injection:** `kubectl delete pod canary-worker-01 --grace-period=0` while an in-flight non-idempotent task is executing. Verify that `canary-worker-02` recovers the task into `SUSPENDED` without duplicate execution.
2. **Network Delay Injection:** Inject 200ms latency to PostgreSQL using `tc/netem`. Verify connection pool health and query timeout handling.
3. **Duplicate Webhook Delivery:** Inject 10 duplicate webhook events within 100ms. Verify HMAC signature caching and single-event dispatch.
4. **Stale Fencing Token Commit:** Attempt a task write with an expired lease token. Verify that storage rejects the write with `StaleLeaseFenceError`.

### 3.9 Rollback Criteria (Emergency Abort Triggers)
The canary deployment must be immediately aborted and rolled back if ANY of the following occur:
- Any unhandled process crash resulting in data corruption or unrecoverable split-brain state.
- Process error rate exceeds $0.5\%$ over a 5-minute rolling window.
- Duplicate irreversible task execution detected in audit logs.
- Memory leak detected in worker pods (RAM growth $> 20\text{ MB/hour}$ sustained).
- Staging canary network egress violates policy (any attempt to connect to external IP addresses).

### 3.10 Canary Exit Criteria (Sign-Off Thresholds)
- [ ] 100% of planned canary workflows (minimum 1,000 instances) completed.
- [ ] All 4 failure-injection scenarios passed deterministically.
- [ ] Zero unhandled errors, zero duplicate operations, zero split-brain events.
- [ ] Emergency rollback runbook rehearsed and validated in the staging environment.
- [ ] Cryptographic audit log hash chain verified with zero tampering detected.

---

## 4. Execution Command Flow (Reference Only)

```bash
# 1. Pre-flight namespace and network isolation
kubectl apply -f deploy/staging/namespace.yaml
kubectl apply -f deploy/staging/network-policy-deny-egress.yaml

# 2. Database migration dry-run and apply
kubectl run canary-migration --image=ghcr.io/atlas/atlas-engine:0.16.8 \
  --namespace=atlas-staging-canary --restart=Never \
  -- env ATLAS_DATABASE_URL=$CANARY_DB_URL atlas-admin migrate up

# 3. Deploy Canary API & Worker fleet
helm upgrade --install atlas-canary ./helm/atlas-platform \
  --namespace atlas-staging-canary \
  --values deploy/staging/canary-values.yaml \
  --set image.tag=0.16.8 \
  --atomic --timeout 10m
```

---

## 5. Conclusion

This plan provides an airtight, non-destructive, and observable methodology for verifying ATLAS v0.16.8 in staging. Execution remains strictly paused awaiting explicit human authorization.

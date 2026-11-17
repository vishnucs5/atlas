# ATLAS Phase 16.13 — Staging Canary Acceptance Criteria & Verification Protocol

## 1. Executive Summary

This document defines the formal, quantitative, and qualitative acceptance criteria that must be satisfied during the execution of the ATLAS Phase 16.13 Staging Canary deployment.

Passing these criteria is the mandatory prerequisite for advancing from **Release Candidate v0.16.8** to **General Availability (GA) Production Rollout**.

---

## 2. Multi-Dimensional Acceptance Criteria Matrix

### 2.1 Category A: Pre-Deployment & Infrastructure Validation
| ID | Acceptance Criterion | Verification Method | Pass Threshold |
| :--- | :--- | :--- | :---: |
| **AC-PRE-1** | Clean schema migration execution | Run Migrations 001–018 against staging PostgreSQL 18.6 | Exit code 0, 0 table collisions |
| **AC-PRE-2** | Network egress lockdown | NetworkPolicy probe attempting outbound HTTP to public internet | 100% blocked (connection refused / timeout) |
| **AC-PRE-3** | Synthetic credential purity | Automated secret scanner inspecting environment & configs | 0 production secrets or keys |
| **AC-PRE-4** | Health probe readiness | HTTP GET `/healthz` and `/readyz` on API and worker pods | HTTP 200 OK within 15s of startup |

### 2.2 Category B: Functional & State Machine Invariants
| ID | Acceptance Criterion | Verification Method | Pass Threshold |
| :--- | :--- | :--- | :---: |
| **AC-FNC-1** | Workflow completion rate | Synthetic canary workload (minimum 1,000 instances) | $\ge 99.99\%$ success rate |
| **AC-FNC-2** | Durable idempotency preservation | Re-submitting completed/in-flight tasks with identical keys | 100% cached response, 0 double executions |
| **AC-FNC-3** | Canonical fingerprint mismatch detection | Re-submitting identical idempotency keys with modified payload | 100% rejected with `CanonicalArgumentFingerprintMismatch` |
| **AC-FNC-4** | Multi-worker lease fencing | Concurrently acquiring expired worker leases | Stale worker rejected with monotonic fence check |
| **AC-FNC-5** | Quorum-based approval decision | Multi-party human approval workflow with quorum threshold | Exactly 1 state transition, 0 race conditions |
| **AC-FNC-6** | Tenant data boundary enforcement | Attempting cross-tenant queries from `tenant_synthetic_canary` | 100% query isolation, 0 records returned |

### 2.3 Category C: Performance & Scalability Upper Bounds
| ID | Acceptance Criterion | Target Metric | Staging Pass Boundary |
| :--- | :--- | :--- | :---: |
| **AC-PRF-1** | Process initialization latency | P95 latency | $\le 50\text{ ms}$ |
| **AC-PRF-2** | Task dispatch latency | P95 latency | $\le 20\text{ ms}$ |
| **AC-PRF-3** | Approval state transition latency | P95 latency | $\le 100\text{ ms}$ |
| **AC-PRF-4** | Worker crash recovery sweep | Total recovery time | $\le 5.0\text{ s}$ |
| **AC-PRF-5** | PostgreSQL connection pool utilization | Maximum pool saturation | $\le 75\%$ under 50 concurrent workflows |
| **AC-PRF-6** | Memory footprint stability | Worker RSS memory growth | $< 20\text{ MB/hour}$ sustained |

### 2.4 Category D: Chaos & Failure Injection Resiliency
| ID | Acceptance Criterion | Injected Failure | Required System Response |
| :--- | :--- | :--- | :--- |
| **AC-CHS-1** | Hard worker termination (`SIGKILL`) | Kill `canary-worker-01` during active task execution | Surviving worker recovers instance into `SUSPENDED`; zero uncommitted double writes. |
| **AC-CHS-2** | PostgreSQL transient latency | Inject 200ms latency on database socket via `netem` | Connection pool absorbs delay; operations complete or retry without process crash. |
| **AC-CHS-3** | Duplicate webhook assault | Burst of 10 identical webhook deliveries within 100ms | 1st event processed; remaining 9 rejected with `DuplicateEventError`. |
| **AC-CHS-4** | Stale worker write attempt | Stale worker awakes after lease expiry and attempts commit | Storage rejects commit via fencing token check (`StaleLeaseFenceError`). |

### 2.5 Category E: Auditability, Compliance & Rollback
| ID | Acceptance Criterion | Verification Method | Pass Threshold |
| :--- | :--- | :--- | :---: |
| **AC-AUD-1** | Merkle hash chain integrity | Cryptographic verification of all audit event transitions | 100% valid SHA-256 chain, 0 broken links |
| **AC-AUD-2** | Telemetry and alerting coverage | Prometheus metric emission check across all 8 core metrics | Zero missing metric streams |
| **AC-AUD-3** | Staging rollback rehearsal | Execute `PRODUCTION_ROLLBACK_RUNBOOK.md` in staging | System cleanly reverts to base revision in $< 5\text{ min}$ |
| **AC-AUD-4** | Database Point-in-Time Recovery | Verify WAL archive restore and dump integrity check | 100% data restored, 0 corruption errors |

---

## 3. Formal Sign-Off Protocol

Upon completion of the staging canary deployment, all criteria must be validated and signed off by the governance triad:

```
[ ] Lead Architect:                ____________________    Date: __________
[ ] Security Operations Lead:      ____________________    Date: __________
[ ] Release Incident Commander:    ____________________    Date: __________
```

If ANY criterion fails to achieve the pass threshold, the canary is marked **CANARY FAIL**, emergency rollback is executed, and production promotion is blocked.

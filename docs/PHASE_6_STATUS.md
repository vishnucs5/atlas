# ATLAS Phase 6 Status Tracker: Production Hardening & Release Readiness

**Target Branch:** `feat/phase-6-production-hardening`  
**Base Commit (Phase 5):** `06b5cdb`  
**Current Status:** **IN PROGRESS (M0 Baseline Audit & Architecture Setup)**  
**Start Date:** 2026-11-13  
**Passing Tests:** **230 / 230** (100% Green baseline)  
**Code Quality:** Ruff Linting & Formatting 100% Clean across all 181 files

---

## Phase 6 Milestone Progress Ledger

| Milestone | Subsystem / Scope | Status | Assigned Target | Commit Hash |
|---|---|:---:|---|:---:|
| **M0** | Phase 5 Acceptance Audit & Baseline Verification | **COMPLETED** | `PHASE_6_PLAN.md`, `PHASE_6_STATUS.md`, `PHASE_6_RISK_REGISTER.md`, M0 Audit | `ff07700` |
| **M1** | Security Hardening (Auth, RBAC, Exact Approvals, SSRF, Filesystem, Threat Model) | **COMPLETED** | `atlas-api/auth.py`, `firewall.py`, `approval_manager.py`, `SECURITY_THREAT_MODEL.md` | `902f769` |
| **M2** | Reliability Engineering (Subprocess crash, fencing, DB locks, side-effect safety, backup/restore) | **COMPLETED** | `action_ledger.py`, `recovery.py`, `backup.py`, fault injection tests | `bb583fa` |
| **M3** | Performance & Scalability (Benchmarks, queue backpressure, quotas, rate limiting) | **COMPLETED** | `atlas-agent/runtime.py`, `atlas-api`, benchmark scripts | `008a932` |
| **M4** | Production Deployment (Docker Compose multi-service, Windows worker Session 0 check, .env.example) | **COMPLETED** | `compose.yaml`, `Dockerfile`, Windows worker guides | `eee7a6b` |
| **M5** | Observability & Operations (Structured logs, Prometheus metrics, audit events, dashboards) | NOT STARTED | `atlas-observability`, `/metrics`, `/dashboard` | - |
| **M6** | Release Readiness & 28-Scenario Acceptance Suite | NOT STARTED | 28 acceptance scenarios, `CHANGELOG.md`, `PHASE_6_ACCEPTANCE_REPORT.md` | - |

---

## 28 Required Acceptance Scenarios Checklist

- [x] **Scenario 01:** Unauthorized API request is rejected (401).
- [x] **Scenario 02:** Unauthorized user cannot access another user's task (403/404).
- [x] **Scenario 03:** Viewer role cannot execute privileged actions (403).
- [x] **Scenario 04:** Worker authentication is validated.
- [x] **Scenario 05:** Expired approval is rejected.
- [x] **Scenario 06:** Modified action parameters invalidate approval.
- [x] **Scenario 07:** Approval cannot be replayed or reused.
- [x] **Scenario 08:** Private-network SSRF attempt is blocked.
- [x] **Scenario 09:** Redirect to a prohibited destination is blocked.
- [x] **Scenario 10:** Filesystem path traversal is blocked.
- [x] **Scenario 11:** Symlink escape is blocked.
- [x] **Scenario 12:** Destructive terminal command requires appropriate authorization.
- [x] **Scenario 13:** Secrets are redacted from logs, traces, and events.
- [x] **Scenario 14:** Sensitive input is not exposed in artifacts.
- [x] **Scenario 15:** Worker crash is detected and recovered.
- [x] **Scenario 16:** Stale worker cannot commit (fencing token rejection).
- [x] **Scenario 17:** Duplicate action delivery is idempotent and safe.
- [x] **Scenario 18:** Unknown external action outcome is reconciled before retry.
- [x] **Scenario 19:** Database backup restores successfully with data integrity.
- [x] **Scenario 20:** Graceful shutdown preserves task consistency and releases resources.
- [x] **Scenario 21:** Concurrent tasks respect resource limits and bounded concurrency.
- [x] **Scenario 22:** Queue overload applies backpressure (429 / 503).
- [ ] **Scenario 23:** API and dashboard show consistent task and worker state.
- [ ] **Scenario 24:** Event stream reconnects without losing required sequenced events.
- [x] **Scenario 25:** Windows interactive worker validates its desktop execution session (non-Session 0).
- [x] **Scenario 26:** Clean deployment starts successfully from scratch.
- [x] **Scenario 27:** Database migration and rollback procedures work reliably.
- [x] **Scenario 28:** Full previous-phase regression suite passes (Phases 1–5).

---

## Active Risks & Blockers

- See [`docs/PHASE_6_RISK_REGISTER.md`](PHASE_6_RISK_REGISTER.md) for full risk inventory and mitigations.

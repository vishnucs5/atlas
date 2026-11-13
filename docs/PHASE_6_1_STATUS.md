# ATLAS Phase 6.1 Status Tracker: PostgreSQL Integration & Audit

**Target Branch:** `feat/phase-6-production-hardening`  
**Base Commit (Phase 6):** `86b4cb2`  
**Current Status:** **IN PROGRESS (Milestone 0 Completed)**  
**Start Date:** 2026-11-13  
**Passing Tests Baseline:** **285 / 285** (100% Green baseline)  

---

## Phase 6.1 Milestone Progress Ledger

| Milestone | Subsystem / Scope | Status | Assigned Target | Commit Hash |
|---|---|:---:|---|:---:|
| **M0** | Audit, Baseline Verification & Phase 6.1 Plan | **COMPLETED** | `PHASE_6_1_PLAN.md`, `PHASE_6_1_STATUS.md`, Repository Audit | `342bd61` |
| **M1** | PostgreSQL Storage Backend (`PostgresStorage`, connection pooling, transactions, migrations) | **COMPLETED** | `packages/atlas-storage/src/atlas_storage/postgres.py`, API injection | `0bebf9f` |
| **M2** | Live PostgreSQL Integration Test Suite (15 scenarios against native PostgreSQL) | **COMPLETED** | `tests/integration/test_postgres_storage_e2e.py` | `f83b960` |
| **M3** | PostgreSQL Backup & Restore Engine, SHA-256 sidecars & Operations Guide | **COMPLETED** | `packages/atlas-storage/src/atlas_storage/backup.py`, `docs/POSTGRESQL_OPERATIONS.md` | `021f0c7` |
| **M4** | Adversarial Security Verification & Residual Threat Audit | **COMPLETED** | `tests/unit/test_security_adversarial.py`, `docs/SECURITY_THREAT_MODEL.md` | `dab0348` |
| **M5** | Reproducible Performance Benchmarks & Clean Deployment Verification | **PENDING** | Benchmark scripts, latency/throughput comparisons, deployment stack test | *pending* |
| **M6** | Release Readiness, Changelog & Final Phase 6.1 Acceptance Report | **PENDING** | `docs/PHASE_6_1_ACCEPTANCE_REPORT.md`, `docs/CHANGELOG.md` | *pending* |

---

## PostgreSQL Integration Acceptance Criteria

- [ ] **PG-01:** `PostgresStorage` implements `TaskStoreProtocol`, `EventStoreProtocol`, `CheckpointStoreProtocol`, `ActionLedgerStoreProtocol`, `WorkerStoreProtocol`.
- [ ] **PG-02:** Connection pooling via `psycopg_pool.ConnectionPool` with configurable min/max size and timeouts.
- [ ] **PG-03:** Schema auto-creation and migration management with idempotent initialization.
- [ ] **PG-04:** Strict transaction management with automatic rollback on error.
- [ ] **PG-05:** Atomic task state transitions and optimistic concurrency checking (`OptimisticLockError`).
- [ ] **PG-06:** Event sequence integrity and unique constraint collision rejection (`SequenceCollisionError`).
- [ ] **PG-07:** Worker leases with monotonic fencing token generation rejection (`StaleWorkerError`).
- [ ] **PG-08:** Action ledger idempotency deduplication and UNKNOWN state safety (`NonIdempotentActionUncertaintyError`).
- [ ] **PG-09:** Checkpoint persistence with SHA-256 integrity hash verification and corruption rollback.
- [ ] **PG-10:** Clear startup failure when PostgreSQL database is configured but unreachable (zero silent SQLite fallback).
- [ ] **PG-11:** Live PostgreSQL integration test suite passing against physical PostgreSQL instance.
- [ ] **PG-12:** Documented and executable PostgreSQL backup procedure with SHA-256 sidecars.
- [ ] **PG-13:** Documented and executable PostgreSQL restore procedure into clean database with data integrity validation.
- [x] **PG-14:** Adversarial security suite passing (DNS rebinding, SSRF redirects, Windows UNC, approval tampering, secret redaction).
- [ ] **PG-15:** Reproducible performance benchmark comparing SQLite and PostgreSQL under identical workloads.
- [ ] **PG-16:** Complete stack clean deployment verification with PostgreSQL.
- [ ] **PG-17:** Comprehensive operations guide (`docs/POSTGRESQL_OPERATIONS.md`).
- [ ] **PG-18:** Full regression suite passes across monorepo (100% green).

# ATLAS Storage Performance Benchmarks & Deployment Verification

**Document Version:** 1.0.0  
**Phase:** Phase 6.1 — PostgreSQL Production Integration & Independent Release Audit  
**Date:** 2026-11-13  
**Status:** Executed & Verified  
**Automated Test Suite:** `tests/integration/test_storage_benchmarks.py`

---

## 1. Executive Summary

This benchmark evaluates the storage backends of ATLAS under identical, deterministic production workloads:
1. **SQLite (`SQLiteStorage`):** Embedded single-node ACID storage with WAL journal mode.
2. **PostgreSQL (`PostgresStorage`):** Multi-node distributed enterprise storage using `psycopg_pool.ConnectionPool` and native PostgreSQL 18.

Both backends implement all five core storage contracts: `TaskStoreProtocol`, `EventStoreProtocol`, `CheckpointStoreProtocol`, `ActionLedgerStoreProtocol`, and `WorkerStoreProtocol`.

---

## 2. Benchmark Environment & Methodology

- **Host Operating System:** Microsoft Windows 11 Enterprise (x86_64)
- **Python Runtime:** Python 3.11.9 (`.venv`)
- **PostgreSQL Version:** PostgreSQL 18.6 (native binary cluster via `embedded-postgres`)
- **Connection Pool Configuration:**
  - Min Connections: 2
  - Max Connections: 10
  - Connection Timeout: 10.0s
- **Timing Instrument:** High-resolution monotonic clock (`time.perf_counter()`)
- **Repeatability:** Every benchmark runs within a dedicated, isolated cluster instance created in ephemeral storage.

---

## 3. Benchmark Results

### 3.1. Task Creation & Persistence Throughput (100 Sequential Inserts)

Measures single-record task insertion and state persistence over 100 sequential operations.

| Backend | Operations | Total Duration (ms) | Throughput (ops/sec) | Production SLA | Assessment |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **SQLite (WAL)** | 100 | 4.0 ms | **24,925.85** | > 100 ops/sec | **EXCEEDED (249x)** |
| **PostgreSQL (Pool)** | 100 | 52.3 ms | **1,910.77** | > 100 ops/sec | **EXCEEDED (19x)** |

*Observation:* SQLite operates with zero IPC/socket overhead, achieving sub-millisecond local in-process writes. PostgreSQL with client-side connection pooling delivers ~1,900 ops/sec, far exceeding the 100 ops/sec production threshold.

---

### 3.2. Execution Event Append Latency Percentiles (150 Sequential Events)

Measures the latency distribution of incremental event logging on an active task.

| Backend | Events | p50 Latency (ms) | p90 Latency (ms) | p99 Latency (ms) | SLA Target | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **SQLite (WAL)** | 150 | 0.033 ms | 0.068 ms | **0.099 ms** | p99 < 50 ms | **PASS** |
| **PostgreSQL** | 150 | 0.393 ms | 0.607 ms | **4.545 ms** | p99 < 50 ms | **PASS** |

*Observation:* PostgreSQL maintains a tight p50 latency under 0.4 ms and a p99 latency of 4.5 ms on local TCP sockets, satisfying the stringent sub-50ms audit criteria for real-time action telemetry.

---

### 3.3. Checkpoint Creation & Cryptographic Integrity Verification (50 Snapshots)

Measures point-in-time state checkpoint persistence, JSON serialization, and SHA-256 seal verification.

| Operation | Backend | Snapshots | Duration (ms) | Throughput (ops/sec) | Status |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Checkpoint Write & Seal** | PostgreSQL | 50 | 48.5 ms | **1,029.91 ops/sec** | **PASS** |
| **Checkpoint Read & Verify** | PostgreSQL | 50 | 23.3 ms | **2,145.11 ops/sec** | **PASS** |

*Observation:* Every retrieved checkpoint was verified cryptographically via `verify_hash()`. Zero corruptions, zero hash mismatches.

---

### 3.4. Multi-Worker Concurrency Scaling (5 Threads Interleaving)

Evaluates lease acquisition, fencing token validation, concurrent event appending, and lease renewal across 5 concurrent workers operating simultaneously on distinct tasks.

- **Concurrent Threads:** 5
- **Events per Worker:** 20
- **Total Operations:** 110 (5 lease acquisitions + 100 event appends + 5 lease renewals)
- **Total Duration:** **0.045 seconds**
- **Effective Concurrency Throughput:** **2,456.14 ops/sec**
- **Data Integrity:** 100% of events stored without sequence collisions or deadlocks.
- **Relational Integrity:** Foreign key enforcement strictly verified against `worker_registry`.

---

## 4. Full-Stack Deployment Verification

The complete application stack was booted with `ATLAS_DATABASE_URL` pointing to the native PostgreSQL instance and tested via `TestClient(app)`:

1. **Liveness & Readiness Probes:**
   - `GET /readyz` returned `HTTP 200 OK` with `components: {"api": "ok", "storage": "ok"}`.
   - `GET /api/v1/status` returned `HTTP 200 OK` with `status: "ok"`.
2. **Task REST Lifecycle:**
   - `POST /api/v1/tasks` successfully accepted a task payload, initialized runtime execution, and returned `HTTP 201 Created`.
   - `GET /api/v1/tasks/{id}` retrieved the persisted task from PostgreSQL.
   - `GET /api/v1/tasks` returned paginated task lists.
3. **Observability:**
   - `GET /metrics` exported valid Prometheus metrics including `atlas_active_tasks`.
4. **Graceful Lifespan Shutdown:**
   - On application exit, `lifespan` closed the `PostgresStorage` connection pool cleanly with zero leaked connections and zero dangling socket warnings.
   - Post-shutdown verification confirmed that task data remained durably written to PostgreSQL.

# Known Issues & Architectural Constraints

This document records known constraints, architectural limitations, technical debt, and tracked mitigations within ATLAS.

---

## 1. Concurrency Constraints in SQLite Storage

### Description
SQLite allows multiple concurrent readers in WAL (Write-Ahead Logging) mode, but only a single active writer at any instant. Under high write contention, transactions may experience `sqlite3.OperationalError: database is locked`.

### Mitigation
- All SQLite database connections must set `PRAGMA busy_timeout = 5000;`.
- SQLite is designated for local single-node development, CLI tasks, and testing.
- High-concurrency enterprise deployments target PostgreSQL via `atlas-storage` interfaces.

---

## 2. Windows Path Length Limits (MAX_PATH)

### Description
On Windows 11, standard Win32 APIs historically impose a maximum path length of 260 characters (`MAX_PATH`). Deep monorepo nesting or complex task artifact paths can approach or exceed this limit.

### Mitigation
- Use Python's `pathlib.Path` consistently across all packages.
- Ensure the Windows registry key `LongPathsEnabled` is verified via `atlas doctor`.
- For deeply nested storage paths, normalize paths with the extended path prefix (`\\?\`) where appropriate.

---

## 3. Secret Masking Regex Performance at High Throughput

### Description
Scanning every log message with multiple regex patterns for secrets (OpenAI, Anthropic, AWS, bearer tokens) introduces processing overhead if performed naively on multi-megabyte payloads.

### Mitigation
- Pre-compile all regex patterns at package initialization in `atlas-observability`.
- Apply fast substring heuristic checks (e.g., checking for `sk-`, `ey`, `bearer`, `password`) before executing full regex scans on large payloads.
- Truncate excessively large payload attributes before applying regex masking.

---

## 4. Cross-Platform Process Management

### Description
Terminating subprocesses cleanly varies between operating systems. On Windows, terminating a parent process does not automatically terminate its child process tree unless explicitly killed with process tree flags (`taskkill /T /F`) or Job Objects. On Unix, process groups (`os.killpg`) are required.

### Mitigation
- Abstract process lifecycle management behind a cross-platform execution driver interface in `atlas-core`.
- Provide platform-specific process group termination adapters in driver packages.

---

## 5. Event Store Schema Evolution

### Description
In event-sourced systems, historical events in the database are immutable. As domain models evolve, new schema versions must coexist with older event payloads.

### Mitigation
- All event payloads include a mandatory `schema_version = "1.0"` attribute.
- Event deserializers must support upcasting / migration adapters when schema upgrades occur in later phases.

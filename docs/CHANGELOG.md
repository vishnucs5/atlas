# Changelog

All notable changes to the ATLAS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.9.0] - 2026-11-14 — Phase 9 Distributed Execution Network

### Added
- **Distributed Execution Network Package (`packages/atlas-distributed`)**:
  - Full UV workspace member with clean architectural boundaries.
  - `models.py`: Domain contracts for `WorkerPlatform`, `SessionType`, `WorkerHardware`, `WorkerCapabilities`, `EnrollmentToken`, `EnrollmentRequest`, `EnrollmentResponse`, `WorkerIdentity`, `AssignmentPayload`, `AssignmentStatus`, `AssignmentResult`, `WorkerHeartbeat`, `AssignmentProgress`, `ProtocolMessageType`, and `ProtocolEnvelope`.
  - `enrollment.py`: `WorkerEnrollmentAuthority` managing cryptographic provisioning tokens, tenant scoping, mutual authentication, credential rotation, and Certificate/Publisher Revocation Lists (CRL). Includes Windows Session 0 protection invariant (`SessionZeroInteractiveError`).
  - `worker.py`: `WorkerAgent` daemon runtime supporting outbound-only control plane connectivity, platform/session detection, driver execution bridge (`ComputerDriver`), telemetry heartbeat loop, cancellation propagation, and an in-memory `EventRingBuffer` buffering up to 1,000 events during network disconnects and replaying in arrival order upon reconnection.
  - `scheduler.py`: `DistributedScheduler` implementing 9-dimensional resource matching (OS platform, Windows Session 0 guard, session type, drivers, browsers, CPU/RAM/GPU capacity, security tags, tenant boundaries, and concurrency caps), least-loaded fairness load balancing, priority queuing with backpressure throttling (`SchedulerQueueFullError`), and monotonic fencing token lease allocation.
  - `protocol.py`: Remote Execution Protocol v1 (`ATLAS-REP/1.0`) implementation with canonical JSON serialization, HMAC-SHA256 frame signatures, timestamp TTL clock drift validation, and replay attack prevention with `MessageDeduplicator`.
  - `coordinator.py`: `DistributedTaskCoordinator` providing multi-worker DAG partitioning, parallel branch dispatch, synchronization barriers, and deliverable/artifact aggregation into `DistributedExecutionSummary`.
  - `fault_tolerance.py`: `DistributedRecoveryManager` handling heartbeat timeout detection, dead-worker eviction, monotonic fencing token validation rejecting stale completions (`StaleWorkerError`), side-effect safety halting blind retries of non-idempotent actions in `UNKNOWN` status (`NonIdempotentActionUncertaintyError`), and deterministic external state reconciliation (`reconcile_external_action`).
- **REST API Routes (`apps/api/src/atlas_api/routes/distributed.py`)**:
  - `POST /api/v1/distributed/tokens`: Create cryptographic provisioning token.
  - `POST /api/v1/distributed/enroll`: Mutual authenticated worker enrollment.
  - `POST /api/v1/distributed/workers/{worker_id}/heartbeat`: Ingest telemetry heartbeat.
  - `POST /api/v1/distributed/workers/{worker_id}/revoke`: Administrative worker revocation.
  - `GET /api/v1/distributed/workers`: List enrolled workers with redacted credentials.
  - `GET /api/v1/distributed/workers/{worker_id}`: Retrieve worker detail.
  - `POST /api/v1/distributed/assignments`: Schedule assignment across eligible workers.
  - `POST /api/v1/distributed/assignments/{assignment_id}/progress`: Ingest streaming progress events.
  - `POST /api/v1/distributed/assignments/{assignment_id}/complete`: Ingest completion result and validate fencing generation.
  - `POST /api/v1/distributed/reconcile`: Reconcile physical external outcome for in-doubt actions.
  - `GET /api/v1/distributed/fleet/metrics`: Aggregated fleet capacity, health, and queue depth.
- **Operator Dashboard Integration (`apps/api/src/atlas_api/routes/dashboard.py`)**:
  - Added 4th main navigation tab: `Distributed Fleet & Remote Nodes`.
  - Distributed Fleet Overview with live stats (Total Workers, Active, Busy, Disconnected, Queue Depth).
  - Worker Fleet Table with live status, session type badges (Session 0 Guarded vs Interactive Desktop), drivers, and revocation controls.
  - Provisioning Token Generator panel with tenant isolation controls.
  - Unknown Outcome Reconciliation panel for deterministic operator recovery.
- **Verification & Acceptance Test Suite**:
  - `tests/integration/test_phase9_acceptance.py`: Comprehensive 30-scenario test suite covering all Phase 9 acceptance criteria (DN-01 through DN-30) (100% green).
  - `tests/unit/test_worker_enrollment.py`: 7 unit tests covering enrollment authority, tokens, and CRL.
  - `tests/unit/test_worker_agent.py`: 9 unit tests covering daemon execution, session 0 guard, and ring buffer.
  - `tests/unit/test_distributed_scheduler.py`: 8 unit tests covering multi-dimensional matching and backpressure.
  - `tests/unit/test_remote_protocol.py`: 8 unit tests covering ATLAS-REP/1.0 framing, HMAC signing, and replay defense.
  - `tests/unit/test_distributed_coordinator.py`: 3 unit tests covering DAG multi-worker coordination and barriers.
  - `tests/unit/test_distributed_fault_tolerance.py`: 4 unit tests covering dead-worker eviction, fencing, and reconciliation.
  - Full monorepo regression baseline: **495 / 495 tests passing (100% green)**.

---

## [0.8.0] - 2026-11-13 — Phase 8 Autonomous Workflow Marketplace & Skill Ecosystem

### Added
- **Workflow Marketplace Package (`packages/atlas-marketplace`)**:
  - Full UV workspace member with clean architectural boundaries.
  - `models.py`: Canonical Pydantic schemas for `WorkflowPackage`, `PackageManifest`, `WorkflowGraphDefinition`, `WorkflowNodeDefinition`, `PublisherIdentity`, `PermissionDeclaration`, `PermissionScope`, and `ResourceLimits`.
  - `package.py`: Package builder and unpacker with Kahn's DAG cycle detection (`validate_workflow_dag_cycles`), SHA-256 integrity hashing (`calculate_sha256`), and detached cryptographic signatures (`sign_payload`, `verify_payload_signature`).
  - `resolver.py`: Semantic Versioning dependency resolver with caret (`^`), tilde (`~`), wildcard (`*`), and comparison range constraint satisfaction, topological resolution, cycle detection (`CircularDependencyError`), and version conflict rejection (`IncompatibleDependencyError`).
  - `registry.py`: `MarketplaceRegistry` backend supporting multi-tenant package publishing, semantic search, capability/tag filtering, pagination, package versioning, installation tracking, atomic rollback (`rollback_package`), deprecation, withdrawal, and publisher revocation (`revoke_publisher`).
  - `executor.py`: `WorkflowExecutor` compiling declarative package workflow DAGs into canonical ATLAS `TaskGraph` instances, gating all declared actions through `ActionFirewall`, and executing via `AgentSupervisor` with `IndependentReviewer` deliverable audits.
  - `security.py`: `PackageSecurityScanner` enforcing supply chain protection, privilege escalation detection (`PrivilegeEscalationError`), prompt injection defense (`UntrustedInstructionError`), and forbidden OS system call rejection in sandboxed code (`SecurityViolationError`).
- **Skill SDK Package (`packages/atlas-skills`)**:
  - Full UV workspace member providing developer framework for specialist skills.
  - `models.py`: Pydantic models for `SkillManifest`, `SkillParameter`, `SkillCapability`, and `SkillResult`.
  - `base.py`: Extensible `BaseSkill` class with lifecycle hooks (`on_load`, `on_unload`), typed input validation (`validate_inputs`), timeout enforcement, cancellation handling, and structured invocation logging (`SkillLogger`).
  - `builtins.py`: Built-in specialist skills:
    - `CodeLinterSkill`: AST parsing and syntax analysis.
    - `DataAnalysisSkill`: Statistical computation (mean, min, max, sum, count).
    - `TextSummarizerSkill`: Multi-sentence extractive summarization.
- **FastAPI REST API Routes (`apps/api/src/atlas_api/routes/marketplace.py`)**:
  - `GET /api/v1/marketplace/packages`: Search and filter marketplace packages with pagination.
  - `POST /api/v1/marketplace/packages`: Publish signed packages or JSON manifests with automatic verification.
  - `GET /api/v1/marketplace/packages/{package_id}`: Retrieve package specification and latest release.
  - `GET /api/v1/marketplace/packages/{package_id}/versions`: Version history ledger.
  - `POST /api/v1/marketplace/packages/{package_id}/install`: Transitive dependency resolution and installation.
  - `POST /api/v1/marketplace/packages/{package_id}/rollback`: Atomic version rollback.
  - `POST /api/v1/marketplace/packages/{package_id}/uninstall`: Clean package removal.
  - `GET /api/v1/marketplace/installations`: List active workspace package installations.
  - `GET /api/v1/marketplace/skills`: List specialist skills.
  - `POST /api/v1/marketplace/workflows/{package_id}/execute`: Execute workflow package via ATLAS multi-agent runtime.
  - `POST /api/v1/marketplace/security/scan`: Supply chain security scan API.
  - `GET /api/v1/marketplace/publishers/{publisher_id}`: Publisher identity profile.
  - `POST /api/v1/marketplace/publishers/{publisher_id}/revoke`: Revoke publisher credentials.
- **Embedded Operator Dashboard Marketplace Integration (`apps/api/src/atlas_api/routes/dashboard.py`)**:
  - Embedded single-page control plane updated to support 14 distinct marketplace screens:
    1. Marketplace Overview
    2. Workflow Discovery
    3. Skill Discovery
    4. Workflow Detail
    5. Skill Detail
    6. Package Version History
    7. Publisher Profile
    8. Installation Management
    9. Installed Skills
    10. Installed Workflows
    11. Visual Workflow Builder (interactive graph node editor)
    12. Package Publishing
    13. Security and Permission Review
    14. Organization Registry Administration
- **Integration Test Suite (`tests/integration/test_phase8_acceptance.py`)**:
  - Complete 20-scenario deterministic verification suite (MP-01 through MP-20) achieving 100% green pass rate.

---

## [0.7.0] - 2026-11-13 — Phase 7 Multi-Agent Intelligence & Autonomous Orchestration

### Added
- **Multi-Agent Orchestration Package (`packages/atlas-orchestration`)**:
  - Full workspace member integrated into UV workspace with clean dependency boundaries to `atlas-core`, `atlas-policy`, `atlas-storage`, and `atlas-coordination`.
- **Core Multi-Agent Contracts (`packages/atlas-core`) (M1)**:
  - Agent capability taxonomy: `RESEARCH`, `BROWSER`, `DESKTOP`, `CODE`, `DATA_ANALYSIS`, `QUALITY_ASSURANCE`, `SUPERVISOR`, `GENERAL`.
  - Pydantic models for `AgentDescriptor`, `AgentLease`, `AgentBudget` with token/step utilization tracking, and lease fencing tokens.
- **Agent Registry (`AgentRegistry`) (M1)**:
  - Dynamic specialist registration, capability discovery, heartbeat liveness tracking, and lease acquisition with fencing tokens.
  - Concurrency caps (`max_concurrent_tasks`) and strict budget caps (`AgentBudgetExhaustedError`).
- **Task Graph Engine (`TaskGraphEngine`) (M2)**:
  - Versioned dependency DAG model (`TaskGraph`, `TaskNode`) supporting sequential, parallel, and conditional dependencies.
  - Cycle detection using Kahn's algorithm (`CyclicDependencyError`) and topological batch scheduling (`get_execution_batches`).
  - Cascading failure cancellation and dynamic DAG replanning (`replan`).
- **Inter-Agent Communication Protocol (`AgentMessageRouter`) (M3)**:
  - Typed envelopes (`AgentMessage`, `AgentMessageType`) with cryptographic message IDs, correlation IDs, and timestamps.
  - Replay prevention via deduplication registry (`DuplicateMessageError`).
  - Strict TTL deadline enforcement (`ExpiredMessageError`).
  - Circular delegation prevention with cycle detection and depth capping (`CircularDelegationError`).
  - Cross-task communication barriers preventing unauthorized context leakage (`UnauthorizedCrossTaskCommunicationError`).
- **Scoped Shared Memory Engine (`SharedMemoryEngine`) (M3)**:
  - Three-tier memory scoping: `TASK_SCOPED`, `AGENT_SCOPED`, and `PROJECT_SCOPED`.
  - Role-based access control and agent privacy isolation (`MemoryAccessDeniedError`).
  - Untrusted external web content marking (`is_untrusted`) and prompt sanitization preventing indirect prompt injection attacks.
  - Structured text context summarization (`summarize_task_context`) for model prompt injection.
- **Specialist Agents Suite (`SpecialistAgent`) (M4)**:
  - Modular specialist implementations: `ResearchSpecialist`, `BrowserSpecialist`, `DesktopSpecialist`, `CodingSpecialist`, `DataAnalysisSpecialist`, and `QASpecialist`.
  - Mandatory policy firewall gating (`ActionFirewall.evaluate()`) on all computer actions; raises `PolicyViolationError` on blocked domains/actions.
  - Strict budget enforcement preventing runaway token consumption.
- **Agent Supervisor, QA Reviewer & Recovery Manager (M5)**:
  - `AgentSupervisor`: Hierarchical 3-stage task decomposition (Research -> Code -> QA), parallel batch execution, and cancellation propagation.
  - `IndependentReviewer`: Deterministic verification of deliverables, evidence, and completed state (`ReviewVerdict.APPROVED` vs `REJECTED`).
  - Structured replanning and review rejection gates (`ReviewRejectionError`).
  - `MultiAgentRecoveryManager`: Crash detection, expired lease eviction, subtask reassignment, and strict non-idempotent action uncertainty safety (`NonIdempotentActionUncertaintyError`).
- **FastAPI Orchestration Endpoints & Dashboard Integration (M6)**:
  - REST endpoints under `/api/v1/orchestration`:
    - `GET /api/v1/orchestration/agents`
    - `POST /api/v1/orchestration/agents`
    - `POST /api/v1/orchestration/tasks`
    - `GET /api/v1/orchestration/tasks/{task_id}/graph`
    - `GET /api/v1/orchestration/tasks/{task_id}/messages`
    - `GET /api/v1/orchestration/tasks/{task_id}/memory`
    - `POST /api/v1/orchestration/tasks/{task_id}/cancel`
  - Operator Dashboard integration: Multi-agent fleet table, DAG dispatch interface, and active specialist counter.
- **Comprehensive End-to-End Acceptance Test Suite (M6)**:
  - 20 deterministic acceptance scenarios in `tests/integration/test_phase7_acceptance.py` achieving 100% green rate.
  - Monorepo regression suite: 376 tests passing across Phases 1–7.

---

## [0.6.1] - 2026-11-13 — Phase 6.1 PostgreSQL Production Integration & Independent Release Audit

### Added
- **Full Operational PostgreSQL Backend (`PostgresStorage`) (M1)**:
  - Enterprise implementation conforming to all 5 storage protocols: `TaskStoreProtocol`, `EventStoreProtocol`, `CheckpointStoreProtocol`, `ActionLedgerStoreProtocol`, and `WorkerStoreProtocol`.
  - High-performance connection pooling via `psycopg_pool.ConnectionPool` with configurable min/max bounds and timeout controls.
  - Strict atomic transactions, optimistic locking with monotonic versioning (`OptimisticLockError`), unique event sequence collision rejection (`SequenceCollisionError`).
  - Worker lease fencing tokens with generation enforcement (`StaleWorkerError`) and foreign key validation against registered workers.
  - Checkpoint persistence with SHA-256 integrity verification (`CorruptedCheckpointError`).
  - Action ledger idempotency deduplication with UNKNOWN state protection (`NonIdempotentActionUncertaintyError`).
  - API lifespan storage injection: dynamically boots `PostgresStorage` when `ATLAS_DATABASE_URL` is set, failing fast without silent SQLite substitution.
- **Native PostgreSQL Integration Test Suite (M2)**:
  - 14 live end-to-end integration test scenarios running on native physical PostgreSQL via `embedded-postgres` binary cluster (`tests/integration/test_postgres_storage_e2e.py`).
  - Verifies DDL idempotency, optimistic concurrency, sequence rollback, lease fencing, checkpoint tamper detection, and cross-tenant isolation.
- **PostgreSQL Backup & Disaster Recovery Engine (M3)**:
  - Online database dump and restore utilities (`create_postgres_backup`, `verify_postgres_backup`, `restore_postgres_backup`, `clean_old_backups`) supporting native `pg_dump`/`psql` binaries and logical SQL fallback.
  - SHA-256 metadata sidecars, database password scrubbing (`_sanitize_dsn`), pre-restore validation, and post-restore table row assertions.
  - Comprehensive operations manual: `docs/POSTGRESQL_OPERATIONS.md`.
- **Adversarial Security Hardening (M4)**:
  - 10 adversarial attack scenarios tested and verified (`tests/unit/test_security_adversarial.py`): DNS rebinding, multi-hop redirect SSRF, IPv6 loopback/link-local/ULA/mapped addresses, Windows SMB UNC paths, directory traversal, approval tampering, approval replay, API bearer token revocation, and concurrent approval race conditions.
  - Enhanced secret redaction engine with URI password scrubber (`://user:pass@host`).
  - Updated `docs/SECURITY_THREAT_MODEL.md` (v1.1.0) with residual threat analysis and verification matrix.
- **Reproducible Performance Benchmarks & Clean Deployment Verification (M5)**:
  - Benchmark test suite (`tests/integration/test_storage_benchmarks.py`) and performance report (`docs/BENCHMARKS.md`).
  - Task insertion throughput: SQLite ~24,900 ops/sec; PostgreSQL ~1,910 ops/sec.
  - Event append latency percentiles: SQLite p99 0.099ms; PostgreSQL p99 4.545ms (well under the 50ms SLA).
  - Checkpoint sealing: PostgreSQL 1,029 writes/sec and 2,145 reads/sec.
  - Concurrency scaling: 5 parallel workers achieving 2,456 concurrent ops/sec.
  - Clean deployment lifecycle: FastAPI startup, health/readiness, REST API operations, Prometheus metrics, and leak-free graceful shutdown verified on PostgreSQL.

---

## [0.6.0] - 2026-11-13 — Phase 6 Production Hardening, Security & Release Readiness Release

### Added
- **Security Hardening & Threat Defense (M1)**:
  - Cryptographically bound approvals (`ApprovalManager`): SHA-256 parameter hashing and cryptographic action signatures binding task ID, action ID, canonical parameters, risk level, and policy version.
  - Parameter tampering detection (`ApprovalSecurityError`) and atomic single-use consumption lock (`consumed = True`) preventing replay attacks.
  - Multi-tier SSRF filter (`ActionFirewall`): DNS socket resolution, loopback (`127.0.0.0/8`, `::1`), private RFC1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), and cloud metadata blocking (`169.254.169.254`, `metadata.google.internal`).
  - Redirect hop inspection (`validate_redirect`) preventing SSRF pivoting across HTTP redirects.
  - Filesystem containment (`ArtifactManager`): Blocking Windows UNC paths (`\\server\share`, `//server/share`), blocking Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), symlink escape protection, and zip bomb decompression guards (`safe_extract_archive`).
  - Timing attack defense: Constant-time API key verification (`hmac.compare_digest`), dynamic token revocation registry (`revoke_token`), token expiration, and cross-user private task isolation.
  - Comprehensive threat model: Authored `docs/SECURITY_THREAT_MODEL.md` under STRIDE methodology.
- **Reliability Engineering & Disaster Recovery (M2)**:
  - Online live SQLite backup and restore utilities (`create_sqlite_backup`, `verify_sqlite_backup`, `restore_sqlite_backup`) with SHA-256 metadata sidecars and page integrity validation.
  - External side-effect safety: Non-idempotent actions in `UNKNOWN` state cannot be blindly retried without explicit reconciliation (`NonIdempotentActionUncertaintyError`).
  - Worker crash resilience and monotonic fencing tokens (`StaleWorkerError`).
  - Corrupted checkpoint detection and automated rollback to last verified state (`rollback_to_last_valid`).
- **Performance, Scalability & Backpressure (M3)**:
  - Task queue backpressure: Bounded queue capacity (`max_queue_depth`) rejecting saturated submissions with `QueueBackpressureError` and RFC6585 HTTP 429 Too Many Requests (`Retry-After: 5`).
  - Execution timeouts (`task_timeout_seconds`) with clean transition to `FAILED` and resource teardown.
  - Verified persistence throughput (> 200 tasks/sec) and low latency.
- **Production Deployment & Environment (M4)**:
  - Updated multi-service `compose.yaml` with PostgreSQL database service (`atlas-postgres`), API server, worker pool, healthchecks, and persistent volumes.
  - Windows interactive worker verification: `DesktopDriver.validate_interactive_session()` guarding against Windows Session 0 service isolation.
  - Environment template `.env.example` documenting all configuration keys.
- **Observability & Operations (M5)**:
  - Prometheus metrics exposition (`/metrics`): thread-safe `MetricsRegistry` reporting `atlas_tasks_total`, `atlas_action_executions_total`, `atlas_policy_evaluations_total`, `atlas_queue_backpressure_rejections_total`, `atlas_active_workers`, `atlas_pending_approvals`, and `atlas_active_tasks`.
  - Structured JSON audit logging and multi-pattern secret scrubbing.
  - Verified real-time state consistency across API, Dashboard, and SSE stream.
- **Release Readiness & Acceptance Suite (M6)**:
  - Complete 28-scenario acceptance suite (`tests/integration/test_phase6_acceptance.py`) covering all Phase 6 requirements with 100% pass rate.
  - Updated documentation: `docs/PHASE_6_STATUS.md`, `docs/PROJECT_STATUS.md`, `docs/IMPLEMENTATION_PLAN.md`, and `docs/PHASE_6_ACCEPTANCE_REPORT.md`.

---

## [0.5.0] - 2026-11-12 — Phase 5 Production Runtime Integration & Orchestration Release

### Added
- **Unified Production Runtime (`packages/atlas-agent`)**:
  - `ProductionRuntime` conforming to `AtlasRuntime` protocol, orchestrating the full 14-state task state machine without skipping intermediate states (`CREATED` $\to$ `QUEUED` $\to$ `PLANNING` $\to$ `READY` $\to$ `RUNNING` $\to$ `WAITING_APPROVAL` $\leftrightarrow$ `RUNNING` $\to$ `VERIFYING` $\to$ `COMPLETED`).
  - Integrated coordination of `StructuredPlanner`, `ModelRouter`, `ContextManager`, `ActionFirewall`, `ApprovalManager`, `WorkerScheduler`, `DriverRegistry`, `VerificationEngine`, `CheckpointManager`, `RecoveryCoordinator`, and `SQLiteStorage`.
  - Air-gapped / CI execution resilience: automatic `HermeticFallbackAdapter` fallback when zero external LLM API credentials are provided.
- **Multi-Driver Abstraction & Desktop Automation (`packages/atlas-browser`)**:
  - `DriverRegistry` enabling capability-based dynamic routing to `PlaywrightBrowserDriver` and `DesktopDriver`.
  - `DesktopDriver` implementing `ComputerDriver` with cross-platform window management, pointer/keyboard actions, accessibility extraction, and display capture.
  - Native Windows interactive session automation with primary monitor resolution auto-detection via `user32.GetSystemMetrics`, native application process spawning and lifecycle management, cursor positioning, and clean resource teardown.
- **Human-in-the-Loop Approval Workflow (`packages/atlas-coordination`)**:
  - `ApprovalManager` pausing tasks in `WAITING_APPROVAL` whenever high-risk actions are proposed, resuming on approval and cancelling on rejection.
  - Expiration monitoring and deterministic status transitions (`PENDING`, `GRANTED`, `DENIED`, `EXPIRED`).
- **Secure Artifact Storage (`packages/atlas-coordination`)**:
  - `ArtifactManager` with directory traversal protection, size quotas, and recursive secret scrubbing (`redact_secrets`) across screenshots, DOM snapshots, logs, and downloads.
- **Production REST API & Operator Dashboard (`apps/api`)**:
  - Comprehensive endpoints for tasks, approvals, workers, artifacts, checkpoints, and health.
  - Role-Based Access Control (RBAC) supporting `admin`, `operator`, `worker`, and `viewer` roles via header-based API keys.
  - Real-time Server-Sent Events (SSE) streaming (`/api/v1/events/stream`) with sequence-based replay and secret redaction.
  - Embedded single-page web Operator Dashboard (`/dashboard`) displaying live task status, worker fleet health, approval inbox, and real-time event logs.
- **Background Worker Daemon & CLI Operations (`apps/cli`)**:
  - Standalone worker daemon (`atlas worker run`) with registration, heartbeat loop, lease fencing, and capability discovery.
  - CLI task lifecycle commands (`atlas task create`, `atlas task cancel`, `atlas task list`).
  - CLI approval commands (`atlas approval list`, `atlas approval grant`, `atlas approval deny`).
- **End-to-End Test Suite, Docker Deployment & Demonstration (`tests/integration`, `scripts/`, Docker)**:
  - Full end-to-end integration test (`tests/integration/test_production_e2e.py`) verifying the complete production lifecycle with approvals.
  - Multi-stage `Dockerfile` with Playwright Chromium browser bundle.
  - Multi-service `compose.yaml` orchestrating API server, worker pool, shared volumes, health checks, and restart policies.
  - Standalone executable demonstration script (`scripts/demo_production_runtime.py`).
  - Architectural ADR: [ADR-0008](adr/0008-production-runtime-integration.md).

---

## [0.4.0] - 2026-11-12 — Phase 4 Durable Execution & Recovery Infrastructure Release

### Added
- **Core Durable Contracts (`packages/atlas-core`)**:
  - `Checkpoint` schema with cryptographic SHA-256 seal computation (`compute_hash()`, `seal()`, `verify_hash()`), step progress, action lists, environment metadata, and fencing generation.
  - `WorkerRecord` and `WorkerLease` with monotonic fencing tokens and status tracking (`IDLE`, `BUSY`, `DRAINING`, `DISCONNECTED`, `TERMINATED`).
  - `ActionExecutionRecord` with tri-state tracking and safe `UNKNOWN` outcome handling.
  - `FailureClassification`, `RecoveryStrategy`, `ReconciliationDecision`, and `ReconciliationResult`.
  - Zero third-party dependencies in `atlas-core` (Constitution Rule 3).
- **Durable Storage & Fencing Persistence (`packages/atlas-storage`)**:
  - SQLite persistence with WAL mode, foreign keys, and busy timeout for `checkpoints`, `action_ledger`, `worker_registry`, and `worker_leases`.
  - Atomic commit-time fencing token validation rejecting stale worker writes with `StaleWorkerError`.
  - Documented PostgreSQL production storage DDL and specifications.
- **Control Plane Coordination Package (`packages/atlas-coordination`)**:
  - `CheckpointManager` supporting transactional creation, SHA-256 integrity verification, tamper detection, corruption rollback, and recursive secret sanitization (`redact_secrets`).
  - `WorkerRegistryManager` with capability discovery, heartbeats, draining, and stale worker sweep.
  - `WorkerLeaseManager` for exclusive task lease allocation and commit-time fencing token assertion.
  - `WorkerScheduler` providing capability-aware task assignment without OS coupling.
  - `ActionLedger` tracking execution lifecycle, deduplicating idempotent actions, and blocking blind retry of non-idempotent actions in `UNKNOWN` state.
  - `EnvironmentReconciler` comparing live browser URL and DOM against checkpoint expectations before resumption.
  - `RecoveryCoordinator` orchestrating the 8-stage recovery lifecycle ($\text{DETECT} \to \text{RECORD}$) gated by `ActionFirewall` with bounded retry limits.
  - `ExecutionReplayEngine` supporting time-travel state reconstruction at sequence $N$, sanitized audit timeline export, and checkpoint divergence detection.
- **20-Scenario Fault-Injection Test Suite & Demonstration (`tests/integration`, `scripts/`)**:
  - `tests/integration/test_fault_recovery_e2e.py` verifying recovery from 20 real-world failure modes 100% offline (20/20 PASS).
  - Standalone executable demonstration script `scripts/demo_durable_recovery.py`.
  - Architectural ADR: [ADR-0007](adr/0007-durable-execution-and-recovery.md).

---

## [0.3.0] - 2026-11-12 — Phase 3 Model Provider Adapters & Planning Engine Release

### Added
- **Core Model & Tool Contracts (`packages/atlas-core`)**:
  - Pydantic v2 domain schemas (`ModelRequest`, `ModelResponse`, `ModelMessage`, `TextPart`, `ImagePart`, `ModelCapabilities`, `ToolDefinition`, `ToolCall`, `TokenUsage`, `ProviderHealth`, `ModelError`).
  - Zero third-party SDK dependencies in `atlas-core` (Constitution Rule 3 verified via isolated subprocess tests).
- **Universal Model Adapter Framework (`packages/atlas-models`)**:
  - `ModelAdapter` abstract base protocol with async `complete()`, `stream()`, `health_check()`, and `get_capabilities()`.
  - Concrete normalized adapters for:
    1. OpenAI (`OpenAIAdapter`)
    2. Anthropic Claude (`AnthropicAdapter`)
    3. Google Gemini (`GeminiAdapter`)
    4. Ollama (`OllamaAdapter`)
    5. OpenAI-Compatible local inference endpoints (`OpenAICompatibleAdapter`)
  - Normalized multimodal input, tool/function calling, and token usage accounting.
  - Safe credential masking (`mask_credential`) preventing API key leaks in logs and exceptions.
- **Resilient Model Router (`packages/atlas-models`)**:
  - `ModelRouter` with capability-based filtering (`vision`, `tools`, `min_context_window`).
  - Per-adapter `CircuitBreaker` with 3-state tracking (`CLOSED`, `OPEN`, `HALF_OPEN`).
  - Exponential backoff with jitter on 429 rate limit responses.
  - Per-task and global token usage and USD cost tracking via `CostTracker`.
- **Autonomous Planning & Agent Engine (`packages/atlas-agent`)**:
  - `StructuredPlanner` producing typed `ExecutionPlan` with `PlanStep` sequence, driver schema validation, and dynamic bounded replanning (`max_replans=3`).
  - `ContextManager` with sliding window pruning, token budgeting, and compact `DOMSummarizer` generating clean interactive element markup.
  - Prompt injection defense via strict `<untrusted_external_content>` XML demarcation.
  - `SafetyEngine` with action idempotency hashing (breaks infinite loops after 3 consecutive identical actions) and hard resource ceilings (`max_steps`, `max_tokens`, `max_cost_usd`, `timeout_seconds`).
  - `AutonomousAgentLoop` orchestrating the 11-step execution cycle: Observe $\to$ Build Context $\to$ Ask Model $\to$ Validate $\to$ Propose Action $\to$ Check Policy $\to$ Request Approval $\to$ Execute Driver $\to$ Verify Post-Condition $\to$ Record SQLite Events $\to$ Replan/Continue.
- **Integration Test Suite & Verification (`tests/integration`, `scripts/`)**:
  - `tests/integration/test_autonomous_agent_e2e.py` verifying multi-turn login workflow and Action Firewall denial recovery.
  - Standalone executable demonstration script `scripts/demo_autonomous_agent.py`.
  - Architectural ADRs: [ADR-0005](adr/0005-model-provider-adapter-architecture.md) and [ADR-0006](adr/0006-autonomous-planning-and-execution-loop.md).
  - Final acceptance report in `docs/roadmap/PHASE_3_ACCEPTANCE_REPORT.md`.

---

## [0.2.0] - 2026-11-12 — Phase 2 Browser Execution Runtime Release

### Added
- **Browser Execution Driver (`packages/atlas-browser`)**:
  - `PlaywrightBrowserDriver` implementing the core `ComputerDriver` protocol with Chromium automation.
  - Isolated browser context creation with per-session cookies, cache, viewport settings, and health check monitoring.
  - `BrowserActionExecutor` supporting `browser.navigate`, `browser.click`, `browser.type`, `browser.fill`, `browser.select`, `browser.scroll`, `browser.press_key`, `browser.wait`, `browser.upload`.
  - Resilient locator resolution supporting accessible roles (`page.get_by_role`), text matching, placeholder, labels, test IDs, CSS, XPath, and coordinate clicking.
  - `DownloadManager` intercepting download events, preventing directory traversal, computing SHA-256 checksums, and logging file sizes.
  - `NetworkMonitor` capturing HTTP request/response metrics, status codes, and console errors.
- **Multimodal Observation Engine (`packages/atlas-observation`)**:
  - `extract_dom_snapshot` and `extract_interactive_elements` for structured DOM evaluation.
  - `extract_accessibility_tree` using Chromium CDP `Accessibility.getFullAXTree` with fallback to semantic DOM ARIA walking.
  - `capture_screenshot` and `capture_observation` generating base64-encoded PNG screenshots and structured `Observation` domain models.
- **Deterministic Verification Engine (`packages/atlas-verification`)**:
  - `VerificationEngine` evaluating declarative post-conditions against live browser state with async polling.
  - Post-condition matchers: `element_visible`, `element_hidden`, `text_present`, `url_matches`, `file_downloaded`, `value_equals`.
- **Core Runtime Driver Contracts (`packages/atlas-core`)**:
  - `ComputerDriver` abstract protocol and `DriverHealth` model in `atlas_core.runtime.driver`.
  - Browser runtime exception hierarchy (`DriverError`, `NavigationTimeoutError`, `ElementNotFoundError`, `DetachedElementError`, `BrowserCrashError`, `ActionExecutionError`).
- **Developer CLI Extensions (`apps/cli`)**:
  - `atlas doctor` extended with Playwright Chromium driver availability check.
  - `atlas environment test browser` CLI diagnostic command verifying headless Chromium launch and connectivity.
- **Hermetic Synthetic Test Fixtures (`tests/fixtures`)**:
  - Local HTTP `SyntheticServer` serving deterministic test pages (`/`, `/login`, `/interactive`, `/upload`, `/download`).
  - End-to-end integration test (`test_browser_runtime_e2e.py`) validating the full ATLAS lifecycle without external network dependencies.

---

## [0.1.0] - 2026-11-12 — Phase 1 Foundation & Core Lifecycle Release

### Added
- **Monorepo Architecture & Governance**:
  - Root monorepo workspace configuration using `uv` (`pyproject.toml`) linking packages (`atlas-core`, `atlas-storage`, `atlas-policy`, `atlas-observability`) and applications (`apps/api`, `apps/cli`).
  - Code style and linting configuration in `ruff.toml` targeting Python 3.11+.
  - Comprehensive `.gitignore` filtering out bytecode, test caches, virtual environments, and SQLite databases.
  - Engineering Constitution (`AGENTS.md`) enforcing 8 mandatory rules for contributors and AI agents.
  - Documentation suite: `ARCHITECTURE.md`, `DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `PROJECT_STATUS.md`, `TEST_RESULTS.md`, `KNOWN_ISSUES.md`.
  - Foundational Architectural Decision Records (ADRs):
    - `0001-monorepo-and-runtime-ownership.md`
    - `0002-event-sourced-task-persistence.md`
    - `0003-action-firewall-policy-separation.md`

- **Core Domain & State Machine (`packages/atlas-core`)**:
  - Zero-dependency Pydantic v2 data contracts with schema versioning (`"1.0"`) covering `TaskRequest`, `Task`, `ComputerAction`, `ActionTarget`, `ActionResult`, `ExecutionEvent`, `Observation`, `Session`, `Checkpoint`, `Model`, `Policy`.
  - Explicit 14-state Task State Machine enforcing strict transition rules and raising `InvalidStateTransitionError` on illegal moves.
  - Execution event emission hooks and runtime protocol definitions.

- **Action Firewall & Policy Engine (`packages/atlas-policy`)**:
  - Action firewall evaluation pipeline with `ALLOW`, `REQUIRE_APPROVAL`, and `DENY` decision types.
  - Risk classification (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - Destructive command pattern filters blocking catastrophic shell commands (`rm -rf /`, `mkfs`, format, fork bombs, PowerShell recursive deletion).
  - Domain security policies with allowlists, blocklists, wildcard matching, and fail-closed denial on malformed or unparseable URLs.

- **Contextual Observability & Structured Logging (`packages/atlas-observability`)**:
  - RFC-compliant structured JSON logging formatter with contextual attributes (`task_id`, `session_id`, `step_id`).
  - Async context propagation using Python `contextvars` and scoped context managers.
  - High-performance regex and key-based credential masking for OpenAI, Anthropic, Google AI, AWS, Bearer tokens, passwords, and PEM private keys.

- **Event-Sourced Storage Engine (`packages/atlas-storage`)**:
  - SQLite storage engine with WAL journal mode (`PRAGMA journal_mode=WAL`), busy timeout (5000ms), and foreign key integrity.
  - Append-only `execution_events` table guaranteeing monotonic sequence numbering per task.
  - Materialized `tasks` view with optimistic concurrency control (`expected_state`).
  - Concurrency safety with multi-connection WAL readers and transactional rollback on failure.
  - Abstract PostgreSQL storage interface specification.

- **FastAPI Service (`apps/api`)**:
  - Production FastAPI application with modular routers and lifespan management.
  - Liveness endpoint (`/health`, `/healthz`), readiness probe (`/readyz` with SQLite connection check), and detailed status (`/api/v1/status`).
  - Graceful degradation returning HTTP 503 when backing storage is unavailable.

- **Developer CLI Suite (`apps/cli`)**:
  - Click-powered `atlas` CLI command suite.
  - `atlas doctor`: Environment verification (Python 3.11+, SQLite WAL support, OS environment).
  - `atlas init`: Automated workspace initialization and database schema provisioning.
  - `atlas task`: Task lifecycle management (`create`, `list`, `inspect` with sensitive data redaction).

- **CI Matrix & Verification Suite (`.github/workflows/ci.yml`)**:
  - Cross-platform GitHub Actions matrix running on Windows 11 and Ubuntu across Python 3.11 and Python 3.12.
  - Enforced quality gates: Ruff linting (`uv run ruff check .`), Ruff formatting check (`uv run ruff format --check .`), and Pytest test suite (`uv run pytest -v`).
  - 97 automated unit and integration tests passing with 100% pass rate.
  - Complete verification of all 14 Phase 1 acceptance criteria (14/14).

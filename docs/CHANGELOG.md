# Changelog

All notable changes to the ATLAS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.15.0] - 2026-11-16 — Phase 15 Federated Autonomous Intelligence Network & Global Agent Interoperability

### Added
- **Federated Cryptographic Identity & Trust Model (`packages/atlas-federation/src/atlas_federation/identity.py`)**:
  - `ParticipantIdentity`: Hierarchical participant and agent identities formatted as standard URNs (`urn:atlas:org:...:inst:...:agent:...`).
  - `FederationCredentials`: Ed25519-signed credentials with scoped capabilities and cryptographic validity intervals.
  - `FederationIdentityManager`: Mutual authentication, seamless credential rotation, real-time revocation registry, and pairwise trust policy enforcement (`TRUSTED`, `DISCOVERY_ONLY`, `PROBATION`, `BLOCKED`).
- **Capability Registry & Discovery Engine (`packages/atlas-federation/src/atlas_federation/discovery.py`)**:
  - `FederatedCapabilityRegistry`: Multi-agent discovery supporting four-tier visibility scoping (`PRIVATE`, `ORGANIZATION`, `FEDERATION`, `PUBLIC`).
  - Zero-leak metadata sanitizer: Automatically strips sensitive keys (tokens, passwords, secrets, prompts) from published advertisements.
- **Versioned Agent Messaging Protocol (`packages/atlas-federation/src/atlas_federation/protocol.py`)**:
  - `FederationProtocolEngine`: Envelope encryption and Ed25519 HMAC signatures with correlation tracking.
  - Nonce-based replay defense with sliding TTL windows (`ReplayAttackDetectedError`) and clock-skew guards (`ExpiredMessageError`).
  - Idempotent duplicate message handling returning cached results without redundant execution.
- **Cross-Instance Task Delegation Engine (`packages/atlas-federation/src/atlas_federation/delegation.py`)**:
  - `CrossInstanceDelegationEngine`: Structured task contract negotiation, execution lease issuance, and local Action Firewall authorization gates.
  - Independent post-condition verification (Constitutional Invariant Rule 7): Rejects unverified remote claims and enforces evidence integrity (`InvalidResultEvidenceError`).
- **External Agent Interoperability Adapters (`packages/atlas-federation/src/atlas_federation/external_adapters.py`)**:
  - `MCPAdapter`: Translates external Model Context Protocol (`tools/list`, `tools/call`) requests into ATLAS internal actions with mandatory Action Firewall inspection.
  - `WebhookAdapter`: Ingests HTTP webhook triggers with constant-time HMAC-SHA256 signature verification (`X-Atlas-Signature`) and generates signed async callbacks.
- **Federated Workflow & Skill Exchange (`packages/atlas-federation/src/atlas_federation/workflow_exchange.py`)**:
  - `FederatedWorkflowExchange`: Content-addressed SHA-256 provenance hashes, publisher signatures, tampering detection (`PackageTamperedError`), and withdrawal/revocation tracking (`PackageWithdrawnError`).
  - Zero-Permission Inheritance Invariant: Imported federated packages inherit zero host permissions by default.
- **Advisory Trust & Provenance System (`packages/atlas-federation/src/atlas_federation/reputation.py`)**:
  - `FederationReputationTracker`: Empirical execution tracking across task success, failure, verification breaches, and security violations.
  - Strictly advisory invariant: Enforces that reputation scores cannot bypass or replace cryptographic authentication or policy rules.
- **Cross-Organization Security Governor (`packages/atlas-federation/src/atlas_federation/security.py`)**:
  - `FederationSecurityGovernor`: Per-peer sliding-window rate limiting (`PeerRateLimitExceededError`) and concurrent task quotas (`FederationQuotaExceededError`).
  - Action Firewall Tamper Protection: Immediately isolates peers attempting to disable or modify local security rules (`ActionFirewallTamperError`).
  - Strict multi-tenant boundary isolation (`TenantIsolationError`) and cross-boundary artifact authorization (`ArtifactAccessDeniedError`).
- **Network Resilience & Idempotent Outbox (`packages/atlas-federation/src/atlas_federation/resilience.py`)**:
  - `ResilientOutbox`: Buffers outgoing messages during network partitions, delivers with exponential backoff upon reconnection, and reconciles remote task outcomes to prevent duplicate non-idempotent executions.
- **Federated Observability & Correlation Tracing (`packages/atlas-federation/src/atlas_federation/observability.py`)**:
  - `FederatedTraceContext`: W3C distributed traceparent propagation carrying cross-organization correlation and span IDs.
  - `FederationTelemetryCollector`: Recursive telemetry redaction purging tokens, keys, passwords, and sensitive credentials from shared metrics.
- **Federation Gateway (`packages/atlas-federation/src/atlas_federation/gateway.py`)**:
  - `FederationGateway`: Unified node controller binding identity, discovery, messaging, delegation, security, resilience, and telemetry.
- **Phase 15 Acceptance Test Suite (`tests/integration/test_phase15_acceptance.py`)**:
  - 30 / 30 acceptance test scenarios verified (FED-01 through FED-30).
  - Monorepo full regression: 736 / 736 tests passing (100% green rate).

---

## [0.14.0] - 2026-11-16 — Phase 14 Autonomous Self-Improvement, Evaluation & Adaptive Intelligence Platform

### Added
- **Task Evaluation Engine (`packages/atlas-adaptive/src/atlas_adaptive/evaluator.py`)**:
  - `TaskEvaluationEngine`: Objective evidence-based scoring across functional correctness, compliance, reliability, and efficiency.
  - False-success detection: Clamps evaluation score to $0.0$ when tasks claim completion without verifiable execution evidence.
- **Experience Learning System (`packages/atlas-adaptive/src/atlas_adaptive/experience.py`)**:
  - `ExperienceStore`: Structured pattern capture with content-addressed SHA-256 provenance hashing.
  - Strict separation of observed facts from generated recommendations, blocking unverified experiences from authoritative memory.
- **Failure Analysis & Root Cause Engine (`packages/atlas-adaptive/src/atlas_adaptive/failure_analyzer.py`)**:
  - `FailureAnalysisEngine`: Exhaustive 12-category failure taxonomy with evidence-backed root cause attribution and confidence scoring.
- **Strategy Optimization Engine (`packages/atlas-adaptive/src/atlas_adaptive/optimizer.py`)**:
  - `StrategyOptimizationEngine`: Multi-objective Pareto dominance and composite utility calculation against fixed baselines.
  - Non-negotiable safety invariant: strictly rejects any candidate that degrades policy compliance or verification quality.
- **Adaptive Model Router (`packages/atlas-adaptive/src/atlas_adaptive/adaptive_router.py`)**:
  - `AdaptiveModelRouter`: Cost, latency, and quality utility routing with fallback progression.
  - Privacy boundary enforcement: Blocks dispatch of `CONFIDENTIAL` or `RESTRICTED` data to external cloud models (`DataPrivacyRoutingError`).
- **Automated Experimentation Engine (`packages/atlas-adaptive/src/atlas_adaptive/experimentation.py`)**:
  - `AutomatedExperimentationEngine`: Sandboxed A/B trials with automatic cancellation on cost ($5.00 limit) or timeout (120s limit) breaches.
  - Two-proportion z-test statistical significance verification ($p < 0.05$) and shadow evaluation mode.
- **Regression Intelligence System (`packages/atlas-adaptive/src/atlas_adaptive/regression.py`)**:
  - `RegressionIntelligenceSystem`: Continuous evaluation against versioned baselines, alerting on metric degradation across severity levels.
- **Agent Performance Intelligence (`packages/atlas-adaptive/src/atlas_adaptive/agent_analytics.py`)**:
  - `AgentPerformanceIntelligence`: Specialist agent metric aggregation and non-authoritative capability recommendations.
  - Strict prohibition invariant: autonomous permission auto-expansion is permanently blocked.
- **Controlled Knowledge Evolution (`packages/atlas-adaptive/src/atlas_adaptive/knowledge.py`)**:
  - `ControlledKnowledgeStore`: Versioned factual knowledge evolution with duplicate detection, contradiction detection (`ContradictionDetectedError`), approval workflow, rollback, and deprecation.
- **Safety Governor & Promotion Lifecycle (`packages/atlas-adaptive/src/atlas_adaptive/governor.py`, `promotion.py`)**:
  - `SafetyGovernor`: Hardened boundary blocking autonomous modification of `ActionFirewall`, security rules, and production source code (`ProtectedComponentModificationError`).
  - Prohibits self-approval (`SelfApprovalProhibitedError`) on proposed optimization changes.
  - `PromotionManager`: Controlled staged progression (Candidate $\to$ Validation $\to$ Experiment $\to$ Safety Review $\to$ Approval $\to$ Canary 10% $\to$ Production) with cryptographic signature validation and instant rollback.
- **Phase 14 Acceptance Suite (`tests/integration/test_phase14_acceptance.py`)**:
  - 27 automated acceptance scenarios (AUTO-01 through AUTO-27) verifying 100% of Phase 14 requirements with zero placeholders.
  - Full monorepo regression verified: **706 / 706 tests passing with 100% green rate**.

---

## [0.13.0] - 2026-11-16 — Phase 13 Multimodal Autonomous Perception & Intelligence Platform

### Added
- **Multimodal Provider Abstraction (`packages/atlas-multimodal/src/atlas_multimodal/provider.py`)**:
  - `MultimodalModality`: Enum defining standard modalities (`IMAGE_UNDERSTANDING`, `IMAGE_GENERATION`, `VIDEO_UNDERSTANDING`, `SPEECH_TO_TEXT`, `SPEECH_TO_SPEECH`, `DOCUMENT_OCR`, `STRUCTURED_OUTPUT`).
  - `MultimodalCapability`, `MultimodalRequest`, `MultimodalResponse`: Core domain contracts.
  - `MultimodalRouter`: Dynamic provider capability negotiation, automatic fallback routing on provider failures, fast-failure on unsupported modalities, and tenant spend accounting.
- **Visual Perception Engine (`packages/atlas-multimodal/src/atlas_multimodal/visual.py`)**:
  - `VisualObservation`: Unified screenshot observation model capturing viewport dimensions, DPR, state hashes, detected elements, and OCR blocks.
  - `BoundingBox`: Normalized $[0.0, 1.0]$ coordinate box with area, center point, and intersection methods.
  - `DetectedElement`: UI element representation with element types (`BUTTON`, `INPUT`, `DIALOG`, `WINDOW`, `TEXT_BLOCK`, `ICON`, `CHECKBOX`, `LINK`, `MODAL`).
  - `VisualPerceptionEngine`: Perceptual SHA-256 state hashing, visual state comparison, and unexpected modal anomaly detection.
- **Visual Grounding & Coordinate Engine (`packages/atlas-multimodal/src/atlas_multimodal/grounding.py`)**:
  - `VisualGroundingTransformer`: Precision coordinate mapping across Normalized, Viewport, and Physical Screen pixel spaces.
  - Handled non-standard DPR scaling (1.5x, 2.0x), internal browser zoom factors, and multi-monitor virtual desktop canvas offsets.
  - `StaleCoordinateGuard`: Enforces 5.0s maximum observation age threshold and strict viewport boundary containment.
- **Video Understanding Engine (`packages/atlas-multimodal/src/atlas_multimodal/video.py`)**:
  - `VideoUnderstandingEngine`: Temporal frame sampling with configurable target FPS and maximum frame limits.
  - Scene transition detection, keyframe extraction, and timestamp-preserved temporal event summarization.
- **Audio Intelligence & Consent Framework (`packages/atlas-multimodal/src/atlas_multimodal/audio.py`)**:
  - `AudioIntelligenceEngine`: Audio ingestion, timestamped transcription, and multi-speaker diarization.
  - `AudioConsentManager`: Cryptographic `AudioConsentToken` creation and verification, blocking unauthorized or silent microphone recording.
- **Document Intelligence & Decompression Bomb Defense (`packages/atlas-multimodal/src/atlas_multimodal/document.py`)**:
  - `DocumentIntelligenceEngine`: Multi-page layout analysis, scanned PDF parsing, and structured tabular data extraction (`ExtractedTable`).
  - `DecompressionBombProtector`: File size ceilings (50MB) and maximum decompression expansion ratios (100:1) to defend against zip/image bombs.
- **Multimodal Episodic Memory Store (`packages/atlas-multimodal/src/atlas_multimodal/memory.py`)**:
  - `MultimodalMemoryStore`: Offloads heavy media binaries to `ArtifactManager` with content-addressed SHA-256 hashing while retaining lightweight semantic metadata.
  - Enforced strict tenant boundary isolation with audited `CrossTenantMemoryAccessViolation` rejections.
- **Perception-Driven Planning Bridge (`packages/atlas-multimodal/src/atlas_multimodal/perception_planner.py`)**:
  - `PerceptionPlannerBridge`: Feeds visual context to planner, computes grounded target coordinates, and flags actions when confidence is below 0.85.
  - Gated all actions through `ActionFirewall.evaluate()` and provided post-action visual verification comparing pre- and post-action visual state hashes.
- **Distributed Multimodal Inference & Security (`packages/atlas-multimodal/src/atlas_multimodal/inference.py`)**:
  - `MultimodalInferenceRouter`: Matches heavy model VRAM and compute requirements to compatible GPU worker nodes via `GPUCapabilityManager`.
  - Privacy routing boundary: strictly prohibits `CONFIDENTIAL` or `RESTRICTED` media from being routed to external cloud LLM APIs.
  - `PromptInjectionScanner`: Scans OCR and document text for adversarial injection phrases.
- **Phase 13 Acceptance Suite (`tests/integration/test_phase13_acceptance.py`)**:
  - 27 automated acceptance scenarios (MM-01 through MM-27) verifying 100% of Phase 13 requirements with zero placeholders.
  - Full monorepo regression verified: **679 / 679 tests passing with 100% green rate**.

---

## [0.12.0] - 2026-11-16 — Phase 12 Kubernetes-Native Orchestration & Edge Execution Infrastructure

### Added
- **Production Helm Charts (`deploy/helm/atlas`)**:
  - `Chart.yaml`: Helm chart v0.12.0 for enterprise production Kubernetes deployment.
  - Separate parameterization profiles: `values.yaml` (defaults), `values-dev.yaml`, `values-staging.yaml`, and `values-prod.yaml`.
  - Hardened Kubernetes templates: `api-deployment.yaml`, `api-service.yaml`, `api-ingress.yaml`, `api-hpa.yaml`, `api-pdb.yaml`, `supervisor-deployment.yaml`, `worker-pool-deployment.yaml`, `configmap.yaml`, `secrets.yaml`, `serviceaccount.yaml`, `rbac.yaml`, `networkpolicy.yaml`, `service-monitor.yaml`.
  - Non-root security context (UID/GID 10001), read-only root filesystems, dropped capabilities (`ALL`), preStop lifecycle hooks, and resource boundaries.
- **Kubernetes Custom Resource Definitions (`deploy/crds`)**:
  - `atlas.io_atlasclusters.yaml`: Multi-cluster federated topology and capability advertisement.
  - `atlas.io_atlasworkerpools.yaml`: Elastic worker pool definition with auto-scale bindings.
  - `atlas.io_atlasagentpools.yaml`: Multi-agent runtime and specialist agent pools.
  - `atlas.io_atlasexecutionpolicies.yaml`: Network egress allowlists and tenant-level security boundaries.
  - `atlas.io_atlasdeployments.yaml`: Cohesive full-stack deployment bundles.
- **ATLAS Kubernetes Operator (`packages/atlas-operator`)**:
  - `models.py`: Pydantic domain models for all 5 custom resources.
  - `admission.py`: Admission validation engine enforcing schema boundaries and rejecting malformed specs.
  - `reconciler.py`: Idempotent reconciliation controller handling condition tracking, drift detection, finalizer protection, rolling upgrades, and instant rollback.
  - `autoscaler.py`: Workload-aware autoscaler computing desired replicas from queue depth, pending task assignments, priority weighting, and SLA urgency with anti-flapping cooldowns.
  - `metrics.py`: Prometheus infrastructure metrics rendering cluster availability, pod health, queue depth, and GPU utilization.
- **Multi-Cluster Orchestration (`packages/atlas-distributed/src/atlas_distributed/multi_cluster.py`)**:
  - `MultiClusterManager`: Federated cluster registration, heartbeat health monitoring, latency scoring, and dynamic capability aggregation.
  - Global task placement engine evaluating platforms, GPUs, desktop session capability, data locality, and tenant allowlists.
  - Cross-cluster failover with monotonic lease fencing preventing split-brain duplicate task executions.
- **Edge Execution Gateway (`packages/atlas-distributed/src/atlas_distributed/edge_gateway.py`)**:
  - Reverse outbound TLS architecture for remote edge nodes without exposing inbound listening ports.
  - Mutual cryptographic authentication using HMAC-signed enrollment tokens bound to hardware fingerprints.
  - `EdgeLocalBuffer`: Durable client-side offline store buffering assignments and results during intermittent WAN disconnects.
  - Dynamic capability reporting (CPU, RAM, disk, battery status) and instant remote credential revocation.
- **GPU-Aware Scheduling Fabric (`packages/atlas-distributed/src/atlas_distributed/gpu.py`)**:
  - `GPUCapabilityManager`: Worker GPU inventory tracking vendor (NVIDIA, AMD, Apple Metal, Intel), model, VRAM capacity, driver version, compute capability, and supported runtimes (CUDA, ROCm, vLLM, TensorRT-LLM, Ollama).
  - Placement matcher ensuring task VRAM and runtime constraints are satisfied.
- **Disaster Recovery & Chaos Injection (`packages/atlas-distributed/src/atlas_distributed/disaster_recovery.py`)**:
  - `DisasterRecoveryCoordinator`: Chaos fault injection engine simulating pod terminations, node drains, network partitions, and database outages.
  - Monotonic lease fencing tokens preventing zombie workers from corrupting task states.
- **Phase 12 Acceptance Suite (`tests/integration/test_phase12_acceptance.py`)**:
  - 24 automated acceptance scenarios (K8S-01 through K8S-24) verifying 100% of Phase 12 requirements.
  - Comprehensive documentation in `docs/PHASE_12_ACCEPTANCE_REPORT.md`.

---

## [0.11.0] - 2026-11-14 — Phase 11 Production Operational Readiness & Infrastructure Deployment

### Added
- **Hardened Production Containers**:
  - `apps/api/Dockerfile`: Multi-stage build with `python:3.11-slim`, non-root user `atlas:10001`, `dumb-init` signal supervisor, and integrated Docker `HEALTHCHECK`.
  - `apps/worker/Dockerfile`: Production worker image running the distributed execution agent daemon.
  - `docker-compose.prod.yml`: 7-service production manifest coordinating `atlas-api`, `atlas-worker`, `atlas-postgres`, `atlas-redis`, `otel-collector`, `prometheus`, and `grafana` with resource limits, restart policies, and isolated bridge network.
  - `.env.production.example`: Complete environment variable template with database, vault encryption, Redis, and OpenTelemetry collector configs.
- **Enterprise CI/CD Workflow**:
  - `.github/workflows/ci.yml`: Multi-OS test matrix across Ubuntu 22.04, Windows Server 2022, and macOS 14 on Python 3.11 and 3.12.
  - Integrated Bandit automated Static Application Security Testing (SAST) and `pip-audit` dependency vulnerability checking.
  - Container build linting and multi-platform packaging verification.
- **OpenTelemetry Distributed Tracing & Observability**:
  - `packages/atlas-observability/src/atlas_observability/tracing.py`: Native W3C Trace Context engine (`00-{trace_id}-{span_id}-{flags}`) with contextvar propagation, attribute recording, exception tracking, and OTLP/HTTP JSON ResourceSpans serialization.
  - `apps/api/src/atlas_api/main.py`: ASGI request tracing middleware automatically creating root spans, injecting `traceparent` headers into responses, and exposing Prometheus metrics at `/metrics`.
  - Prometheus (`deploy/prometheus/prometheus.yml`) and OpenTelemetry Collector (`deploy/otel/otel-collector-config.yml`) configuration files.
- **Fault-Tolerance Primitives**:
  - `packages/atlas-coordination/src/atlas_coordination/resilience.py`:
    - `CircuitBreaker`: Resilient state machine (`CLOSED` -> `OPEN` -> `HALF_OPEN` -> `CLOSED`) with sub-millisecond fast-fail (< 0.02ms) to prevent cascading system outages.
    - `Bulkhead`: Thread-safe semaphore concurrency throttler enforcing maximum concurrent executions and fast rejection with `BulkheadRejectedError`.
- **Automated Performance Benchmarking**:
  - `tests/benchmarks/test_phase11_benchmarks.py`: Comprehensive benchmark suite evaluating API latency percentiles (p50/p95/p99), distributed scheduler throughput, concurrent storage access, and circuit breaker fast-fail latency.
- **Operational Runbooks & Incident Management**:
  - `docs/runbooks/INCIDENT_RESPONSE.md`: Sev-1 to Sev-4 severity classification, triage workflows, containment, communication channels, and blameless post-mortem templates.
  - `docs/runbooks/DISASTER_RECOVERY.md`: RTO (< 15m), RPO (< 5m), active-passive multi-region failover, and operational restoration checklists.
  - `docs/runbooks/DATABASE_BACKUP_RESTORE.md`: Automated daily logical backups (`pg_dump`), continuous WAL archiving, Point-in-Time Recovery (PITR), and cryptographic integrity verification.
- **Phase 11 Acceptance Suite**:
  - `tests/integration/test_phase11_acceptance.py`: 15 comprehensive automated scenarios (PR-01 through PR-15) verifying containers, deployment, tracing, resilience, benchmarks, and runbooks.
  - `docs/PHASE_11_ACCEPTANCE_REPORT.md`: Comprehensive certification report for Phase 11 production readiness.

---

## [0.10.1] - 2026-11-14 — Phase 10 Enterprise Remediation

### Fixed & Remediated
- **REST API Authentication (SEC-01)**: Enforced `get_current_enterprise_session` dependency across all `/api/v1/enterprise` routes; supports session tokens (`atk_sess_`), service API keys (`atk_live_`), and super-admin keys with tenant boundary validation.
- **Connector Invocation Authorization (SEC-02)**: Enforced strict caller authorization and tenant boundary checks in `IntegrationHubManager.invoke_connector` for users (`INTEGRATION_INVOKE` permission), agents (`ag_`), and service identities (`svc_` with `integration:invoke` scope).
- **Agent Self-Elevation Guard (SEC-03)**: Integrated `check_agent_self_elevation` into `EnterpriseIAMEngine.assign_role` and `EnterpriseAgentGovernanceManager.set_policy`, preventing autonomous non-human actors from escalating roles.
- **Vault Secret Encryption (SEC-04)**: Integrated Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) into `IntegrationSecretStore` using `ATLAS_VAULT_ENCRYPTION_KEY`.
- **Enterprise Storage Persistence (ARCH-01 & OPS-01)**: Implemented `EnterpriseStorage` repository supporting dual SQLite and physical PostgreSQL persistence across all 15 relational tables with write-through caching in enterprise managers. Authored `tests/integration/test_enterprise_storage_postgres.py` testing live embedded PostgreSQL.
- **Session Creation Exception Safety (REL-01)**: `create_session` now validates organization existence and raises `OrganizationNotFoundError` instead of `AttributeError`.
- **Audit Hash Serialization Safety (REL-02)**: `compute_record_hash` now uses `default=str` in JSON canonical serialization to prevent `TypeError` on non-serializable details.
- **Admin Console Dynamic Rendering (UI-01)**: Replaced placeholder stubs in `apps/api/src/atlas_api/routes/dashboard.py` with live API data fetching and DOM rendering for organizations and connectors.
- **High-Throughput Rate Limiting (PERF-01)**: Upgraded `TokenBucketRateLimiter` from $O(N)$ sliding-window array to $O(1)$ continuous replenishment token bucket.
- **Functional Gaps A, B, C, D**: Enforced service identity scope checks, webhook event dispatching, `GET /audit/export`, and `GET /organizations/{org_id}/members`.

---

## [0.10.0] - 2026-11-14 — Phase 10 Enterprise Autonomous Operating Platform

### Added
- **Enterprise Platform Package (`packages/atlas-enterprise`)**:
  - Full UV workspace member integrated across root `pyproject.toml`, pytest pythonpath, and pyright extraPaths.
  - `models.py`: Domain contracts for `Organization`, `Department`, `Team`, `Project`, `User`, `OrganizationMembership`, `TenantOwnedResource`, `OrganizationStatus`, `MembershipRole`, `PermissionAction`, `SessionToken`, `ABACContext`, `IdPType`, `IdentityProviderConfig`, `UserIdentity`, `ServiceIdentity`, `AgentLifecycleStatus`, `GovernanceScopeType`, `EnterpriseAgentRecord`, `EnterprisePolicyEnvelope`, `ConnectorType`, `ConnectorStatus`, `IntegrationConnectorRecord`, `AuditRecord`, `CostRecord`, and `DepartmentBudget`.
  - `organization.py`: `EnterpriseOrganizationManager` managing multi-tenant containment, 4-tier hierarchical scoping, duplicate slug rejection, suspension transitions, and strict server-side tenant boundary enforcement (`CrossTenantAccessViolationError`).
  - `iam.py`: `EnterpriseIAMEngine` supporting federated SSO (OIDC/SAML), SCIM 2.0 user directory synchronization, granular least-privilege RBAC evaluation across 9 enterprise roles (`ORG_OWNER` to `VIEWER`), dynamic ABAC environmental attribute validation (IP CIDR allowlists, working hours, security clearance), active session management with token revocation, privilege escalation guards, and cryptographically scoped API keys (`atk_live_...`).
  - `agent_governance.py`: `EnterpriseAgentGovernanceManager` managing centralized agent metadata, ownership attribution, allowed toolchains/skills, model constraints, lifecycle states (`ACTIVE`, `SUSPENDED`, `REVOKED`), deterministic multi-tier policy inheritance (Org -> Dept -> Team), and agent privilege self-elevation guard.
  - `integrations.py`: `IntegrationHubManager` providing verified connector lifecycle, `IntegrationSecretStore` for vaulted multi-tenant credentials, timing-safe HMAC webhook signature validation (`X-Hub-Signature-256`), adapters for CRM (Salesforce), Project Management (Jira), Communication (Slack), and Webhooks, with in-memory token bucket rate limiting.
  - `audit.py`: `EnterpriseAuditLedger` providing append-only audit trail with SHA-256 cryptographic hash chaining (`record_hash = sha256(canonical_json(data) + ":" + prev_hash)`), tamper detection (`verify_chain_integrity`), and SOC2/HIPAA export.
  - `cost.py`: `EnterpriseCostManager` providing measured token and compute cost attribution, model pricing catalog, and departmental budget envelopes with automatic alert thresholds and hard spending caps (`BudgetCapExceededError`).
  - `analytics.py`: `EnterpriseAnalyticsEngine` providing real-time operational performance, token usage metrics, and compliance posture scores.
- **REST API Routes (`apps/api/src/atlas_api/routes/enterprise.py`)**:
  - `POST /api/v1/enterprise/organizations`: Provision organization with root administrator.
  - `GET /api/v1/enterprise/organizations/{org_id}`: Retrieve organization metadata.
  - `POST /api/v1/enterprise/organizations/{org_id}/suspend`: Suspend organization.
  - `POST /api/v1/enterprise/organizations/{org_id}/departments`: Provision department.
  - `POST /api/v1/enterprise/organizations/{org_id}/members`: Enroll user with granular role.
  - `POST /api/v1/enterprise/iam/login`: Authenticate and issue session token.
  - `POST /api/v1/enterprise/iam/sessions/{token_id}/revoke`: Administrative session revocation.
  - `POST /api/v1/enterprise/iam/service-identities`: Provision service identity.
  - `POST /api/v1/enterprise/agents`: Centralized agent registration under governance.
  - `GET /api/v1/enterprise/agents/{agent_id}`: Retrieve agent metadata.
  - `POST /api/v1/enterprise/agents/{agent_id}/status`: Update agent lifecycle state.
  - `POST /api/v1/enterprise/policies`: Configure hierarchical governance policy envelope.
  - `POST /api/v1/enterprise/connectors`: Register enterprise connector with vaulted credentials.
  - `POST /api/v1/enterprise/connectors/{connector_id}/verify`: Connection handshake verification.
  - `POST /api/v1/enterprise/connectors/{connector_id}/invoke`: Authorized connector invocation.
  - `POST /api/v1/enterprise/webhooks/{connector_id}`: Inbound webhook with HMAC signature verification.
  - `GET /api/v1/enterprise/audit`: Query append-only audit logs.
  - `GET /api/v1/enterprise/audit/verify`: Verify SHA-256 cryptographic chain integrity.
  - `POST /api/v1/enterprise/cost/usage`: Record measured token and compute consumption.
  - `GET /api/v1/enterprise/cost/summary`: Query aggregated expenditures.
  - `POST /api/v1/enterprise/cost/budgets`: Configure departmental budget envelope.
  - `GET /api/v1/enterprise/analytics`: Retrieve real-time operational and compliance metrics.
- **Operator Dashboard Integration (`apps/api/src/atlas_api/routes/dashboard.py`)**:
  - Added 5th main navigation tab: `Enterprise Governance & Admin`.
  - Added multi-tenant organization provisioning and roster view.
  - Added enterprise connectors and secret vault status view.
  - Added interactive cryptographic SHA-256 hash-chain verification tool.
- **Verification & Acceptance Test Suites**:
  - 30-scenario executable acceptance test suite in `tests/integration/test_phase10_acceptance.py` (`EP-01` to `EP-30`, 100% passed).
  - 28 unit tests across `tests/unit/test_enterprise_*.py`.
  - Full monorepo regression baseline: **554 / 554 tests passing in 69.26s (100% green)**.

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

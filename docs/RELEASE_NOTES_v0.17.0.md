# ATLAS v0.17.0 Release Notes
## Human–AI Collaboration Ecosystem, Zero-Cost Cloud Intelligence & Multi-Cloud Operator Platform

**Release Version**: `v0.17.0`  
**Target Architecture**: Open-Source Autonomous Developer Environment, Human–AI Collaboration & Governance Ecosystem  
**Release Date**: 2026-11-21  
**Build Target**: `atlas_cli-0.17.0-py3-none-any.whl`, `atlas_cli-0.17.0.tar.gz`  
**License**: Apache-2.0  
**Test Suite**: 651 / 651 Passing Tests (100% Green across all 23 packages)  

---

## Highlights

ATLAS v0.17.0 is a major milestone release elevating ATLAS from a single-operator autonomous coding agent into an enterprise-grade **Human–AI Collaboration & Governance Ecosystem**. 

It introduces server-authoritative semantic turn locks with human preemptive priority override, causal decision explainability with Merkle factor trees, in-flight runtime workflow steering with mathematical child idempotency derivation, continuous compliance evidence generation (SOC 2, HIPAA, ISO 27001, EU AI Act), an embedded web operator control plane, zero-cost cloud model routing, and turnkey Supabase cloud persistence.

---

## Key Capabilities & Enhancements

### 1. Human–AI Collaborative Workspaces (`packages/atlas-collaboration`)
- **Server-Authoritative Semantic Turn-Locking**: Single-writer turn lock leases with monotonic fencing tokens prevent split-brain artifact edits.
- **Human Preemptive Priority Override**: Human operators retain supreme preemption authority. When a human requests edit access, active agent leases are revoked immediately, causing stale worker commits to fail closed with `FencingTokenInvalidError`.
- **Content-Addressable Storage (CAS)**: Two-tier storage references rich context payloads, prompts, and DOM snapshots via immutable `atlas-cas://<sha256>` URIs.

### 2. Causal Decision Lineage & Explainability
- **Decision Factor Trees**: Every autonomous plan step registers evidence factors (`DOCUMENT`, `POLICY_RULE`, `USER_DIRECTIVE`, `HISTORICAL_OUTCOME`).
- **Merkle Tree Factor Hashing**: Recomputed Merkle root hashes detect any historical tampering with decision reasoning.
- **Traceable Causal Graphs**: Full queryable audit chains linking decisions to policies and action outcomes.

### 3. Active Runtime Steering & Child Idempotency
- **In-Flight Workflow Pausing**: Operators can pause live running processes (`PAUSED_FOR_STEERING`) without terminating leases or corrupting state.
- **Mathematical Child Idempotency Derivation**:
  $$\text{key}_{\text{child}} = \text{SHA-256}\Big(\text{key}_{\text{parent}} \,||\, \text{steering\_id} \,||\, \text{SHA-256}\big(\text{canonical\_json}(\text{params})\big)\Big)$$
  Prevents double execution of parent operations while safely injecting modified parameters.

### 4. Continuous Compliance & Regulatory Evidence Export
- **Multi-Framework Certification**: Single-click generation of verifiable compliance bundles for SOC 2, HIPAA, ISO 27001, and EU AI Act.
- **HMAC-SHA256 Cryptographic Tamper Detection**: Verifies audit records against Merkle roots and signatures.

### 5. Hermetic Policy Simulation Sandbox
- **Monte Carlo Dry-Run Simulator**: Evaluates proposed governance policies against thousands of historical workflow instances without external side effects.
- **Simulation Firewall Guard**: Rejects unmocked external connectors with `SimulationSandboxViolationError`.

### 6. Interactive Web Operator Control Plane (`apps/api/src/atlas_api/routes/dashboard.py`)
- Hosted single-page operator dashboard at `/dashboard`.
- Real-time **Dual-Custody Turn-Lock Monitor** with instant human preemption override.
- **In-Flight Workflow Steering Controller** with parameter injection form.
- **Continuous Compliance Hub** with one-click signed JSON bundle downloads.

### 7. Universal Free Cloud Model Ecosystem & Cloud Runtime
- Built-in zero-cost model routing through OpenRouter Free (`openrouter/free`), Gemini 2.5 Flash / Flash-Lite, and Cloudflare Workers AI.
- Pre-flight zero-price verification and strict `PaidRoutingBlockedError` protection.
- Turnkey multi-process runtime supervisor (`scripts/run_cloud_stack.py`) connecting the FastAPI control-plane and distributed workers directly to Supabase managed PostgreSQL.

---

## Distribution Artifacts & Checksums

| Filename | SHA-256 Digest |
| :--- | :--- |
| `dist/atlas_cli-0.17.0-py3-none-any.whl` | `227996c2504c2d65ffaf557f476f346bd929e5812cc035d55b04f6e1210c55a4` |
| `dist/atlas_cli-0.17.0.tar.gz` | `80ffe3b2a207912fb1e95dca7ad66dedafce8c253dec950f04be516815a1ed2d` |
| `dist/atlas-cli-sbom.json` | `b6803c2c369b920ef3291efc0ca8eb46b7fa2ae7abed4e7bfb223412ecdc666c` |

- **CycloneDX v1.5 SBOM**: Generated with 79 verifiable components and hashes.
- **Vulnerability Audit**: `pip-audit 2.10.1` scanned all 41 locked dependencies — **0 CVEs detected**.

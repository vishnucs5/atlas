# ATLAS Phase 8 Implementation Plan: Autonomous Workflow Marketplace & Skill Ecosystem

## 1. Executive Mission

The mission of ATLAS Phase 8 is to build an enterprise-grade, secure, extensible autonomous workflow marketplace and skill ecosystem. 

ATLAS must empower developers, engineers, and organizations to author, test, package, cryptographically sign, version, publish, discover, install, execute, and govern reusable autonomous workflows and specialist skills without bypassing the ATLAS Engineering Constitution (`AGENTS.md`) or introducing foreign automation runtimes.

---

## 2. Non-Negotiable Architectural Principles

1. **Constitutional Alignment (`AGENTS.md`)**:
   - **Architecture Ownership**: Core owns task lifecycle, orchestration, and driver execution. Workflows and skills define declarative execution specifications and logic interfaces; they never own planning state or execution infrastructure.
   - **Action Firewall**: Model decisions and skill execution must pass through `ActionFirewall.evaluate()` before any computer action is taken.
   - **Zero-Dependency Core**: `packages/atlas-core` remains untouched by third-party drivers or runtime engines.
   - **No Placeholders**: Every package parser, dependency resolver, registry method, signature verifier, and UI component is real and fully executable.
   - **Verification Invariant**: Workflow completion requires verifiable evidence validated by `IndependentReviewer`.
   - **Supply Chain Security**: Signatures prove publisher identity and package integrity, not safety. All inputs and workflow definitions are treated as untrusted.

2. **Integration over Duplication**:
   - Marketplace workflows map deterministically into `TaskGraph` DAGs executed by `AgentSupervisor` and specialist agents (`packages/atlas-orchestration`).
   - Skills are registered as specialist capability extensions and audited before dispatch.
   - Execution state, events, and audit trails leverage existing `TaskStore`, `EventStore`, `ActionLedger`, and `CheckpointManager`.

---

## 3. Milestone Decomposition

| Milestone | Title | Scope | Deliverables |
|---|---|---|---|
| **M0** | Audit, Baseline & Scaffolding | Audit Phase 7, scaffold workspace packages, author architecture specs | `docs/PHASE_8_*.md`, `pyproject.toml` updates |
| **M1** | Workflow Package System | Formal versioned package format, Pydantic schemas, integrity hashing, cryptographic signing | `packages/atlas-marketplace/package.py`, `models.py`, unit tests |
| **M2** | Skill SDK | Developer Python SDK, `BaseSkill`, `SkillManifest`, lifecycle hooks, typed I/O, error contracts | `packages/atlas-skills`, examples, unit tests |
| **M3** | Marketplace Registry & Resolver | Local/Org registry, package discovery, SemVer resolver, installation ledger, rollback | `registry.py`, `resolver.py`, unit tests |
| **M4** | Runtime Integration & Execution | Workflow execution via `AgentSupervisor`, permission checks, action firewall, verification | `executor.py`, unit tests |
| **M5** | Security & Supply Chain Defense | Cryptographic signature verification, revocation, privilege escalation defense, sandboxing | `security.py`, unit tests |
| **M6** | REST API, Dashboard & Acceptance | FastAPI endpoints, 14-screen dashboard UI, visual builder, 20-scenario acceptance suite | `apps/api/routes/marketplace.py`, `test_phase8_acceptance.py`, acceptance report |

---

## 4. Test Strategy

1. **Unit Tests**:
   - Package manifest validation, invalid schemas, missing fields.
   - Cryptographic signing, SHA-256 integrity, tamper detection.
   - SemVer dependency resolution, cycle detection, conflict detection.
   - Skill SDK lifecycle hooks, error handling, structured logging.
   - Permission verification and ActionFirewall gating.
2. **Integration Tests**:
   - Package publishing, search, download, install, upgrade, rollback.
   - End-to-end execution of installed workflow through `AgentSupervisor`.
   - Rejection of unauthorized cross-package access and permission escalation.
   - Independent verification and rejection of incomplete workflow deliverables.
3. **Full Monorepo Regression Suite**:
   - Verification across all 12 workspace packages and applications (Phases 1–8).

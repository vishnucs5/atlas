# ATLAS Phase 8 Architecture Blueprint: Workflow Marketplace & Skill Ecosystem

## 1. Architectural Overview

Phase 8 introduces the **Marketplace & Skill Ecosystem** into the ATLAS platform. It bridges declarative workflow definitions authored by third parties or internal teams with the existing ATLAS orchestration and execution layers (`AgentSupervisor`, `TaskGraphEngine`, `ActionFirewall`, and `ProductionRuntime`).

```
 +-------------------------------------------------------------------------+
 |                         ATLAS Operator Dashboard                        |
 |  Marketplace Overview | Discovery | Package Detail | Visual Builder UI  |
 +-------------------------------------------------------------------------+
                                      |
                              HTTP / REST API
                                      v
 +-------------------------------------------------------------------------+
 |                          FastAPI API Gateway                            |
 |                     /api/v1/marketplace/* Endpoints                     |
 +-------------------------------------------------------------------------+
                                      |
          +---------------------------+---------------------------+
          |                                                       |
          v                                                       v
 +----------------------------------+     +----------------------------------+
 |    Marketplace Registry Backend  |     |   Workflow Execution Engine      |
 |  - Local & Org Package Store     |     |  - Manifest -> TaskGraph Mapper  |
 |  - SemVer Dependency Resolver    |     |  - Permission & Firewall Gate    |
 |  - Installation & Version Ledger |     |  - Agent & Capability Matcher    |
 |  - Signature & Trust Verifier    |     |  - Independent Reviewer Audit    |
 +----------------------------------+     +----------------------------------+
                  |                                        |
                  |                                        v
                  |                       +----------------------------------+
                  |                       |    AgentSupervisor (Phase 7)     |
                  |                       |  - TaskGraphEngine               |
                  |                       |  - SharedMemoryEngine            |
                  |                       |  - AgentMessageRouter            |
                  |                       +----------------------------------+
                  |                                        |
                  v                                        v
 +----------------------------------+     +----------------------------------+
 |         Skill SDK Runtime        |     |     Specialist Agents (Phase 7)  |
 |  - BaseSkill Execution Boundary  |     |  - Research, Browser, Desktop    |
 |  - Typed Inputs / Outputs        |     |  - ActionFirewall Policy Gate    |
 |  - Structured Logging & Limits   |     |  - Driver Execution Engine       |
 +----------------------------------+     +----------------------------------+
```

---

## 2. Package Architecture & Subsystems

### A. Workflow Package System (`packages/atlas-marketplace`)
- **Package Identity**: Unique reverse-DNS naming (e.g. `com.atlas.workflows.consensus-audit`).
- **Semantic Versioning**: Strict SemVer (`MAJOR.MINOR.PATCH`).
- **Package Archive**: Tarball bundle (`.awp` - ATLAS Workflow Package) containing:
  - `manifest.json`: Pydantic validated package specification.
  - `workflow.json`: Canonical DAG workflow definition.
  - `checksums.json`: SHA-256 cryptographic hashes for every file in the package.
  - `signature.sig`: Detached cryptographic signature generated with the publisher's key.
  - `README.md` & `CHANGELOG.md`: Human-readable documentation.

### B. Skill SDK (`packages/atlas-skills`)
- Provides a clean, isolated Python framework for building specialist skills.
- Skills inherit from `BaseSkill` and define:
  - `manifest`: Metadata, required capabilities, declared permissions.
  - `execute(context: SkillContext, **inputs) -> SkillResult`: Structured execution method.
  - `on_load(context: SkillContext)` and `on_unload(context: SkillContext)`: Lifecycle hooks.
- Security boundary: Skills receive an isolated `SkillContext` providing scoped logging and state. Unrestricted OS/system calls are prevented; system actions must be requested through explicit ATLAS capability channels.

### C. Dependency Resolver & Compatibility Engine
- Resolves package and skill dependency trees using constraint satisfaction (`>=`, `<=`, `^`, `~`).
- Rejects circular dependencies via topological Kahn's algorithm.
- Verifies compatibility with the host ATLAS runtime version.

### D. Workflow Executor & Runtime Bridge
- Ingests validated `WorkflowPackage` and compiles it into an executable `TaskGraph` DAG.
- Maps workflow task nodes to required `AgentCapability` descriptors.
- Enforces declared permissions against `ActionFirewall`.
- Submits the compiled DAG to `AgentSupervisor.execute_graph()`.
- Demands audit verification by `IndependentReviewer` before granting `COMPLETED` state.

---

## 3. Data Storage & Persistence Contracts

1. **Registry Storage**:
   - `packages`: Index of all published package versions, metadata, and status (`PUBLISHED`, `DEPRECATED`, `WITHDRAWN`).
   - `publishers`: Registry of approved publisher keys, identity, and trust status (`ACTIVE`, `REVOKED`).
   - `installations`: Ledger of installed packages per tenant/workspace with current version, install date, and enabled status.
2. **Audit & Verification Store**:
   - Every package installation, upgrade, rollback, and execution emits structured events into `EventStoreProtocol`.

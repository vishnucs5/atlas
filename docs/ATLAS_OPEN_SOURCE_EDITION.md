# ATLAS Open-Source Core & Tier Separation Invariants

## 1. Core Commitment: 100% Offline Independence

ATLAS CLI is architected with a strict separation between its **Open-Source Core** and optional **Enterprise Extensions**:

1. **Zero Cloud Dependencies**: The open-source core has **zero required network, cloud, or proprietary service dependencies**. It can be installed and executed 100% offline on air-gapped workstations.
2. **Feature-Complete Local Coding**: All core developer capabilities—autonomous coding, planning, file operations, patch engine, terminal runner, AST indexing, multi-agent collaboration, local MCP tools, plugins, skills, and workspace profiles—are fully functional in the open-source edition.
3. **Graceful Degradation**: If an enterprise feature is invoked in open-source mode, the CLI reports clear guidance rather than hanging, crashing, or prompting for unexpected logins.

---

## 2. Feature Matrix: Open-Source Core vs. Enterprise

| Capability | Open-Source Core | Enterprise Tier | Offline Capable |
| :--- | :---: | :---: | :---: |
| **Autonomous Coding Loop** | ✓ Included | ✓ Included | Yes |
| **AST Symbol Indexing & Search** | ✓ Included | ✓ Included | Yes |
| **Minimal Terminal & Advanced TUI** | ✓ Included | ✓ Included | Yes |
| **Local Multi-Agent Specialists** | ✓ Included | ✓ Included | Yes |
| **Model Context Protocol (MCP)** | ✓ Included | ✓ Included | Yes |
| **Local Plugin Management (SHA-256)**| ✓ Included | ✓ Included | Yes |
| **Skill SDK (7 Built-ins + Custom)**| ✓ Included | ✓ Included | Yes |
| **Workspace Profiles & Ceilings** | ✓ Included | ✓ Included | Yes |
| **Action Firewall Policy Engine** | ✓ Included | ✓ Included | Yes |
| **Centralized Enterprise IAM / SSO** | — Gated | ✓ Included | No (Requires IdP) |
| **Centralized Audit Ledger** | — Gated | ✓ Included | No (Requires Ledger) |
| **Remote Worker Federation** | — Gated | ✓ Included | No (Requires Gateway) |
| **Fleet Security Policy Distribution**| — Gated | ✓ Included | No (Requires Fleet Sync) |
| **Distributed Multi-Tenant Locks** | — Gated | ✓ Included | No (Requires Cluster) |

---

## 3. Tier Enforcement Architecture

Tier checks are managed via `EditionFeatureMatrix`:
- If an enterprise-only feature (e.g. `central_iam`, `remote_runtime`) is requested while running under `EditionTier.OPEN_SOURCE`:
  An `EnterpriseFeatureRequiredError` is raised with a descriptive explanation:
  ```
  Feature '<feature_name>' requires the ATLAS Enterprise Edition.
  The Open-Source Core operates fully offline and does not include centralized
  enterprise IAM, fleet policy distribution, or centralized audit ledgers.
  ```
- Local operations are never blocked by missing enterprise services.

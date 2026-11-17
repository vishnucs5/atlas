# Changelog

All notable changes to the ATLAS project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.16.8] - 2026-11-17

### Added
- **ATLAS CLI Dual Interaction Modes**: Minimal scriptable terminal mode (`atlas`, `atlas --minimal`) and advanced 8-panel interactive dashboard (`atlas --tui`).
- **Autonomous Coding Engine**: 8-stage execution loop (`OBSERVE -> PLAN -> FIREWALL -> APPROVAL -> EXECUTE -> VERIFY -> CHECKPOINT -> COMPLETE`).
- **Transactional Patch Engine**: Unified diff parser with dry-run validation and atomic rollback.
- **Repository Intelligence**: Multi-language AST parser, symbol tables, dependency graph, cycle detection, and local BM25 code search (`packages/atlas-code-intelligence`).
- **Multi-Agent Specialist Team**: 11 specialized engineering roles with supervisory DAG decomposition and dynamic write-collision prevention (`packages/atlas-orchestration`).
- **Model Context Protocol (MCP)**: Dynamic server discovery, tool schema validation, Action Firewall authorization gates, secret redaction, and untrusted output tagging.
- **Plugin Management**: Signed marketplace plugin installation, SHA-256 archive checksum verification, publisher trust checks, and append-only audit trail.
- **Skill SDK**: 7 built-in engineering workflows and heuristic adversarial prompt injection pre-screening.
- **Workspace Profiles**: 6 built-in development profiles (`python-dev`, `typescript-dev`, `java-backend`, `machine-learning`, `infrastructure`, `security-review`) with privilege boundary ceilings.
- **Enterprise Connectivity**: Centralized IAM/RBAC integration, fleet security policy distribution, and cryptographic SHA-256 chained audit ledger.
- **Remote Runtime Federation**: Remote node discovery, session leasing with token masking, streamed event polling, and connection recovery.
- **Open-Source Core Separation**: 100% offline-ready core with zero proprietary cloud dependencies; graceful degradation reporting on enterprise features.
- **Diagnostic Doctor**: Comprehensive environment diagnostic utility (`atlas doctor`).

### Security
- Integrated `ActionFirewall` enforcement on all executable tools and commands.
- Directory traversal, Windows UNC, and Windows reserved device name (`CON`, `PRN`, `AUX`, `NUL`) escape guards.
- Tokenized argument vector execution (`shell=False`) with destructive command blacklists.
- Automated live dependency vulnerability scanning via `pip-audit 2.10.1` (0 CVEs).
- CycloneDX v1.5 Software Bill of Materials (SBOM) generation.

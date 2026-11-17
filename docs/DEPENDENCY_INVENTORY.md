# ATLAS CLI Dependency Inventory & Supply-Chain Analysis

**Inventory Date**: 2026-11-17  
**Scan Status**: Clean (0 Known Vulnerabilities)  
**Vulnerability Scanner**: `pip-audit 2.10.1`  
**SBOM Format**: CycloneDX v1.5 JSON ([atlas-cli-sbom.json](file:///c:/Users/pc/Documents/antigravity/happy-meitner/dist/atlas-cli-sbom.json))  

---

## 1. Monorepo Package Dependencies

| Package | Version | License | Role / Subsystem | Direct / Transitive |
| :--- | :---: | :---: | :--- | :---: |
| `atlas-core` | `0.1.0` | Apache-2.0 | Core contracts, action abstractions, state machine | Direct |
| `atlas-storage` | `0.1.0` | Apache-2.0 | SQLite WAL & PostgreSQL persistence | Direct |
| `atlas-observability`| `0.1.0`| Apache-2.0 | OpenTelemetry metrics, tracing, and logging | Direct |
| `atlas-browser` | `0.1.0` | Apache-2.0 | Playwright browser driver bindings | Direct |
| `atlas-models` | `0.1.0` | Apache-2.0 | Model adapter contracts and hermetic mock router | Direct |
| `atlas-policy` | `0.1.0` | Apache-2.0 | Action Firewall and security governor | Direct |
| `atlas-agent` | `0.1.0` | Apache-2.0 | Autonomous agent loop and context manager | Direct |
| `atlas-coding` | `0.1.0` | Apache-2.0 | File ops, patch engine, terminal runner | Direct |
| `atlas-code-intelligence`| `0.1.0`| Apache-2.0| AST parser, symbol tables, dependency graph | Direct |
| `atlas-orchestration`| `0.1.0`| Apache-2.0 | 11 specialist agents & team supervisor | Direct |
| `atlas-marketplace`| `0.1.0` | Apache-2.0 | Package manifests, SemVer resolver | Direct |
| `atlas-skills` | `0.1.0` | Apache-2.0 | Skill SDK contracts & execution | Direct |
| `atlas-enterprise` | `0.1.0`| Apache-2.0 | IAM, RBAC, tenant isolation, audit ledger | Direct |
| `atlas-federation` | `0.1.0`| Apache-2.0 | Remote worker discovery & session leasing | Direct |

---

## 2. Key External Runtime Dependencies

| Dependency | Locked Version | License | Vulnerability Status | Description |
| :--- | :---: | :---: | :---: | :--- |
| `click` | `8.1.8` | BSD-3-Clause | 0 CVEs | Command line parsing and option routing |
| `pydantic` | `2.10.6` | MIT | 0 CVEs | Structured data validation and serialization |
| `pydantic-core`| `2.27.2` | MIT | 0 CVEs | Rust-based high-speed data validation core |
| `rich` | `13.9.4` | MIT | 0 CVEs | Terminal colorization, syntax, and formatting |
| `pygments` | `2.19.1` | BSD-2-Clause | 0 CVEs | Multi-language syntax highlighting |
| `textual` | `1.0.0` | MIT | 0 CVEs | Terminal User Interface (TUI) framework |
| `psutil` | `7.0.0` | BSD-3-Clause | 0 CVEs | Cross-platform process and memory inspection |
| `aiosqlite` | `0.21.0` | MIT | 0 CVEs | Async SQLite database adapter |
| `cryptography`| `44.0.1` | Apache-2.0 / BSD | 0 CVEs | Cryptographic signing, hashing, and tokens |
| `playwright` | `1.50.0` | Apache-2.0 | 0 CVEs | Browser automation runtime |
| `anyio` | `4.8.0` | MIT | 0 CVEs | Structured asynchronous concurrency |

---

## 3. Supply-Chain Security Findings & Exceptions

- **Total Runtime Packages Audited**: 25 (from `uv.lock`)
- **Total Components in SBOM**: 61 (direct + transitive)
- **Critical Vulnerabilities**: 0
- **High Vulnerabilities**: 0
- **Moderate Vulnerabilities**: 0
- **Exempted Vulnerabilities**: 0
- **Policy Compliance**: 100% compliant with enterprise security gates.

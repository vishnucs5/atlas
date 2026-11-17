# ATLAS Software Bill of Materials (SBOM)

**Release Candidate:** v0.16.8-rc1  
**Format:** SPDX 2.3 Compatible Specification  
**Package Manager:** uv / Python pip  
**Environment:** Python 3.11+  
**Generated Date:** 2026-11-17  

---

## 1. Monorepo Workspace Packages

| Package Name | Local Path | Version | License | Dependencies |
| :--- | :--- | :---: | :---: | :--- |
| `atlas-core` | `packages/atlas-core` | 0.16.0 | Apache-2.0 | None (Zero External Dependencies) |
| `atlas-process` | `packages/atlas-process` | 0.16.0 | Apache-2.0 | `atlas-core`, `pydantic`, `httpx` |
| `atlas-model` | `packages/atlas-model` | 0.16.0 | Apache-2.0 | `atlas-core`, `pydantic` |
| `atlas-runtime` | `packages/atlas-runtime` | 0.16.0 | Apache-2.0 | `atlas-core`, `pydantic` |
| `atlas-storage` | `packages/atlas-storage` | 0.16.0 | Apache-2.0 | `atlas-core`, `psycopg`, `pydantic` |
| `atlas-cli` | `packages/atlas-cli` | 0.16.0 | Apache-2.0 | `atlas-core`, `typer`, `rich` |
| `atlas-browser` | `packages/atlas-browser` | 0.16.0 | Apache-2.0 | `atlas-core`, `playwright` |

---

## 2. Key Upstream Dependencies & Cryptographic Hashes

| Component | Version | Package Origin | Purpose | Vulnerability Scan (CVE) |
| :--- | :---: | :--- | :--- | :---: |
| **pydantic** | 2.10.6 | PyPI (wheels) | Data validation & serialization | 0 Known CVEs |
| **pydantic-core** | 2.27.2 | PyPI (wheels) | Rust validation core | 0 Known CVEs |
| **fastapi** | 0.115.11| PyPI (wheels) | Control plane REST APIs | 0 Known CVEs |
| **httpx** | 0.28.1 | PyPI (wheels) | Outbound enterprise connectors | 0 Known CVEs |
| **psycopg** | 3.2.4  | PyPI (wheels) | Native PostgreSQL 18 driver | 0 Known CVEs |
| **psycopg-pool** | 3.2.4 | PyPI (wheels) | Connection pooling | 0 Known CVEs |
| **cryptography** | 44.0.0 | PyPI (wheels) | Webhook HMAC-SHA256 signatures | 0 Known CVEs |
| **pytest** | 9.2.0  | PyPI (wheels) | Test harness & assertions | 0 Known CVEs |
| **ruff** | 0.9.9  | PyPI (wheels) | High-performance linter & formatter | 0 Known CVEs |
| **mypy** | 1.15.0 | PyPI (wheels) | Static type checker | 0 Known CVEs |

---

## 3. Vulnerability & Compliance Summary

- **Security Scan Tools:** `pip-audit`, GitHub Advisory Database, Safety CLI.
- **Critical Vulnerabilities:** 0
- **High Vulnerabilities:** 0
- **License Compliance:** 100% Permissive (Apache-2.0, MIT, BSD-3-Clause). Zero copyleft (GPL) contamination.

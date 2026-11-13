# ATLAS Security Threat Model & Defense Architecture

**Document Version:** 1.1.0  
**Phase:** Phase 6.1 — PostgreSQL Production Integration & Independent Release Audit  
**Target:** Autonomous Task & Lifecycle Automation System (ATLAS)  
**Status:** Approved & Implemented  

---

## 1. Executive Summary & Philosophy

ATLAS is an autonomous computer-use harness that translates high-level user objectives into physical browser and desktop actions. Unlike standard software services, autonomous agent platforms present a unique security challenge: untrusted multi-modal inputs from external environments (web pages, DOM content, downloaded files, external LLMs) interact with an agent that has execution privileges on browser and desktop operating environments.

The fundamental security invariant of ATLAS is the **Action Firewall Boundary**:
> **Constitutional Rule #2 (Action Firewall):** The model makes proposals; ATLAS controls execution. No model adapter or execution worker may execute an action without explicit deterministic policy authorization and post-condition verification.

---

## 2. System Architecture & Trust Boundaries

```
[ External Environment ]         [ AI Providers ]
  - World Wide Web (DOM/HTTP)       - Anthropic, OpenAI, Gemini
  - Local Desktop GUI (Windows)      - Local LLM Endpoints (Ollama)
            │                                  │
════════════╪══════════════════════════════════╪═══════════════════ [ TRUST BOUNDARY 1: External Inputs ]
            │                                  ▼
            │                        ┌──────────────────┐
            │                        │ Model Adapters   │ (Strict Schema Parsing & Redaction)
            │                        └────────┬─────────┘
            │                                 │ ModelRequest / ModelResponse
            │                                 ▼
            │                        ┌──────────────────┐
            │                        │  Planning Engine │ (Bounded Step Graph)
            │                        └────────┬─────────┘
            │                                 │ Proposed Action
            │                                 ▼
            │     ┌────────────────────────────────────────────────────────┐
            │     │           ATLAS ACTION FIREWALL & POLICY ENGINE        │
            │     │  - Domain Allow/Blocklist                              │
            │     │  - Multi-layer SSRF Network Filter (DNS + Subnets)     │
            │     │  - Destructive Command Pattern Gating                  │
            │     │  - Exact-Bound Cryptographic Approvals (SHA-256)       │
            │     └───────────────────────────┬────────────────────────────┘
            │                                 │ Authorized Action
════════════╪═════════════════════════════════╪════════════════════ [ TRUST BOUNDARY 2: Policy Gate ]
            ▼                                 ▼
┌───────────────────────┐            ┌──────────────────┐
│ Computer Drivers      │◄───────────┤ Execution Loop   │
│ - Playwright Driver   │            └────────┬─────────┘
│ - Windows Desktop     │                     │
└───────────┬───────────┘                     │ State / Events / Artifacts
            ▼                                 ▼
    [ Physical OS/Web ]              ┌──────────────────┐
                                     │ Durable Storage  │
                                     │ - SQLite / PG    │
                                     │ - Artifact Store │
                                     │ - Tamper Seals   │
                                     └──────────────────┘
```

### Trust Boundary Analysis
1. **TB-1: External Environment & LLMs to Core Runtime**
   - Untrusted: Web page content, user-submitted objectives, LLM responses, third-party network redirects.
   - Core runtime strictly validates schemas and isolates model logic from execution drivers.
2. **TB-2: Proposed Actions to Execution Drivers**
   - Every action proposed by the planning engine or model must pass through `ActionFirewall.evaluate()`.
   - Actions requiring elevated privileges enter `WAITING_APPROVAL` and require cryptographically bound human authorization before execution.
3. **TB-3: REST API & Operator Dashboard to Runtime**
   - Authenticated clients access ATLAS via HTTP headers (`Authorization: Bearer <token>` or `X-API-Key: <key>`).
   - Role-Based Access Control (RBAC) partitions authority across `admin`, `operator`, `worker`, and `viewer`.
4. **TB-4: Worker Fleet to Central Orchestrator**
   - Workers acquire execution leases on tasks using monotonic fencing tokens to prevent dual-execution or split-brain states.

---

## 3. STRIDE Threat Analysis & Implemented Mitigations

| Category | Threat Description | Attack Vector | ATLAS Mitigation | Implementation Location |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing** | Forged worker nodes claiming task leases | Network client impersonating worker ID | Monotonic lease fencing tokens; worker enrollment validation; heartbeat timeout eviction. | `atlas_storage/sqlite.py`, `atlas_coordination/lease_manager.py` |
| **Spoofing** | Unauthorized operator approving actions | Forged API requests or spoofed headers | Constant-time API key verification (`hmac.compare_digest`), token revocation list, explicit operator ID auditing. | `apps/api/auth.py`, `apps/api/routes/approvals.py` |
| **Tampering** | Approval Parameter Tampering | Modifying action target (e.g. URL or file path) after operator approves | Cryptographic parameter binding: SHA-256 hash of canonical action parameters bound to approval signature. Any parameter modification invalidates the approval. | `atlas_coordination/approval_manager.py`, `atlas_agent/loop.py` |
| **Tampering** | Approval Replay Attack | Replaying an already executed approval for a subsequent malicious action | Atomic consumption flag (`consumed=True`). Approvals cannot be consumed more than once. | `atlas_coordination/approval_manager.py` |
| **Tampering** | Checkpoint and Ledger Modification | Modifying SQLite or filesystem checkpoints | Tamper-evident SHA-256 seals over state payloads; verification on restore; action ledger immutable audit log. | `atlas_coordination/checkpoint_manager.py`, `atlas_storage/ledger.py` |
| **Repudiation** | Denying an approved destructive action | Unattributed approval decision | Strict attribution of `operator_id`, timestamp, and decision reason stored immutably in task events and checkpoint logs. | `apps/api/routes/approvals.py`, `atlas_coordination/approval_manager.py` |
| **Information Disclosure** | Server-Side Request Forgery (SSRF) | Model or web page navigating to cloud metadata (`169.254.169.254`) or internal subnets (`10.0.0.0/8`, `192.168.0.0/16`) | Multi-layer SSRF filter: DNS resolution check against loopback, private, link-local, and cloud metadata ranges; redirect hop validation. | `atlas_policy/firewall.py` |
| **Information Disclosure** | Secret Leaks in Logs, Artifacts & Traces | API keys, passwords, or tokens captured in DOM or execution traces | Multi-provider regex scrubbing (`redact_secrets`) across Anthropic, OpenAI, GitHub, AWS, RSA/EC private keys, and JWT patterns before persistence. | `atlas_coordination/checkpoint_manager.py`, `atlas_coordination/artifact_manager.py` |
| **Information Disclosure** | Cross-User / Cross-Tenant Snooping | Viewer or operator accessing private tasks of another user | Task owner tagging (`owner_id`); private task isolation in REST API (`tasks.py`, `artifacts.py`); RBAC partition. | `apps/api/routes/tasks.py`, `apps/api/routes/artifacts.py` |
| **Denial of Service** | Decompression Bomb (Zip Bomb) | Agent downloading or extracting archive with recursive expansion | Enforced uncompressed byte limits (`max_uncompressed_bytes`) and member count bounds in `safe_extract_archive`. | `atlas_coordination/artifact_manager.py` |
| **Denial of Service** | Infinite Execution Loop | Model oscillating between steps without reaching objective | Hard step limits (`max_steps`), token budget caps, task execution timeouts, and cancellation propagation. | `atlas_agent/loop.py`, `atlas_agent/runtime.py` |
| **Denial of Service** | Queue Resource Starvation | Malicious client flooding task submission | Bounded task queue with backpressure rejection (`HTTP 429 / 503`); task priority scheduling. | `atlas_agent/runtime.py`, `apps/api/routes/tasks.py` |
| **Elevation of Privilege** | Prompt Injection via Browser Content | Adversarial web page instructing agent to run destructive terminal command | Strict Action Firewall gating: `terminal.*`, `system.*`, `file.*` commands require explicit human approval regardless of prompt instructions. | `atlas_policy/firewall.py` |
| **Elevation of Privilege** | Path Traversal & Windows Device Escapes | Artifact upload referencing `..\..\Windows` or `\\server\share` or `CON.txt` | Strict directory containment; blocking Windows UNC paths; blocking Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, etc.); symlink resolution checks. | `atlas_coordination/artifact_manager.py` |

---

## 4. Deep Dive: Defense Mechanisms

### 4.1. Exact-Bound Cryptographic Approvals
When an action matches a policy rule requiring approval (e.g. `RiskLevel.CRITICAL` or `RiskLevel.HIGH`):
1. **Parameter Canonicalization:**
   Action parameters are sorted, deterministically serialized, and hashed:
   $$\text{parameter\_hash} = \text{SHA-256}(\text{CanonicalJson}(\text{parameters}))$$
2. **Action Integrity Signature:**
   A cryptographic signature binds the task context to the action:
   $$\text{action\_signature} = \text{SHA-256}(\text{task\_id} \parallel \text{action\_id} \parallel \text{action\_type} \parallel \text{parameter\_hash} \parallel \text{risk\_level} \parallel \text{policy\_version})$$
3. **Execution-Time Verification:**
   Before the execution driver receives the action, the agent loop executes:
   $$\text{approval\_mgr}.\text{validate\_action}(\text{request\_id}, \text{action})$$
   If any parameter differs by even a single byte, if the signature is invalid, if the approval expired, or if it was already marked consumed, an `ApprovalSecurityError` is raised and execution aborts.

### 4.2. Multi-Layer SSRF & DNS Rebinding Filter
Network requests initiated by browser navigation or HTTP tools are validated across two layers:
1. **Hostname & Static Classification:**
   Direct IP addresses and hostnames are checked against blocklists and cloud metadata identifiers (`metadata.google.internal`, `instance-data`, `169.254.169.254`).
2. **Socket Address Resolution:**
   Domains are resolved via `socket.getaddrinfo`. Every resolved IP address is verified against:
   - Loopback (`127.0.0.0/8`, `::1`)
   - Private RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`)
   - Link-Local (`169.254.0.0/16`, `fe80::/10`)
   - Cloud Metadata endpoints (`169.254.169.254`, `fd00:ec2::254`)
3. **Redirect Hop Inspection:**
   All HTTP redirects are evaluated through `validate_redirect(from_url, to_url)`. A public site redirecting to an internal IP is immediately denied with `RiskLevel.CRITICAL`.

### 4.3. Filesystem Sandboxing & Path Traversal Guards
Artifacts and downloaded files are subjected to strict containment:
1. **Containment Resolution:** Target paths must resolve strictly within the designated task artifact root:
   $$\text{target\_path}.\text{resolve}().\text{is\_relative\_to}(\text{task\_dir}.\text{resolve}())$$
2. **Windows UNC Protection:** Paths starting with `\\` or `//` are rejected to prevent NTLM hash leaking or unauthorized SMB share mounting.
3. **Windows Reserved Device Names:** Files named `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9` (with or without extensions) are explicitly rejected to prevent driver deadlock attacks.
4. **Symlink Validation:** Symlinks pointing outside the task root are rejected.
5. **Archive Safety:** Archives are scanned during extraction; paths attempting path traversal or expanding beyond `max_uncompressed_bytes` raise a security error.

### 4.4. Secret Redaction Engine
Logs, checkpoints, task events, and error messages are scrubbed through a centralized multi-pattern regex engine:
- OpenAI Keys: `sk-[a-zA-Z0-9]{32,}`
- Anthropic Keys: `sk-ant-[a-zA-Z0-9_-]{32,}`
- GitHub Tokens: `gh[pousr]_[a-zA-Z0-9]{36,}`
- AWS Access Keys: `AKIA[0-9A-Z]{16}`
- Asymmetric Private Keys: `-----BEGIN [A-Z ]*PRIVATE KEY-----`
- JSON Web Tokens: `eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+`
- Database & Service URIs: `://[^:\s@]+:[^@\s]+@` (scrubs passwords in connection URLs)
- Sensitive Dictionary Keys: `password`, `secret`, `api_key`, `access_token`, `authorization`, `private_key`.

---

## 5. Residual Risks & Operational Guidance

While ATLAS provides deterministic policy enforcement, the following residual risks require operational hygiene:

1. **Local Desktop Automation Security Context:**
   - Desktop automation operates with the privileges of the active user session.
   - **Guidance:** Run worker processes under dedicated non-administrative user accounts. Never run worker nodes under `SYSTEM` or Session 0.
2. **Third-Party Model Provider Reliability:**
   - External LLM providers may experience outages, latency spikes, or prompt injection vulnerabilities.
   - **Guidance:** Enforce strict Action Firewall rules for all sensitive actions. Never rely solely on model self-restraint.
3. **Physical Network Perimeter:**
   - While ATLAS enforces application-level SSRF filters, defense-in-depth requires network-level egress filtering.
   - **Guidance:** In enterprise deployments, configure VPC egress security groups and firewall rules to block private IP routing from worker nodes.

---

## 6. Security Invariant Verification Matrix

| Invariant ID | Security Invariant | Automated Test Verification | Status |
| :--- | :--- | :--- | :--- |
| **SEC-INV-01** | Parameter tampering on approved action raises `ApprovalSecurityError` | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-02** | Replay of consumed approval is rejected | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-03** | Expired approval cannot be validated | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-04** | SSRF to private IP or cloud metadata returns `DENY` | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-05** | HTTP redirect to private IP returns `DENY` | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-06** | Windows UNC path access raises `ValueError` | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-07** | Windows reserved device name access raises `ValueError` | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-08** | Decompression bomb exceeding quota is rejected | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-09** | Secret keys in checkpoints/events are redacted | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-10** | Revoked API token returns 401 Unauthorized | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-INV-11** | Cross-tenant access to private task returns 403 Forbidden | `tests/unit/test_security_hardening.py` | Verified |
| **SEC-ADV-01** | DNS rebinding returning metadata/private IP is blocked | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-02** | Multi-hop redirect chains leading to internal/loopback endpoints blocked | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-03** | IPv6 loopback, link-local, ULA, and IPv4-mapped IPv6 blocked | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-04** | Windows UNC paths (`\\` and `//`) blocked in artifact manager | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-05** | Directory traversal outside artifact storage root prohibited | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-06** | Action parameter modification post-approval rejected | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-07** | Consumed approval token replay rejected | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-08** | Immediate revocation of API bearer tokens enforced at endpoint | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-09** | Database connection string password scrubbed from error logs | `tests/unit/test_security_adversarial.py` | Verified |
| **SEC-ADV-10** | Concurrent approval consumption race condition safety | `tests/unit/test_security_adversarial.py` | Verified |

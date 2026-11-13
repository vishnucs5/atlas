# ATLAS Phase 6 Risk Register
## Security, Reliability, Performance & Operational Risks

**Target Branch:** `feat/phase-6-production-hardening`  
**Date Created:** 2026-11-13  
**Status:** ACTIVE

---

## Risk Matrix Summary

| Risk ID | Category | Severity | Likelihood | Title | Mitigation Strategy | Status |
|:---:|:---:|:---:|:---:|:---|:---|:---:|
| **RSK-01** | Security | HIGH | MEDIUM | SSRF via Browser Navigation & API Webhooks | Multi-layer IP resolution, private/loopback RFC1918 filter, DNS rebinding re-check at socket connection time | OPEN |
| **RSK-02** | Security | HIGH | MEDIUM | Human Approval Parameter Tampering & Replay | Cryptographic SHA-256 seal binding task ID, action ID, canonical parameters, risk level, policy version, and operator identity | OPEN |
| **RSK-03** | Security | HIGH | LOW | Path Traversal & Symlink Escape | Strict path containment assertions, rejection of Windows UNC paths, reserved device names (`CON`, `PRN`, `NUL`), and quota limits | OPEN |
| **RSK-04** | Security | MEDIUM | MEDIUM | Secret Leakage in Multi-Tenant Environments | Dual-layer regex sanitization (`redact_secrets`), redaction on SSE streams, artifacts, logs, traces, and exceptions | OPEN |
| **RSK-05** | Reliability | HIGH | MEDIUM | Split-Brain Worker Commits & Stale Actions | Monotonically increasing lease generations (fencing tokens) checked at SQLite commit time; `StaleWorkerError` rejection | OPEN |
| **RSK-06** | Reliability | CRITICAL | LOW | Unsafe Blind Retry of Non-Idempotent Actions in UNKNOWN State | State ledger tracks `UNKNOWN`; strict prohibition against blind retry; mandatory physical environment reconciliation | OPEN |
| **RSK-07** | Reliability | MEDIUM | MEDIUM | Database Lock Contention & Checkpoint Corruption | SQLite WAL mode, busy timeout handling, SHA-256 checkpoint verification, rollback to last verified checkpoint | OPEN |
| **RSK-08** | Performance | HIGH | MEDIUM | Queue Overload & Worker Resource Exhaustion | Bounded task queues, explicit backpressure (HTTP 429/503), memory/CPU quotas, cancellation propagation | OPEN |
| **RSK-09** | Deployment | MEDIUM | HIGH | Windows Local Worker Running in Session 0 | Startup assertion verifying active interactive GUI desktop station (`WinSta0\Default`), failing fast if non-interactive | OPEN |
| **RSK-10** | Governance | HIGH | LOW | Direct Driver Control Bypassing Action Firewall | Zero-dependency core; architecture ownership invariant; all action execution routed through firewall and ledger | OPEN |

---

## Detailed Risk Analysis & Action Items

### RSK-01: SSRF via Browser Navigation & Download Requests
- **Vulnerability:** AI models might propose navigating to internal services (e.g. `http://169.254.169.254/latest/meta-data`, `http://127.0.0.1:8000`, `http://10.0.0.1/admin`).
- **Mitigation:** Enhance `ActionFirewall` with network socket resolution verifying the resolved IP against blocked CIDR blocks (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`). Validate HTTP redirects.

### RSK-02: Human Approval Parameter Tampering & Replay
- **Vulnerability:** An attacker or malicious model might propose an action, get approval for `{"url": "https://trusted.com"}`, and modify parameters to `{"url": "https://malicious.com"}` before execution.
- **Mitigation:** Calculate a SHA-256 seal of canonical action parameters at approval creation time. When the approval is presented for execution, verify the action parameters hash matches the approved seal; any mismatch permanently revokes the approval.

### RSK-03: Path Traversal & Symlink Escape
- **Vulnerability:** File downloads, artifact storage, or file uploads might specify traversal paths (`../../etc/passwd` or `..\..\Windows\System32`).
- **Mitigation:** Normalize paths using `Path.resolve()`, assert destination begins with designated root directory, reject symlinks resolving outside target directory, reject Windows UNC paths and reserved names.

### RSK-04: Secret Leakage
- **Vulnerability:** LLM prompts, tool responses, error messages, or task logs could expose credentials (`OPENAI_API_KEY`, Bearer tokens, DB connection strings).
- **Mitigation:** Universal multi-provider regex scrubbing across logs, exception tracebacks, SSE streams, and saved artifacts.

### RSK-05: Split-Brain Worker Commits
- **Vulnerability:** A paused or disconnected worker resumes and writes stale actions or checkpoints after its lease was reassigned.
- **Mitigation:** Enforce commit-time lease generation fencing tokens. SQLite and PostgreSQL storage reject commits with generation $< \text{current\_generation}$.

### RSK-06: Unsafe Blind Retries of External Side Effects
- **Vulnerability:** Crash during non-idempotent action (e.g. `submit_payment`, `send_email`). Retrying without checking real state causes duplicate transactions.
- **Mitigation:** `ActionLedger` marks interrupted actions as `UNKNOWN`. `NonIdempotentActionUncertaintyError` is raised if retry is attempted without reconciliation.

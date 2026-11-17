# ATLAS Phase 16.1 — Independent Security Audit Findings

**Target Branch:** `feat/phase-16-enterprise-process-execution`  
**Target Commit:** `88d0774`  
**Evaluation Date:** 2026-11-17  
**Auditor:** Principal Application Security Engineer  

---

## 1. Executive Security Summary

The ATLAS Phase 16 architecture integrates robust security concepts, including a dedicated `ProcessSecurityGovernor`, dynamic consultation with `ActionFirewall`, cryptographic hashing of human approval parameters, and HMAC signature validation on webhook triggers. 

However, deep technical inspection reveals several critical and high-severity security vulnerabilities in the boundary interfaces:
1. **Unauthenticated HTTP API endpoints** permitting unprivileged read/write access.
2. **State inversion in human approval workflows** allowing rejected requests to be flipped to approved.
3. **Hardcoded static HMAC fallback secrets** exposing event-driven triggers to signature spoofing.
4. **Plaintext credential storage** in enterprise connectors.

---

## 2. Vulnerability Catalog

### SEC-16.1-01: Unauthenticated and Unrestricted FastAPI Endpoints
- **Severity:** HIGH (CVSS 7.5: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N`)
- **Component:** `packages/atlas-process/src/atlas_process/api.py` (Lines 42–125)
- **Vulnerability Description:**
  The FastAPI router exposes endpoints for registering process definitions (`POST /definitions`), starting instances (`POST /instances`), reading instance state (`GET /instances/{instance_id}`), and deciding human approvals (`POST /approvals/{approval_id}/decide`). None of these routes declare authentication dependencies (e.g. `Depends(verify_jwt)`, `Security(oauth2_scheme)`).
- **Exploitation Scenario:**
  An anonymous actor with network access to the API service can:
  1. Inspect sensitive execution variables, payloads, and internal corporate records across arbitrary tenants by enumerating `instance_id`.
  2. Start arbitrary processes or trigger destructive workflows.
  3. Approve sensitive corporate actions (such as high-value wire transfers or ERP changes) by posting to `/approvals/{approval_id}/decide` with an arbitrary `decided_by` identity.
- **Remediation:**
  1. Implement mandatory authentication middleware on the router.
  2. Inject `CallerIdentity` via FastAPI dependencies and enforce tenant boundaries (`caller.tenant_id == instance.tenant_id`).
  3. Bind approval decision endpoints to verified caller identity rather than trusting the JSON payload's `decided_by` field.

---

### SEC-16.1-02: Human Approval Decision State Inversion & Lack of Terminal State Lock
- **Severity:** HIGH (CVSS 7.3: `CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N`)
- **Component:** `packages/atlas-process/src/atlas_process/approvals.py` (Lines 125–150)
- **Vulnerability Description:**
  In `HumanApprovalEngine.decide`, the logic computes approval status based on cumulative vote counts on every decision:
  ```python
  if approvals_count >= req.required_approvals:
      req.status = ApprovalStatus.APPROVED
      req.resolved_at = datetime.now(timezone.utc)
  elif rejections_count > 0:
      req.status = ApprovalStatus.REJECTED
      req.resolved_at = datetime.now(timezone.utc)
  ```
  If an approval request requires 2 approvals and receives 1 rejection, it enters `REJECTED`. However, if subsequent approvers submit `APPROVED`, `approvals_count >= req.required_approvals` becomes true, which overrides `req.status` back to `APPROVED`. Furthermore, the engine does not prevent recording decisions on requests that are already resolved (`APPROVED`, `REJECTED`, or `EXPIRED`).
- **Exploitation Scenario:**
  A compliance officer explicitly rejects a flagged process execution. A rogue or compromised secondary approver subsequently submits approval votes, flipping the terminal state from `REJECTED` to `APPROVED`, bypassing the security veto.
- **Remediation:**
  1. Enforce terminal state immutability: If `req.status != ApprovalStatus.PENDING`, reject all incoming decisions with an `IllegalStateError`.
  2. Implement strict rejection veto: Once any required rejection threshold is reached, permanently seal the request as `REJECTED`.

---

### SEC-16.1-03: Hardcoded Default HMAC Secret in Event Triggers
- **Severity:** MEDIUM (CVSS 6.2: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:N`)
- **Component:** `packages/atlas-process/src/atlas_process/triggers.py` (Line 125)
- **Vulnerability Description:**
  The webhook verification utility sets a static default HMAC secret:
  ```python
  def verify_signature(
      payload: bytes,
      signature: str,
      secret: str = "atlas-process-trigger-secret-v16",
  ) -> bool:
  ```
  If callers do not provide a tenant-specific secret, the hardcoded string is utilized.
- **Exploitation Scenario:**
  An external attacker can craft valid HMAC signatures (`X-ATLAS-Signature`) using the published static key `"atlas-process-trigger-secret-v16"`, allowing spoofed webhook events to trigger unauthorized process executions.
- **Remediation:**
  1. Remove default parameter values for secrets.
  2. Require callers to supply a tenant-specific, cryptographically generated webhook secret retrieved from secret storage.

---

### SEC-16.1-04: Plaintext In-Memory Connector Credential Storage
- **Severity:** MEDIUM (CVSS 5.5: `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N`)
- **Component:** `packages/atlas-process/src/atlas_process/connectors.py` (Lines 85–98)
- **Vulnerability Description:**
  Enterprise connectors (`ERPConnector`, `CRMConnector`, etc.) accept API keys, access tokens, and passwords as raw Python strings and store them in an unencrypted in-memory dictionary `self._credentials`.
- **Exploitation Scenario:**
  Any memory inspection, heap dump, or unhandled exception logging can leak enterprise ERP/CRM service credentials.
- **Remediation:**
  1. Wrap credential fields with Pydantic's `SecretStr` or `atlas-enterprise` credential vault.
  2. Zero credentials in memory after connector lifecycle completion.

---

### SEC-16.1-05: Missing Cross-Tenant Isolation in Engine Lookups
- **Severity:** LOW (CVSS 4.3: `CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N`)
- **Component:** `packages/atlas-process/src/atlas_process/engine.py` (Line 185)
- **Vulnerability Description:**
  `ProcessExecutionEngine.get_instance(instance_id)` takes only `instance_id` without validating caller `tenant_id`.
- **Exploitation Scenario:**
  A tenant user who learns an `instance_id` belonging to another tenant can inspect process status and output variables.
- **Remediation:**
  Update signature to `get_instance(instance_id: str, tenant_id: str)` and raise `PermissionError` on tenant mismatch.

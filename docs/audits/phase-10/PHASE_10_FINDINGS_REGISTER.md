# ATLAS Phase 10 — Independent Audit Findings Register

**Document Version:** 1.0.0  
**Phase Under Audit:** Phase 10 — Enterprise Autonomous Operating Platform  
**Audited Commit:** `d4c735d`  
**Base Commit:** `d858f6c`  
**Date:** 2026-11-14  
**Audit Status:** Complete  

---

## 1. Findings Summary & Severity Distribution

| Severity | Count | Summary of Issues |
|---|---|---|
| **CRITICAL** | 3 | Unauthenticated REST API (SEC-01), Cross-Tenant Connector Invocation (SEC-02), Pure In-Memory Ephemeral Architecture (ARCH-01) |
| **HIGH** | 3 | Orphaned Agent Self-Elevation Guard (SEC-03), Unhandled AttributeError on Missing Org (REL-01), Superficial/Tautological Deployment & DR Tests (OPS-01) |
| **MEDIUM** | 2 | Cryptographic Hash Failure on Non-JSON Details (REL-02), Stubbed Dashboard Handlers & Missing List APIs (UI-01) |
| **LOW** | 1 | Rate Limiter Sliding Window Memory Scaling under high RPM (PERF-01) |
| **INFORMATIONAL** | 1 | Vault Secrets Plain-Text Memory Storage without AES-256 At-Rest Encryption (SEC-04) |
| **TOTAL** | **10** | **3 CRITICAL, 3 HIGH, 2 MEDIUM, 1 LOW, 1 INFORMATIONAL** |

---

## 2. Detailed Findings Register

### Finding SEC-01: Unauthenticated Administrative Access & Tenant Takeover via REST API
- **Finding ID**: `ATLAS-P10-SEC-01`
- **Severity**: **CRITICAL**
- **CWE**: CWE-306 (Missing Authentication for Critical Function), CWE-862 (Missing Authorization)
- **Component**: `apps/api/src/atlas_api/routes/enterprise.py` (lines 196–303, 337–361, 428–454, 564–657)
- **Technical Explanation**:
  Enterprise API routes accept caller identifiers as unverified JSON fields or query strings (e.g. `payload.caller_user_id`) or require no caller identification at all. No endpoints enforce `Authorization: Bearer <session_token>` or call `iam.validate_session()`.
- **Attack Vector & Impact**:
  An unauthenticated remote attacker can call `POST /api/v1/enterprise/organizations/{victim_org_id}/members` specifying `role: "OrganizationOwner"` to hijack administrative ownership of any tenant. Additionally, any caller can call `POST /organizations/{org_id}/suspend` to take down tenant operations.
- **Empirical Evidence**:
  Reproduced and verified in `tests/audit/test_adversarial_security.py::test_audit_sec_01_api_endpoints_lack_authentication_headers` and `test_audit_sec_02_unauthenticated_owner_elevation_via_api`.
- **Remediation**:
  Implement a FastAPI dependency (`get_current_session(authorization: str = Header(...)) -> SessionToken`) that extracts and validates the Bearer token, asserts active membership in the target organization, and attaches the verified session to the request.

---

### Finding SEC-02: Cross-Tenant Connector Invocation & Unauthorized Third-Party Execution
- **Finding ID**: `ATLAS-P10-SEC-02`
- **Severity**: **CRITICAL**
- **CWE**: CWE-862 (Missing Authorization), CWE-639 (Authorization Bypass Through User-Controlled Key)
- **Component**: `packages/atlas-enterprise/src/atlas_enterprise/integrations.py` (lines 375–415) & `apps/api/src/atlas_api/routes/enterprise.py` (lines 505–529)
- **Technical Explanation**:
  `IntegrationHubManager.invoke_connector(caller_id, connector_id, action_name, parameters)` does not verify that `caller_id` belongs to the organization that owns `connector_id`, nor does it verify that the caller holds `PermissionAction.INTEGRATION_INVOKE`.
- **Attack Vector & Impact**:
  A compromised agent, worker, or malicious user in Tenant B can invoke verified connectors in Tenant A (Salesforce, Slack, Jira, external webhooks) and execute arbitrary actions using Tenant A's vaulted third-party API credentials.
- **Empirical Evidence**:
  Reproduced and verified in `tests/audit/test_adversarial_tenant_isolation.py::test_audit_iso_01_cross_tenant_connector_invocation_vulnerability`.
- **Remediation**:
  In `invoke_connector`, call `self.iam_engine.assert_permission(user_id=caller_id, org_id=record.org_id, action=PermissionAction.INTEGRATION_INVOKE)` and check `record.department_id` boundary against caller context.

---

### Finding ARCH-01: Pure Ephemeral In-Memory Architecture Decoupled from Persistent Storage
- **Finding ID**: `ATLAS-P10-ARCH-01`
- **Severity**: **CRITICAL**
- **Component**: Entire `packages/atlas-enterprise/` subsystem
- **Technical Explanation**:
  All enterprise domain models are stored in Python dictionaries (`self._orgs`, `self._departments`, `self._users`, `self._memberships`, `self._sessions`, `self._agents`, `self._policies`, `self._connectors`, `self._secrets`, `self._chains`, `self._budgets`). There is zero integration with `packages/atlas-storage` and zero database tables or DDL schemas in PostgreSQL/SQLite.
- **Attack Vector & Impact**:
  100% data loss occurs whenever the server process restarts, crashes, or is redeployed. It is impossible to run multiple API workers or horizontally scale instances because in-memory state cannot be shared across processes.
- **Empirical Evidence**:
  Reproduced in `tests/audit/test_adversarial_reliability.py::test_audit_rel_04_ephemeral_state_loss_on_system_restart`.
- **Remediation**:
  Define PostgreSQL/SQLite DDL tables for all 25 enterprise domain entities in `packages/atlas-storage`. Implement repository interfaces in `packages/atlas-enterprise` with SQLite/PostgreSQL storage adapters.

---

### Finding SEC-03: Orphaned Agent Self-Elevation Guard
- **Finding ID**: `ATLAS-P10-SEC-03`
- **Severity**: **HIGH**
- **CWE**: CWE-250 (Execution with Unnecessary Privileges)
- **Component**: `packages/atlas-enterprise/src/atlas_enterprise/agent_governance.py` (lines 420–437)
- **Technical Explanation**:
  `check_agent_self_elevation` is defined on `EnterpriseAgentGovernanceManager`, but is never invoked by `EnterpriseIAMEngine.assign_role`, `EnterpriseAgentGovernanceManager.set_policy`, or any API route. It exists only within unit test assertions.
- **Attack Vector & Impact**:
  If an autonomous agent (`ag_*`) or service identity (`svc_*`) obtains an administrative role or calls IAM methods directly, it can reassign roles or modify policies without triggering the self-elevation guard.
- **Empirical Evidence**:
  Reproduced and verified in `tests/audit/test_adversarial_security.py::test_audit_sec_03_agent_self_elevation_guard_is_orphaned`.
- **Remediation**:
  Hook `check_agent_self_elevation` directly into `EnterpriseIAMEngine.assign_role`, `EnterpriseAgentGovernanceManager.set_policy`, and the REST API authorization middleware.

---

### Finding REL-01: Unhandled `AttributeError` on Missing Organization in Session Creation
- **Finding ID**: `ATLAS-P10-REL-01`
- **Severity**: **HIGH**
- **CWE**: CWE-476 (NULL Pointer Dereference)
- **Component**: `packages/atlas-enterprise/src/atlas_enterprise/iam.py` (lines 273–275)
- **Technical Explanation**:
  `create_session` executes `org = self.org_manager.get_organization(org_id)` and immediately evaluates `if org.status != "ACTIVE":`. If `org_id` is invalid, `org` is `None`, raising `AttributeError: 'NoneType' object has no attribute 'status'`.
- **Attack Vector & Impact**:
  Unhandled 500 error and crash on API calls passing invalid or mistyped organization identifiers. Violates ATLAS Constitution Rule 5.
- **Empirical Evidence**:
  Reproduced in `tests/audit/test_adversarial_reliability.py::test_audit_rel_02_attribute_error_on_nonexistent_org_in_iam`.
- **Remediation**:
  Add `if not org: raise OrganizationNotFoundError(f"Organization '{org_id}' not found")` before accessing `org.status`.

---

### Finding OPS-01: Superficial / Tautological Acceptance Scenarios for Deployment & DR
- **Finding ID**: `ATLAS-P10-OPS-01`
- **Severity**: **HIGH**
- **Component**: `tests/integration/test_phase10_acceptance.py` (scenarios EP-27, EP-28, EP-30)
- **Technical Explanation**:
  - `test_ep27` only asserts string matches (`"postgres"` in `compose.yaml`).
  - `test_ep28` writes an in-memory dictionary entry and asserts the list has length 1.
  - `test_ep30` only asserts `assert org_mgr is not None`.
- **Impact**:
  Acceptance tests gave false assurance of production deployment readiness and disaster recovery capabilities without executing real validation.
- **Remediation**:
  Replace with real integration tests spinning up embedded PostgreSQL, running database migrations, executing SQL dumps/restores, and asserting multi-tenant schema isolation.

---

### Finding REL-02: Cryptographic Serialization Failure on Non-JSON-Serializable Details
- **Finding ID**: `ATLAS-P10-REL-02`
- **Severity**: **MEDIUM**
- **Component**: `packages/atlas-enterprise/src/atlas_enterprise/audit.py` (lines 56–58)
- **Technical Explanation**:
  `compute_record_hash` uses `json.dumps(canonical_dict)` without custom serializers. If `details` contains sets, custom classes, or non-serializable objects, `TypeError` is raised, causing audit logging and task execution to fail.
- **Empirical Evidence**:
  Reproduced in `tests/audit/test_adversarial_reliability.py::test_audit_rel_03_non_serializable_details_in_audit_record`.
- **Remediation**:
  Use `json.dumps(canonical_dict, default=str, sort_keys=True, separators=(",", ":"))` or Pydantic's JSON serializer.

---

### Finding UI-01: Stubbed Dashboard Handlers and Missing List Endpoints
- **Finding ID**: `ATLAS-P10-UI-01`
- **Severity**: **MEDIUM**
- **Component**: `apps/api/src/atlas_api/routes/dashboard.py` (lines 1650–1656) & `routes/enterprise.py`
- **Technical Explanation**:
  `loadEnterpriseTenants()` and `loadEnterpriseConnectors()` in the operator dashboard only call `log()`. Furthermore, `routes/enterprise.py` has no GET endpoints to list organizations or connectors.
- **Impact**:
  The Enterprise Admin Console tables never populate and cannot be used to inspect or manage tenants or connectors.
- **Remediation**:
  Add `GET /api/v1/enterprise/organizations` and `GET /api/v1/enterprise/connectors` endpoints and update the dashboard JavaScript to populate table DOM elements dynamically.

---

### Finding PERF-01: Sliding Window Rate Limiter Memory Scaling Under High RPM
- **Finding ID**: `ATLAS-P10-PERF-01`
- **Severity**: **LOW**
- **Component**: `packages/atlas-enterprise/src/atlas_enterprise/integrations.py` (lines 252–270)
- **Technical Explanation**:
  `TokenBucketRateLimiter` retains an unbounded list of timestamps within a 60-second window. At 100,000+ RPM, memory usage scales with call volume.
- **Remediation**:
  Replace with a token bucket with continuous replenishment (`tokens = min(max_tokens, tokens + elapsed * rate)`).

---

### Finding SEC-04: Plain-Text In-Memory Storage of Vaulted Connector Secrets
- **Finding ID**: `ATLAS-P10-SEC-04`
- **Severity**: **INFORMATIONAL**
- **Component**: `packages/atlas-enterprise/src/atlas_enterprise/integrations.py` (`IntegrationSecretStore`)
- **Technical Explanation**:
  Third-party credentials stored in `IntegrationSecretStore` reside as plain strings in heap memory without envelope encryption.
- **Remediation**:
  Encrypt vaulted secrets in memory and at rest using AES-256-GCM backed by a master key derived from environment or KMS.

# ATLAS Phase 10 — Remediation Plan & Engineering Roadmap

**Document Version:** 1.0.0  
**Phase Under Audit:** Phase 10 — Enterprise Autonomous Operating Platform  
**Target Release:** ATLAS v0.10.1-rc1 / Phase 10.1 Remediation  
**Date:** 2026-11-14  
**Audit Status:** Remediation Roadmap Defined (Awaiting Authorization)  

---

## 1. Remediation Strategy & Guiding Principles

This remediation plan provides an actionable, prioritized roadmap to resolve all 10 findings identified during the Phase 10 Independent Audit.

### Core Rules:
1. **Audit-Only Constraint**: In accordance with the audit mandate, **no production code will be modified until explicit authorization is granted by project leadership**.
2. **Prioritization**: CRITICAL and HIGH severity findings must be fully remediated and verified before any release candidate can be certified.
3. **Verification Invariant**: Every remediation step requires automated, deterministic regression and adversarial tests before sign-off.

---

## 2. Prioritized Remediation Milestones

```
+---------------------------------------------------------------------------------+
|                         PHASE 10.1 REMEDIATION MILESTONES                       |
+---------------------------------------------------------------------------------+
|  [R1: Security Hardening]       -> SEC-01 (API Auth), SEC-02 (Connector Auth),  |
|                                    SEC-03 (Agent Self-Elevation Guard)          |
|  [R2: Database Persistence]     -> ARCH-01 (PostgreSQL/SQLite DDL & Storage)    |
|  [R3: Reliability & Exceptions] -> REL-01 (None check), REL-02 (JSON serialize) |
|  [R4: UI & API Completeness]    -> UI-01 (Listing endpoints & dashboard DOM)    |
|  [R5: Operational Acceptance]   -> OPS-01 (Rigorous deployment & DR testing)    |
+---------------------------------------------------------------------------------+
```

---

### Milestone R1: Critical Security Hardening (Sprint 1 — Days 1–3)
**Primary Objective**: Eliminate unauthorized access, cross-tenant connector invocations, and agent self-elevation.

#### Task R1.1: REST API Authentication & Session Token Middleware (`SEC-01`)
- **Action**:
  1. Create `get_current_session` FastAPI dependency in `apps/api/src/atlas_api/dependencies.py` using `fastapi.security.HTTPBearer`.
  2. Validate presented session token against `EnterpriseIAMEngine.validate_session()`.
  3. Extract `user_id`, `org_id`, `role`, and `department_id` directly from the validated session.
  4. Protect all `/api/v1/enterprise/*` routes with `Depends(get_current_session)`. Reject requests where target resource `org_id` differs from session `org_id`.
- **Acceptance Criteria**:
  - `POST /organizations/{org_id}/members` returns 401/403 for unauthenticated or non-admin callers.
  - `POST /organizations/{org_id}/suspend` requires validated `OrganizationOwner` or `SecurityAdmin` session.

#### Task R1.2: Tenant Boundary & Permission Check on Connector Invocation (`SEC-02`)
- **Action**:
  1. In `IntegrationHubManager.invoke_connector(caller_id, connector_id, action_name, parameters)`:
     ```python
     record = self.get_connector(connector_id)
     self.iam_engine.assert_permission(
         user_id=caller_id,
         org_id=record.org_id,
         action=PermissionAction.INTEGRATION_INVOKE,
     )
     ```
  2. Verify caller belongs to `record.org_id` and (if configured) `record.department_id`.
- **Acceptance Criteria**:
  - User B from Org B cannot invoke Org A's connector; raises `UnauthorizedError` or `CrossTenantAccessViolationError`.

#### Task R1.3: Wire Agent Privilege Self-Elevation Guard (`SEC-03`)
- **Action**:
  1. In `EnterpriseIAMEngine.assign_role(caller_user_id, ...)`:
     Call `self.gov_manager.check_agent_self_elevation(caller_user_id, "iam:manage_roles")`.
  2. In `EnterpriseAgentGovernanceManager.set_policy(caller_user_id, ...)`:
     Call `self.check_agent_self_elevation(caller_user_id, "policy:update")`.
- **Acceptance Criteria**:
  - Non-human identities (`ag_*`, `worker_*`, `svc_*`) attempting role assignment or policy modifications are halted with `AgentSelfElevationError`.

---

### Milestone R2: Persistence & PostgreSQL Storage Integration (Sprint 2 — Days 4–8)
**Primary Objective**: Transition enterprise domain entities from ephemeral memory to durable PostgreSQL/SQLite storage (`ARCH-01`).

#### Task R2.1: Enterprise DDL Schemas in `packages/atlas-storage`
- **Action**:
  Create migration script `004_enterprise_platform.sql` defining relational tables:
  - `enterprise_organizations`, `enterprise_departments`, `enterprise_teams`, `enterprise_projects`
  - `enterprise_users`, `enterprise_memberships`, `enterprise_sessions`, `enterprise_service_identities`
  - `enterprise_agents`, `enterprise_policies`
  - `enterprise_connectors`, `enterprise_vault_secrets`
  - `enterprise_audit_records` (with indexed sequence and org_id)
  - `enterprise_cost_records`, `enterprise_department_budgets`

#### Task R2.2: Storage Repository Adapters
- **Action**:
  1. Define `EnterpriseStorageRepository` interface in `packages/atlas-enterprise/storage.py`.
  2. Implement SQLite and PostgreSQL adapters using `atlas_storage`.
  3. Inject persistent repository into `EnterpriseOrganizationManager`, `EnterpriseAuditLedger`, etc.
- **Acceptance Criteria**:
  - Restarting the API process preserves all provisioned organizations, users, connectors, audit chains, and budgets.

---

### Milestone R3: Reliability & Structured Exception Handling (Sprint 3 — Days 9–10)
**Primary Objective**: Resolve crashes and unhandled exceptions across edge cases.

#### Task R3.1: Graceful Handling of Missing Organization in Session Creation (`REL-01`)
- **Action**:
  In `EnterpriseIAMEngine.create_session`:
  ```python
  org = self.org_manager.get_organization(org_id)
  if not org:
      raise OrganizationNotFoundError(f"Organization '{org_id}' not found")
  if org.status != OrganizationStatus.ACTIVE:
      raise UnauthorizedError(f"Organization {org_id} is {org.status}")
  ```

#### Task R3.2: Robust Audit Payload JSON Serialization (`REL-02`)
- **Action**:
  In `packages/atlas-enterprise/src/atlas_enterprise/audit.py`:
  ```python
  canonical_json = json.dumps(
      canonical_dict,
      default=str,
      sort_keys=True,
      separators=(",", ":"),
  ).encode("utf-8")
  ```

---

### Milestone R4: UI & API Completeness (Sprint 3 — Days 11–12)
**Primary Objective**: Complete Enterprise Admin Console functionality and listing routes (`UI-01`).

#### Task R4.1: Organization and Connector Listing Endpoints
- **Action**:
  Add `GET /api/v1/enterprise/organizations` and `GET /api/v1/enterprise/connectors` routes to `apps/api/src/atlas_api/routes/enterprise.py` with pagination and tenant filtering.

#### Task R4.2: Enterprise Admin Console Dashboard Integration
- **Action**:
  Update `loadEnterpriseTenants()` and `loadEnterpriseConnectors()` in `apps/api/src/atlas_api/routes/dashboard.py` to fetch from the listing endpoints and dynamically render table rows.

---

### Milestone R5: Operational Deployment & Rigorous Acceptance Testing (Sprint 4 — Days 13–15)
**Primary Objective**: Replace superficial tests with real operational verification (`OPS-01`).

#### Task R5.1: Real PostgreSQL Integration & Container Tests
- **Action**:
  Replace `test_ep27` with a test spinning up an embedded PostgreSQL instance, running all enterprise migrations, and asserting data persistence.

#### Task R5.2: Database Backup and Multi-Tenant Restore Validation
- **Action**:
  Implement an automated backup script (`scripts/backup_tenant.py`) and replace `test_ep28` with an executable test that dumps a tenant's database schema, restores it to an isolated database, and verifies zero cross-tenant contamination.

---

## 3. Re-Audit Verification Checklist

Before Phase 10 can be recommended for release:
- [ ] All 10 findings verified as closed by re-running `tests/audit/`.
- [ ] Monorepo test suite passes 100% (554+ tests + audit tests).
- [ ] Zero unauthenticated endpoints in `/api/v1/enterprise/*`.
- [ ] Database durability verified across process restarts.
- [ ] Full disaster recovery restore executed and validated against PostgreSQL.

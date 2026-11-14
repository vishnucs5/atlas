# ATLAS Phase 10 Multi-Tenancy & Resource Scoping Model

## 1. Tenancy Hierarchy

ATLAS enforces a 4-level enterprise tenancy and containment hierarchy:

```
Organization (Root Tenant Boundary)
  └── Department (Functional Business Unit & Quota Envelope)
        └── Team (Collaborative Group & Permission Boundary)
              └── Project (Task Graph & Execution Workstream)
```

### Hierarchy Rules:
1. **Strict Tenant Boundaries**: Organizations are completely isolated. No database query, scheduler lease, worker assignment, or audit export may cross organization boundaries under any circumstance.
2. **Departmental Envelopes**: Departments partition budgets, resource limits, and administrator delegations within an organization.
3. **Inheritance Flow**: Policies flow downwards:
   `Organization Policy -> Department Policy -> Team Policy -> Agent Policy`
   More restrictive organization rules always override conflicting lower-level rules.

---

## 2. Resource Ownership Taxonomy

Every persistent object in ATLAS Enterprise implements the `TenantOwnedResource` interface:

| Entity Type | Owner Scope | Isolation Mechanism |
|---|---|---|
| **User Identity** | Organization | Unique email per organization; scoped credentials. |
| **Service Identity** | Department / Project | Cryptographically scoped bearer tokens. |
| **Agent Registration** | Department | Tool allowlists and model adapter constraints. |
| **Workflow Package** | Department / Org | Signature validation and permission scopes. |
| **Distributed Worker** | Organization / Tenant | Enrolled with tenant provisioning token. |
| **Integration** | Department / Org | Vaulted credentials accessible only within scope. |
| **Budget Envelope** | Department | Hard spend caps and real token tracking. |
| **Audit Ledger** | Organization | Tamper-evident hash chain partitioned by tenant. |

---

## 3. Persistence-Layer Tenant Isolation Invariant

- Every table schema and document store contains `tenant_id: str` (mapped to `org_id`).
- All storage query operations accept an explicit `tenant_id` parameter. Queries without a tenant constraint are strictly forbidden in production endpoints.
- Adversarial tests in `test_phase10_acceptance.py` verify that requests presenting Tenant A credentials attempting to query Tenant B objects return `404 Not Found` or `403 Forbidden`.

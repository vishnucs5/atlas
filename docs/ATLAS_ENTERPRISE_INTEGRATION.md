# ATLAS Enterprise Integration Architecture

## 1. Overview

ATLAS CLI provides seamless enterprise integration via `atlas-enterprise` packages without compromising the open-source core. When running in enterprise mode, ATLAS CLI connects to centralized Identity and Access Management (IAM), multi-tenant organization hierarchies, fleet policy distribution, and tamper-evident centralized audit ledgers.

---

## 2. Multi-Tenancy & Identity Synchronization

The `EnterpriseClientAdapter` coordinates enterprise connectivity:
1. **User Authentication**: Authenticates against enterprise identity providers, provisioning tenant-scoped JWT session tokens with bounded lifetimes.
2. **Tenant Scoping**: All operations, sessions, and audits are tagged with `tenant_id` and `org_id`.
3. **Role-Based Access Control (RBAC)**:
   Enforces a strict privilege hierarchy:
   ```
   ORG_OWNER (5) > ORG_ADMIN / SECURITY_ADMIN (4) > DEPT_ADMIN (3) > DEVELOPER (2) > AUDITOR / VIEWER (1)
   ```
   Unauthorized operations trigger `UnauthorizedError` before any model action or tool execution begins.

---

## 3. Fleet Policy Distribution

Enterprise organizations distribute mandatory security rules to local CLI `ActionFirewall` instances:
- Rules are fetched upon session establishment via `distribute_enterprise_policies(firewall)`.
- Enforces enterprise invariants such as blocking credential modification (`ent_block_creds_<tenant>`), restricting untrusted external hosts, or requiring human approval for high-risk operations.
- Local developers cannot disable or delete enterprise-distributed firewall rules.

---

## 4. Cryptographic Tamper-Evident Centralized Audit Ledger

All significant developer actions (logins, workflow deployments, tool executions, privilege escalations) are forwarded to the centralized `EnterpriseAuditLedger`:
- Every audit record contains:
  - Sequence number
  - Tenant ID & Actor ID
  - Action & Target Resource
  - ISO-8601 UTC Timestamp
  - Prior Record Hash
  - SHA-256 Digest of Canonical Record JSON + Prior Hash
- Forms an immutable, mathematically verifiable audit chain enabling enterprise compliance audits (SOC2, ISO 27001, HIPAA).

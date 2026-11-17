# ATLAS Phase 16.2 API Security & Multi-Tenant Authorization
## Defense-in-Depth for REST Process APIs

**Date:** 2026-11-17  
**Module:** `packages/atlas-process/src/atlas_process/auth.py` and `api.py`  
**Verification Suite:** `tests/unit/test_phase16_2_api_auth.py`  

---

## 1. Vulnerability Background (Audit Finding REM-16.1-03)

The Phase 16.1 audit discovered that all 5 REST endpoints exposed by `atlas_process.api` were completely unprotected:
- Zero authentication: Any anonymous HTTP request could start processes, trigger tasks, and view data.
- Zero tenant authorization: Request parameters like `tenant_id` were taken from the request body without verifying caller tenant membership, allowing complete cross-tenant access.
- Approval impersonation: An attacker could submit approval decisions specifying an arbitrary `approver_id` in the JSON payload, bypassing human approval governance.

---

## 2. Hardened Security Architecture

### 2.1 Mandatory Authentication via `Depends(get_current_identity)`
All endpoints now enforce authentication via FastAPI dependency injection:
```python
@router.post("/instances", status_code=status.HTTP_201_CREATED)
def start_process_instance(
    req: StartProcessRequest,
    caller: ProcessCallerIdentity = Depends(get_current_identity),
) -> dict[str, Any]:
...
```
Any request lacking credentials immediately returns `401 Unauthorized` before any process logic is invoked.

### 2.2 Supported Credential Types
1. **Cryptographically Signed HMAC Bearer Tokens (`atk_proc_`):**
   - Contains claims: `sub` (caller ID), `tid` (tenant ID), `roles`, `scopes`, `exp` (expiration), `iat` (issued at), and `jti` (unique nonce).
   - Tamper-evident: Signature validated using constant-time comparison (`hmac.compare_digest`).
   - Rejects expired or structurally malformed tokens with 401.
2. **API Keys (`X-API-Key` or `Authorization: Bearer <key>`):**
   - Cryptographically hashed using SHA-256 and matched against secure key registry or `EnterpriseIAMEngine.authenticate_api_key`.
3. **Enterprise IAM Session Tokens:**
   - Seamlessly integrates with Phase 10 `EnterpriseIAMEngine.validate_session(token)`.

### 2.3 Strict Multi-Tenant Isolation
- The authenticated identity's `tenant_id` is authoritative.
- When an API caller attempts to access a resource (instance, definition, approval, or analytics) belonging to a different tenant, `verify_tenant_access(caller, target_tenant_id)` raises `HTTPException(403, detail="Cross-tenant access forbidden")`.
- Only callers possessing `ADMIN`, `SYSTEM_ADMIN`, or `SUPERADMIN` roles are permitted to cross tenant boundaries for operational oversight.

### 2.4 Prevention of Approval Impersonation
In `POST /approvals/{approval_id}/decide`:
- The caller's authenticated identity (`caller.caller_id`) is strictly bound to the decision.
- If the body specifies an `approver_id` that differs from `caller.caller_id`, the system rejects the call with `403 Forbidden` unless the caller is a verified administrator.
- Rejection decisions immediately and permanently seal the request as `REJECTED`, preventing approval reversals.

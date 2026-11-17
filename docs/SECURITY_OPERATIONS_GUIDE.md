# ATLAS Security Operations Guide (SecOps)

## 1. Principles of ATLAS Security Operations

1. **Defense-in-Depth:** Action Firewall + SSRF IP Pinning + Database Tenant Scoping + Immutable Audit Logs.
2. **Zero-Trust Network:** Pod egress restricted via NetworkPolicies; all connector endpoints validated at connection time.
3. **Secret Isolation:** Passwords, API tokens, and private keys never stored in database definitions or serialized into logs.

---

## 2. Daily Security Operations Tasks

1. **Review Failed Authentication Logs:**
   Inspect 401/403 rate spikes in Prometheus:
   ```promql
   sum(rate(http_requests_total{status=~"401|403"}[5m])) by (tenant_id)
   ```
2. **Inspect Action Firewall Block Events:**
   Query security audit records for blocked operations:
   ```sql
   SELECT timestamp, tenant_id, requesting_identity, action_name, blocked_reason 
   FROM process_security_events 
   WHERE action_firewall_status = 'BLOCKED' 
   ORDER BY timestamp DESC LIMIT 50;
   ```
3. **Inspect Connector Egress Violations:**
   Review blocked private IP / DNS rebinding attempts in connector logs.

---

## 3. Secret Rotation Protocol

1. **Rotating Tenant Webhook Secret:**
   ```bash
   atlas-admin secrets rotate-webhook --tenant=tenant_payments --new-secret=$(openssl rand -hex 32)
   ```
   Both previous and new secrets remain accepted for a 24-hour grace window to allow webhook providers to update.
2. **Rotating Database Application Credentials:**
   Uses dynamic PostgreSQL roles managed by HashiCorp Vault with 30-day lease duration.

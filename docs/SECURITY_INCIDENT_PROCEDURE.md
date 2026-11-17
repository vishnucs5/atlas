# ATLAS Security Incident Handling & Breach Response Procedure

## 1. Scope & Objective

Defines protocol for detecting, containing, investigating, and remediating security incidents targeting the ATLAS platform, including SSRF attempts, prompt injection, unauthorized privilege escalation, cross-tenant leaks, or token compromise.

---

## 2. Emergency Incident Response Protocol

### Phase 1: Identification & Immediate Isolation
1. **Compromised API Key or Bearer Token:**
   - Invalidate the token immediately in the secret manager:
     ```bash
     vault kv delete secret/atlas/tokens/tenant_compromised
     ```
   - Flush active in-memory token caches across all running API instances:
     ```bash
     curl -X POST http://localhost:8000/internal/security/flush-auth-cache -H "X-Security-Admin: $EMERGENCY_KEY"
     ```
2. **SSRF / Malicious Egress Attempt:**
   - Block egress destination at Kubernetes NetworkPolicy level:
     ```bash
     kubectl apply -f k8s/network-policy-emergency-deny.yaml -n atlas-staging
     ```

### Phase 2: Containment & Evidence Preservation
1. Preserve immutable database audit logs:
   ```sql
   COPY (SELECT * FROM process_audit_events WHERE timestamp > NOW() - INTERVAL '24 hours') TO '/var/backups/forensics_audit.csv' CSV HEADER;
   ```
2. Isolate compromised worker container:
   ```bash
   kubectl label pod $SUSPECT_POD quarantine=true -n atlas-staging
   ```

### Phase 3: Post-Incident Remediation & Notification
1. Conduct root cause analysis.
2. Review Action Firewall rules and add explicit rejection rules if attack exploited novel payload syntax.
3. Notify affected tenant administrators within 24 hours of confirmation if tenant data was exposed.

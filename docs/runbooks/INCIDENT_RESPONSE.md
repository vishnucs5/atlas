# Operational Runbook: Incident Response Protocol (IRP)

## 1. Incident Severity Classification

| Severity | Definition | Target Response (SLA) | Target Resolution (RTO) | Examples |
| :--- | :--- | :---: | :---: | :--- |
| **SEV-1 (Critical)** | Core execution network down, multi-tenant boundary compromise, or catastrophic data corruption. | < 5 minutes | < 30 minutes | Control plane unresponsive, cross-tenant data leak, rogue agent self-elevation. |
| **SEV-2 (Major)** | Degraded worker capacity, elevated error rates (> 5%), or single-tenant service outage. | < 15 minutes | < 2 hours | Distributed worker fleet disconnected, external connector failure, rate limit deadlock. |
| **SEV-3 (Minor)** | Non-blocking service degradation, UI anomalies, or slow query latency. | < 1 hour | < 8 hours | Admin dashboard rendering glitch, audit export timeout, non-critical metrics drop. |

---

## 2. Emergency Roles & Incident Command Structure

1. **Incident Commander (IC):** Directs overall response, maintains timeline, enforces containment, makes failover decisions.
2. **Operations & Storage Lead:** Investigates database health, connection pools, disk capacity, and Redis memory.
3. **Security Lead:** Investigates authentication failures, tenant isolation breaches, audit logs, and rogue agent elevation.
4. **Communications Lead:** Updates status page, notifies affected organizational tenant administrators.

---

## 3. Immediate Diagnostic Checklist

Run the following diagnostic sequence within the first 3 minutes of an incident:

```bash
# 1. Check API Liveness and Readiness Probes
curl -i http://localhost:8000/healthz
curl -i http://localhost:8000/readyz

# 2. Check Database Connectivity & Active Connection Count
docker exec -it atlas-postgres-prod psql -U atlas -d atlas_production -c \
  "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"

# 3. Check Redis Latency & Queue Saturation
docker exec -it atlas-redis-prod redis-cli ping
docker exec -it atlas-redis-prod redis-cli info memory

# 4. Inspect OpenTelemetry Prometheus Metrics
curl -s http://localhost:8000/metrics | grep -E "(atlas_active_tasks|atlas_active_workers|atlas_http_requests_total)"

# 5. Check Audit Log Integrity for Breaches
curl -X GET "http://localhost:8000/api/v1/enterprise/audit/verify?org_id=<AFFECTED_ORG>" \
  -H "Authorization: Bearer <ADMIN_KEY>"
```

---

## 4. Remediation & Containment Procedures

### 4.1 Rogue Agent Containment (Emergency Suspension)
If an autonomous agent violates policy or exhibits unexpected destructive behavior:
```bash
# Immediately suspend agent execution via API
curl -X POST "http://localhost:8000/api/v1/enterprise/agents/<AGENT_ID>/status?status=SUSPENDED&reason=EmergencyContainment" \
  -H "Authorization: Bearer <ADMIN_KEY>"
```

### 4.2 Tripped Connector Circuit Breakers
If an external API (e.g. Salesforce or Jira) triggers continuous timeouts:
1. Verify circuit state via `/metrics` (`atlas_circuit_breaker_state`).
2. Circuit breaker automatically enters `OPEN` state and fast-fails within 0.05ms to protect control plane.
3. Once upstream confirms restored health, manually trigger reset or allow automatic probe in `HALF_OPEN`.

### 4.3 Tenant Isolation Leakage Containment
If cross-tenant access is suspected:
1. Immediately invoke administrative tenant suspension:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/enterprise/organizations/<ORG_ID>/suspend?reason=SecurityHold" \
     -H "Authorization: Bearer <ADMIN_KEY>"
   ```
2. Export tamper-evident audit ledger to forensic storage:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/enterprise/audit/export?org_id=<ORG_ID>&format=json" \
     -H "Authorization: Bearer <ADMIN_KEY>" > forensic_audit_<ORG_ID>.json
   ```

---

## 5. Post-Incident Review (PIR)

Within 48 hours of resolution, the Incident Commander must publish a Blameless Post-Mortem addressing:
- Root cause analysis with 5-Whys.
- Detection time vs mitigation time.
- Action items with owner and target commit date.

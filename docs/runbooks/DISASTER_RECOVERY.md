# Operational Runbook: Disaster Recovery & High-Availability Plan

## 1. High-Availability Objectives & Service Level Agreements

- **Recovery Point Objective (RPO):** < 1 minute (achieved via PostgreSQL Write-Ahead Logging / WAL streaming).
- **Recovery Time Objective (RTO):** < 15 minutes (full automated container rebuild and database restore).
- **Audit Immutability Invariant:** Cryptographic SHA-256 hash chains must verify intact without broken sequences after any restore.

---

## 2. Disaster Scenarios & Failover Matrix

| Disaster Scenario | Probability | Impact | Recovery Strategy |
| :--- | :---: | :---: | :--- |
| **Complete Node / Host Failure** | Low | Total Outage | Redeploy via `docker compose -f docker-compose.prod.yml up -d` on backup host; attach persistent storage volume. |
| **Primary Database Corruption** | Very Low | Critical | Point-in-Time Recovery (PITR) from latest base backup + archived WAL segments. |
| **Redis Cache Eviction / Loss** | Low | Low (Temporary) | Redis restart with AOF replay; control plane re-syncs worker leases from PostgreSQL. |
| **Split-Brain Worker Partition** | Medium | Medium | Control plane monotonic fencing tokens reject stale workers (`StaleWorkerError`); zero side-effect duplication. |
| **Tenant Accidental Deletion** | Low | High (Single Org) | Restore isolated tenant tables into staging database; re-import using tenant export archive. |

---

## 3. Step-by-Step System Reconstruction Procedure

In the event of a catastrophic host or infrastructure loss:

### Step 1: Provision Clean Host & Environment
```bash
# Clone repository and checkout release tag
git clone https://github.com/atlas-platform/atlas.git /opt/atlas
cd /opt/atlas

# Copy verified production environment configuration
cp /secure-secrets/.env.production .env.production
```

### Step 2: Restore PostgreSQL Persistent Volume
```bash
# Restore PostgreSQL volume from verified cloud backup snapshot
docker volume create atlas_postgres_data
tar -xzf /backups/atlas_postgres_latest.tar.gz -C /var/lib/docker/volumes/atlas_postgres_data/_data
```

### Step 3: Launch Supporting Infrastructure
```bash
docker compose -f docker-compose.prod.yml up -d atlas-postgres atlas-redis
# Await healthy state
docker compose -f docker-compose.prod.yml ps
```

### Step 4: Launch Control Plane & Workers
```bash
docker compose -f docker-compose.prod.yml up -d
```

### Step 5: Verify Restoration & Integrity
```bash
# Run automated verification probe
curl -f http://localhost:8000/readyz
# Verify SHA-256 audit ledger cryptographic chaining
curl -f "http://localhost:8000/api/v1/enterprise/audit/verify?org_id=*" -H "Authorization: Bearer <ADMIN_KEY>"
```

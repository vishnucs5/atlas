# ATLAS Staging & Production Deployment Runbook

## 1. Scope & Purpose

This runbook defines the standardized, zero-downtime deployment procedure for ATLAS core services, worker pools, and database migrations.

---

## 2. Pre-Deployment Verification Checklist

1. [ ] Target branch verified: clean commit, zero dirty files.
2. [ ] CI quality gate certified: 100% tests passing, zero linter/type errors.
3. [ ] Database backup verified: full snapshot taken within the last 60 minutes.
4. [ ] Secrets verified: all required environment variables present in Vault/K8s Secret.
5. [ ] Maintenance window / traffic draining configured if required.

---

## 3. Step-by-Step Deployment Procedure

### Step 1: Pre-Migration Database Backup
```bash
pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE -F c -b -v -f /backups/atlas_pre_deploy_$(date +%s).dump
```

### Step 2: Forward Database Migrations
Execute migration scripts sequentially:
```bash
atlas-admin migrate up --target=latest
```
Verify schema version:
```bash
psql -h $PGHOST -U $PGUSER -d $PGDATABASE -c "SELECT max(version) FROM schema_migrations;"
```

### Step 3: Rolling Deployment of API Services
Deploy API instances using rolling-update strategy with `maxSurge: 25%`, `maxUnavailable: 0`:
```bash
kubectl rollout restart deployment/atlas-api -n atlas-staging
kubectl rollout status deployment/atlas-api -n atlas-staging --timeout=180s
```

### Step 4: Graceful Worker Drain and Restart
1. Signal worker pods to stop acquiring new task leases:
   ```bash
   curl -X POST http://localhost:8080/internal/workers/drain
   ```
2. Wait for active leases to complete (default max 60s).
3. Rolling restart worker deployments:
   ```bash
   kubectl rollout restart deployment/atlas-worker -n atlas-staging
   kubectl rollout status deployment/atlas-worker -n atlas-staging --timeout=300s
   ```

### Step 5: Post-Deployment Smoke Tests
Execute automated health checks:
```bash
curl -f http://localhost:8000/healthz
curl -f http://localhost:8000/api/v1/status
```
Verify worker heartbeats in database:
```sql
SELECT worker_id, last_heartbeat FROM process_workers WHERE last_heartbeat > NOW() - INTERVAL '30 seconds';
```

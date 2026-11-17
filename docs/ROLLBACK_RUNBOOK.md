# ATLAS Rollback & Emergency Abort Runbook

## 1. Scope & Objective

Defines the emergency procedure to revert an ATLAS deployment to the last known stable state in the event of failure, crash loop, data corruption, or severe performance degradation.

---

## 2. Rollback Triggers

Initiate immediate rollback if any of the following occur within 30 minutes of deployment:
1. API error rate (HTTP 5xx) > 1.0% over a 5-minute rolling window.
2. Worker lease acquisition failure rate > 5.0%.
3. Database connection pool exhaustion or high deadlock frequency.
4. Any regression in Action Firewall or tenant isolation enforcement.

---

## 3. Step-by-Step Rollback Execution

### Step 1: Halt Incoming External Traffic
Drain ingress or set rate-limiting to emergency throttle:
```bash
kubectl annotate ingress atlas-ingress nginx.ingress.kubernetes.io/whitelist-source-range="127.0.0.1/32" --overwrite -n atlas-staging
```

### Step 2: Roll Back Application Deployments
Roll back API and Worker pods to the previous deployment revision:
```bash
kubectl rollout undo deployment/atlas-api -n atlas-staging
kubectl rollout undo deployment/atlas-worker -n atlas-staging
kubectl rollout status deployment/atlas-api -n atlas-staging
kubectl rollout status deployment/atlas-worker -n atlas-staging
```

### Step 3: Revert Database Migrations (If Required)
If schema changes caused the failure and backwards compatibility is broken:
```bash
# Revert to pre-deployment migration version
atlas-admin migrate down --to-version=$PREV_VERSION
```
If schema rollback fails or data is corrupted, restore the physical snapshot:
```bash
pg_restore -h $PGHOST -U $PGUSER -d $PGDATABASE --clean --if-exists /backups/atlas_pre_deploy_$TIMESTAMP.dump
```

### Step 4: Restart Engine and Run Reconciliation
Trigger engine restart recovery to safely mark interrupted in-flight tasks as `UNKNOWN_OUTCOME`:
```bash
curl -X POST http://localhost:8000/internal/recovery/trigger
```

### Step 5: Post-Rollback Health & Verification
1. Verify API responds HTTP 200 on `/healthz`.
2. Inspect logs for exception loops: `kubectl logs -l app=atlas-worker -n atlas-staging --tail=100`.
3. Restore ingress traffic and notify incident commanders.

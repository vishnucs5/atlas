# ATLAS Production Rollback & Emergency Abort Runbook

## 1. Rollback Authority & Authorization

- **Decision Authority:** Release Incident Commander or Lead Systems Engineer.
- **Auto-Rollback Condition:** Helm `--atomic` flag automatically reverts if pod health checks fail within 10 minutes.

---

## 2. Emergency Rollback Execution

### Step 1: Immediate Helm Rollback
```bash
helm rollback atlas-platform -n atlas-prod
kubectl rollout status deployment/atlas-api -n atlas-prod
kubectl rollout status deployment/atlas-worker -n atlas-prod
```

### Step 2: Database Schema Rollback (If Required)
If migration broke backward compatibility:
```bash
kubectl run atlas-rollback-job --image=ghcr.io/atlas/atlas-engine:0.16.8 --restart=Never -- atlas-admin migrate down --to-version=017
kubectl wait --for=condition=complete job/atlas-rollback-job --timeout=300s
```

### Step 3: Trigger Engine Crash Recovery
Restart active execution pods to ensure all in-flight tasks revert safely to `SUSPENDED` / `UNKNOWN_OUTCOME`:
```bash
kubectl rollout restart deployment/atlas-worker -n atlas-prod
```

### Step 4: Verification of Rollback State
```bash
curl -f https://atlas.corp.internal/healthz
atlas-cli status --tenant=corp_prod
```

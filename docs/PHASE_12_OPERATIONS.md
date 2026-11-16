# ATLAS Phase 12 Operations Guide
## Deployment, Upgrades, Rollbacks & Disaster Recovery

---

## 1. Helm Deployment Runbook

### 1.1 Local / Development Cluster
```bash
# 1. Add repository and inspect chart
helm lint deploy/helm/atlas

# 2. Render templates locally
helm template atlas-dev deploy/helm/atlas -f deploy/helm/atlas/values-dev.yaml

# 3. Install chart to local cluster
helm install atlas-dev deploy/helm/atlas \
  --namespace atlas-dev \
  --create-namespace \
  -f deploy/helm/atlas/values-dev.yaml
```

### 1.2 Production Cluster
```bash
# Production installation using external secrets
helm install atlas-prod deploy/helm/atlas \
  --namespace atlas-system \
  --create-namespace \
  -f deploy/helm/atlas/values-prod.yaml \
  --set global.secrets.postgresPasswordSecretKeyRef=atlas-prod-db-secret \
  --set global.secrets.vaultEncryptionKeySecretKeyRef=atlas-prod-vault-secret
```

---

## 2. Upgrade & Rollback Procedures

### 2.1 Controlled Rolling Upgrade
```bash
# Upgrade with rolling update parameters
helm upgrade atlas-prod deploy/helm/atlas \
  --namespace atlas-system \
  -f deploy/helm/atlas/values-prod.yaml \
  --set api.image.tag=0.12.1 \
  --wait --timeout 5m
```

### 2.2 Instant Rollback
```bash
# View revision history
helm history atlas-prod -n atlas-system

# Rollback to previous working revision
helm rollback atlas-prod 1 -n atlas-system
```

---

## 3. Disaster Recovery & Cluster Failover

### 3.1 Primary Cluster Failure Scenario
1. **Detection**: Control Plane marks primary cluster `Disconnected` after 3 consecutive heartbeat failures (45s).
2. **Worker Fencing**: Primary cluster workers are fenced; their leases are invalidated in the distributed database.
3. **Queue Failover**: Pending and unacknowledged tasks are re-queued with incremented attempt numbers.
4. **Secondary Cluster Placement**: Secondary cluster operator spins up additional worker replicas via `AtlasWorkerPool` based on queue depth.
5. **State Reconciliation**: Resumed tasks replay state from the latest validated checkpoint in PostgreSQL.

### 3.2 Database Restoration
Follow database disaster recovery playbook in `docs/runbooks/DATABASE_BACKUP_RESTORE.md` to restore PostgreSQL point-in-time state before restarting the API and Supervisor pods.

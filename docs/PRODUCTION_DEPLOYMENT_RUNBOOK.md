# ATLAS Production Deployment Runbook

## 1. Release Governance & Authority

- **Release Authority:** ATLAS Release Engineering Committee & Lead Architect.
- **Deployment Window:** Off-peak maintenance window (Tuesday or Thursday 02:00–04:00 UTC).
- **Required Quorum:** Minimum 2 authorized release engineers present.

---

## 2. Infrastructure Prerequisites

1. PostgreSQL 18.6+ HA cluster with read-replica and PITR WAL archiving.
2. Kubernetes cluster (v1.28+) with NetworkPolicies and PodDisruptionBudgets configured.
3. Vault / SealedSecrets integration providing production secrets.
4. Prometheus & Grafana alerting operational.

---

## 3. Production Deployment Execution Steps

### Phase 1: Pre-Flight Verification
```bash
# Verify cluster status
kubectl get nodes
kubectl top nodes
# Verify current release revision
helm list -n atlas-prod
```

### Phase 2: Database Snapshot & Migration
```bash
# 1. Trigger cloud volume snapshot
aws rds create-db-snapshot --db-instance-identifier atlas-prod-db --db-snapshot-identifier atlas-pre-0-16-8-$(date +%s)

# 2. Run schema migrations
kubectl run atlas-migrate-job --image=ghcr.io/atlas/atlas-engine:0.16.8 --restart=Never -- atlas-admin migrate up
kubectl wait --for=condition=complete job/atlas-migrate-job --timeout=300s
```

### Phase 3: Rolling Application Upgrade
```bash
helm upgrade atlas-platform ./helm/atlas-platform \
  --namespace atlas-prod \
  --set image.tag=0.16.8 \
  --set replicas.api=4 \
  --set replicas.workers=8 \
  --atomic --timeout 10m
```

### Phase 4: Production Smoke Testing
1. Execute health probes:
   ```bash
   curl -f https://atlas.corp.internal/healthz
   ```
2. Verify worker fleet registration:
   ```bash
   curl -H "Authorization: Bearer $PROD_ADMIN_TOKEN" https://atlas.corp.internal/api/v1/workers/status
   ```
3. Run canary synthetic workflow:
   ```bash
   atlas-cli process start --def=canary_synthetic_v1 --tenant=corp_prod
   ```

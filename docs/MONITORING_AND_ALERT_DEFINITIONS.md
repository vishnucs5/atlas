# ATLAS Monitoring Dashboard & Alert Definitions

## 1. Metrics Architecture

ATLAS emits Prometheus-compatible metrics across API, worker, database, and business workflow dimensions.

---

## 2. Core Prometheus Metrics

| Metric Name | Type | Description |
| :--- | :--- | :--- |
| `atlas_process_instances_total` | Counter | Total process instances started by tenant and status |
| `atlas_process_duration_seconds` | Histogram | End-to-end process execution duration |
| `atlas_task_lease_acquisitions_total` | Counter | Worker lease acquisition attempts by outcome |
| `atlas_task_fencing_rejections_total` | Counter | Number of tasks rejected due to stale fencing tokens |
| `atlas_approval_requests_pending` | Gauge | Current number of active pending human approvals |
| `atlas_idempotency_unknown_outcomes_total` | Counter | Tasks flagged with ambiguous outcome requiring reconciliation |
| `atlas_connector_circuit_breaker_state` | Gauge | Circuit breaker state (0=Closed, 1=Half-Open, 2=Open) |
| `atlas_database_connection_pool_active` | Gauge | Active connections checked out of the pool |

---

## 3. Production Alert Definitions

### Alert 1: StaleWorkerFencingRejectionSpike
```yaml
alert: StaleWorkerFencingRejectionSpike
expr: rate(atlas_task_fencing_rejections_total[5m]) > 2
for: 2m
labels:
  severity: warning
annotations:
  summary: "Spike in stale worker lease fencing rejections"
  description: "Worker nodes are attempting to complete tasks with outdated fencing tokens. Possible worker starvation or clock drift."
```

### Alert 2: ReconciliationRequiredQueueNonZero
```yaml
alert: ReconciliationRequiredQueueNonZero
expr: atlas_idempotency_unknown_outcomes_total > 0
for: 5m
labels:
  severity: high
annotations:
  summary: "Operations waiting in reconciliation queue"
  description: "One or more irreversible task operations experienced unknown outcomes and require manual or automated reconciliation."
```

### Alert 3: DatabaseConnectionPoolSaturation
```yaml
alert: DatabaseConnectionPoolSaturation
expr: (atlas_database_connection_pool_active / 20) > 0.85
for: 3m
labels:
  severity: critical
annotations:
  summary: "Database connection pool near exhaustion (> 85%)"
  description: "High database concurrency or slow query holding connections."
```

### Alert 4: ConnectorCircuitBreakerTripped
```yaml
alert: ConnectorCircuitBreakerTripped
expr: atlas_connector_circuit_breaker_state == 2
for: 1m
labels:
  severity: high
annotations:
  summary: "Enterprise connector circuit breaker OPEN"
  description: "Connector tripped due to repeated failures or timeouts to external endpoint."
```

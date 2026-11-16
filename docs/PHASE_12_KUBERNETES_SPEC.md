# ATLAS Phase 12 Kubernetes Specification
## Custom Resource Definitions & Controller Contract

---

## 1. Custom Resource Definitions (CRDs)

All custom resources are registered under group `atlas.io` with API version `v1alpha1`.

### 1.1 `AtlasCluster` (`atlas.io/v1alpha1`)
Represents an enrolled Kubernetes cluster or execution environment within the multi-cluster topology.

```yaml
apiVersion: atlas.io/v1alpha1
kind: AtlasCluster
metadata:
  name: prod-us-east
spec:
  clusterId: "cls_useast_01"
  region: "us-east-1"
  provider: "aws-eks"
  apiEndpoint: "https://api.eks.us-east-1.amazonaws.com"
  credentialsSecretRef:
    name: "eks-us-east-creds"
    namespace: "atlas-system"
  capabilities:
    platforms: ["linux/amd64"]
    gpuModels: ["NVIDIA-A100-80GB", "NVIDIA-H100-80GB"]
    maxConcurrentWorkers: 500
    supportsDesktopSession: false
  tenantAllowedList: ["org_enterprise_01", "org_enterprise_02"]
status:
  phase: "Healthy" # Healthy | Degraded | Disconnected | Revoked
  registeredAt: "2026-11-16T22:00:00Z"
  lastHeartbeat: "2026-11-16T22:05:00Z"
  activeWorkers: 142
  latencyMs: 14.2
  conditions:
    - type: "Ready"
      status: "True"
      lastTransitionTime: "2026-11-16T22:00:00Z"
      reason: "ClusterReachable"
      message: "Cluster health probe succeeded"
```

### 1.2 `AtlasWorkerPool` (`atlas.io/v1alpha1`)
Defines an elastic pool of subordinate execution workers with specific capabilities.

```yaml
apiVersion: atlas.io/v1alpha1
kind: AtlasWorkerPool
metadata:
  name: gpu-vision-workers
spec:
  clusterRef: "prod-us-east"
  minReplicas: 2
  maxReplicas: 20
  targetQueueDepthPerWorker: 4
  cooldownPeriodSeconds: 60
  capabilities:
    platform: "linux/amd64"
    gpuRequired: true
    minVramGb: 24
    supportedRuntimes: ["vllm", "cuda-12.4"]
  template:
    image: "atlas/worker:0.12.0"
    resources:
      requests:
        cpu: "4000m"
        memory: "16Gi"
        nvidia.com/gpu: "1"
      limits:
        cpu: "8000m"
        memory: "32Gi"
        nvidia.com/gpu: "1"
status:
  currentReplicas: 4
  readyReplicas: 4
  activeTasks: 12
  scalingPhase: "Stable" # Stable | ScalingUp | ScalingDown | Cooldown
```

### 1.3 `AtlasAgentPool` (`atlas.io/v1alpha1`)
Defines a specialized pool of multi-agent intelligence runtimes (hierarchical planners, specialists).

```yaml
apiVersion: atlas.io/v1alpha1
kind: AtlasAgentPool
metadata:
  name: enterprise-specialists
spec:
  replicas: 3
  agentTypes: ["data-analyst", "security-auditor", "planner"]
  modelRouterRef: "primary-llm-router"
status:
  readyReplicas: 3
  observedGeneration: 1
```

### 1.4 `AtlasExecutionPolicy` (`atlas.io/v1alpha1`)
Defines infrastructure-level security and execution boundaries for worker pods.

```yaml
apiVersion: atlas.io/v1alpha1
kind: AtlasExecutionPolicy
metadata:
  name: strict-tenant-boundary
spec:
  tenantId: "org_enterprise_01"
  allowNetworkEgress: false
  egressAllowlist:
    - "api.salesforce.com"
    - "api.github.com"
  requireGpuEncryption: true
  maxExecutionDurationSeconds: 1800
status:
  enforced: true
  activeViolations: 0
```

### 1.5 `AtlasDeployment` (`atlas.io/v1alpha1`)
Defines a complete cohesive deployment bundle of API, Control Plane, and Worker services.

```yaml
apiVersion: atlas.io/v1alpha1
kind: AtlasDeployment
metadata:
  name: enterprise-deployment
spec:
  version: "0.12.0"
  apiReplicas: 3
  supervisorReplicas: 2
  storageType: "postgresql"
  postgresqlConnectionSecretRef: "postgres-credentials"
status:
  phase: "Running"
  ready: true
```

---

## 2. Controller Reconciliation Invariants

1. **Idempotence**: Every reconciliation turn must yield identical cluster state when given identical inputs.
2. **Drift Recovery**: If a user manually scales or modifies a managed Deployment, the Operator reconciles it back to spec within 15 seconds.
3. **Controlled Upgrades**: Image updates must proceed via rolling updates (`maxSurge: 1, maxUnavailable: 0`), verifying new pod health before terminating older pods.
4. **Finalizer Protection**: Every managed resource registers finalizer `atlas.io/finalizer` to ensure graceful worker drain and state archival prior to deletion.

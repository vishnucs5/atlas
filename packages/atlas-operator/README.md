# ATLAS Kubernetes Operator

`atlas-operator` is the Kubernetes-native controller and infrastructure manager for the ATLAS Autonomous Task & Lifecycle Automation System.

It reconciles custom resources (`AtlasCluster`, `AtlasWorkerPool`, `AtlasAgentPool`, `AtlasExecutionPolicy`, `AtlasDeployment`), executes workload-aware worker autoscaling based on queue depth and task deadlines, and monitors infrastructure health without duplicating ATLAS task orchestration.

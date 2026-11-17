"""ATLAS Autonomous Enterprise Process Execution & Digital Workforce Platform.

Package: atlas-process
Version: 0.16.0
"""

from atlas_process.analytics import (
    ProcessAnalyticsEngine,
    ProcessMetricsSummary,
)
from atlas_process.approvals import (
    ApprovalDecision,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalRecord,
    ApprovalRequest,
    HumanApprovalEngine,
    ParameterTamperedError,
    SeparationOfDutiesViolationError,
    UnauthorizedApproverError,
)
from atlas_process.connectors import (
    BaseEnterpriseConnector,
    CircuitBreakerOpenError,
    CircuitState,
    ConnectorError,
    ConnectorExecutionResult,
    ConnectorRateLimitExceededError,
    ConnectorScopeViolationError,
    ConnectorType,
    CRMConnector,
    ERPConnector,
    TicketingConnector,
)
from atlas_process.definitions import (
    BranchCondition,
    CyclicDependencyError,
    DuplicateTaskIdError,
    InvalidDependencyError,
    ProcessDefinition,
    ProcessDefinitionError,
    ProcessDefinitionStatus,
    ProcessDefinitionValidator,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import (
    LeaseExpiredError,
    ProcessExecutionEngine,
    ProcessInstance,
    ProcessTaskInstance,
    StaleWorkerFencingError,
)
from atlas_process.federation import FederatedProcessDelegator
from atlas_process.security import (
    ActionFirewallBlockedError,
    PrivilegeEscalationError,
    ProcessSecurityError,
    ProcessSecurityGovernor,
    TenantIsolationViolationError,
)
from atlas_process.simulation import (
    ProcessSimulationEngine,
    SimulationResult,
)
from atlas_process.sla import (
    EscalationAction,
    SLAManager,
    SLAPolicy,
    SLATracker,
)
from atlas_process.state_machine import (
    InvalidProcessTransitionError,
    InvalidTaskTransitionError,
    ProcessStateMachine,
    ProcessStatus,
    ProcessTaskStateMachine,
    ProcessTaskStatus,
)
from atlas_process.transactions import (
    NonIdempotentBlindRetryError,
    ReconciliationRequiredError,
    SagaCoordinator,
    SagaError,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
    SagaTransaction,
)
from atlas_process.triggers import (
    BusinessEvent,
    DuplicateEventError,
    EventTriggerEngine,
    ForgedEventError,
    TriggerError,
    TriggerType,
    UnauthorizedTriggerError,
)
from atlas_process.workforce import (
    AssignmentPolicy,
    DigitalWorker,
    WorkerKind,
    WorkforceAllocationEngine,
)

__version__ = "0.16.0"

__all__ = [
    # Definitions
    "TaskType",
    "BranchCondition",
    "ProcessTaskDefinition",
    "ProcessDefinitionStatus",
    "ProcessDefinition",
    "ProcessDefinitionValidator",
    "ProcessDefinitionError",
    "CyclicDependencyError",
    "InvalidDependencyError",
    "DuplicateTaskIdError",
    # State Machine
    "ProcessStatus",
    "ProcessTaskStatus",
    "ProcessStateMachine",
    "ProcessTaskStateMachine",
    "InvalidProcessTransitionError",
    "InvalidTaskTransitionError",
    # Execution Engine
    "ProcessTaskInstance",
    "ProcessInstance",
    "ProcessExecutionEngine",
    "StaleWorkerFencingError",
    "LeaseExpiredError",
    # Triggers & Events
    "TriggerType",
    "BusinessEvent",
    "EventTriggerEngine",
    "TriggerError",
    "ForgedEventError",
    "DuplicateEventError",
    "UnauthorizedTriggerError",
    # Approvals
    "ApprovalDecision",
    "ApprovalRecord",
    "ApprovalRequest",
    "HumanApprovalEngine",
    "ApprovalError",
    "ParameterTamperedError",
    "SeparationOfDutiesViolationError",
    "UnauthorizedApproverError",
    "ApprovalExpiredError",
    # Sagas & Transactions
    "SagaStepStatus",
    "SagaStatus",
    "SagaStep",
    "SagaTransaction",
    "SagaCoordinator",
    "SagaError",
    "NonIdempotentBlindRetryError",
    "ReconciliationRequiredError",
    # Connectors & Integrations
    "ConnectorType",
    "CircuitState",
    "ConnectorExecutionResult",
    "BaseEnterpriseConnector",
    "ERPConnector",
    "CRMConnector",
    "TicketingConnector",
    "ConnectorError",
    "ConnectorScopeViolationError",
    "ConnectorRateLimitExceededError",
    "CircuitBreakerOpenError",
    # SLA & Escalation
    "EscalationAction",
    "SLAPolicy",
    "SLATracker",
    "SLAManager",
    # Workforce Allocation
    "WorkerKind",
    "AssignmentPolicy",
    "DigitalWorker",
    "WorkforceAllocationEngine",
    # Analytics
    "ProcessMetricsSummary",
    "ProcessAnalyticsEngine",
    # Simulation
    "SimulationResult",
    "ProcessSimulationEngine",
    # Federation
    "FederatedProcessDelegator",
    # Security
    "ProcessSecurityGovernor",
    "ProcessSecurityError",
    "TenantIsolationViolationError",
    "PrivilegeEscalationError",
    "ActionFirewallBlockedError",
]

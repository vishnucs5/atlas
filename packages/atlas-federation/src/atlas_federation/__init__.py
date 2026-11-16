"""ATLAS Federated Autonomous Intelligence Network & Global Agent Interoperability.

Package: atlas-federation
Version: 0.15.0
"""

from atlas_federation.delegation import (
    CrossInstanceDelegationEngine,
    InvalidResultEvidenceError,
    TaskDelegationError,
    TaskExecutionResult,
    TaskProposal,
    TaskProposalRejectedError,
    TaskProposalStatus,
    UnauthorizedDelegationError,
)
from atlas_federation.discovery import (
    CapabilityAdvertisement,
    FederatedCapabilityRegistry,
    VisibilityScope,
)
from atlas_federation.external_adapters import (
    MCPAdapter,
    MCPToolDefinition,
    WebhookAdapter,
)
from atlas_federation.gateway import FederationGateway
from atlas_federation.identity import (
    FederationCredentials,
    FederationIdentityManager,
    ParticipantIdentity,
    TrustRelationship,
)
from atlas_federation.observability import (
    FederatedTraceContext,
    FederationTelemetryCollector,
)
from atlas_federation.protocol import (
    ExpiredMessageError,
    FederationMessage,
    FederationProtocolEngine,
    FederationProtocolError,
    InvalidMessageSignatureError,
    MalformedMessageError,
    MessageType,
    ReplayAttackDetectedError,
)
from atlas_federation.reputation import (
    FederationReputationTracker,
    ParticipantReputation,
)
from atlas_federation.resilience import (
    DurableOutboxEntry,
    OutboxMessageStatus,
    ResilientOutbox,
)
from atlas_federation.security import (
    ActionFirewallTamperError,
    ArtifactAccessDeniedError,
    FederationQuotaExceededError,
    FederationSecurityError,
    FederationSecurityGovernor,
    PeerRateLimitExceededError,
    PeerSecurityPolicy,
    TenantIsolationError,
)
from atlas_federation.workflow_exchange import (
    FederatedPackageError,
    FederatedPackageRecord,
    FederatedWorkflowExchange,
    PackageSignatureInvalidError,
    PackageTamperedError,
    PackageWithdrawnError,
)

__version__ = "0.15.0"

__all__ = [
    # Identity & Trust
    "ParticipantIdentity",
    "FederationCredentials",
    "TrustRelationship",
    "FederationIdentityManager",
    # Capability Discovery
    "VisibilityScope",
    "CapabilityAdvertisement",
    "FederatedCapabilityRegistry",
    # Protocol & Messaging
    "MessageType",
    "FederationMessage",
    "FederationProtocolEngine",
    "FederationProtocolError",
    "ReplayAttackDetectedError",
    "ExpiredMessageError",
    "InvalidMessageSignatureError",
    "MalformedMessageError",
    # Task Delegation
    "TaskProposalStatus",
    "TaskProposal",
    "TaskExecutionResult",
    "CrossInstanceDelegationEngine",
    "TaskDelegationError",
    "TaskProposalRejectedError",
    "InvalidResultEvidenceError",
    "UnauthorizedDelegationError",
    # External Adapters
    "MCPToolDefinition",
    "MCPAdapter",
    "WebhookAdapter",
    # Workflow Exchange
    "FederatedPackageRecord",
    "FederatedWorkflowExchange",
    "FederatedPackageError",
    "PackageTamperedError",
    "PackageSignatureInvalidError",
    "PackageWithdrawnError",
    # Reputation
    "ParticipantReputation",
    "FederationReputationTracker",
    # Security Governor
    "PeerSecurityPolicy",
    "FederationSecurityGovernor",
    "FederationSecurityError",
    "ActionFirewallTamperError",
    "TenantIsolationError",
    "ArtifactAccessDeniedError",
    "PeerRateLimitExceededError",
    "FederationQuotaExceededError",
    # Resilience & Outbox
    "OutboxMessageStatus",
    "DurableOutboxEntry",
    "ResilientOutbox",
    # Observability
    "FederatedTraceContext",
    "FederationTelemetryCollector",
    # Top-Level Gateway
    "FederationGateway",
]

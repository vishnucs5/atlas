"""ATLAS Multi-Agent Intelligence and Autonomous Orchestration Engine."""

from atlas_orchestration.graph_engine import (
    CyclicDependencyError,
    InvalidNodeStateError,
    NodeNotFoundError,
    TaskGraphEngine,
)
from atlas_orchestration.memory import (
    MemoryAccessDeniedError,
    SharedMemoryEngine,
)
from atlas_orchestration.messaging import (
    AgentMessageRouter,
    CircularDelegationError,
    DuplicateMessageError,
    ExpiredMessageError,
    UnauthorizedCrossTaskCommunicationError,
)
from atlas_orchestration.recovery import (
    MultiAgentRecoveryManager,
)
from atlas_orchestration.registry import (
    AgentBudgetExhaustedError,
    AgentNotFoundError,
    AgentRegistry,
    AgentUnavailableError,
)
from atlas_orchestration.reviewer import (
    IndependentReviewer,
    ReviewResult,
    ReviewVerdict,
)
from atlas_orchestration.specialist import (
    BrowserSpecialist,
    CodingSpecialist,
    DataAnalysisSpecialist,
    DesktopSpecialist,
    PolicyViolationError,
    QASpecialist,
    ResearchSpecialist,
    SpecialistAgent,
)
from atlas_orchestration.supervisor import (
    AgentSupervisor,
    OrchestrationError,
    ReviewRejectionError,
)

__version__ = "0.1.0"

__all__ = [
    "AgentBudgetExhaustedError",
    "AgentMessageRouter",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentSupervisor",
    "AgentUnavailableError",
    "BrowserSpecialist",
    "CircularDelegationError",
    "CodingSpecialist",
    "CyclicDependencyError",
    "DataAnalysisSpecialist",
    "DesktopSpecialist",
    "DuplicateMessageError",
    "ExpiredMessageError",
    "IndependentReviewer",
    "InvalidNodeStateError",
    "MemoryAccessDeniedError",
    "MultiAgentRecoveryManager",
    "NodeNotFoundError",
    "OrchestrationError",
    "PolicyViolationError",
    "QASpecialist",
    "ResearchSpecialist",
    "ReviewRejectionError",
    "ReviewResult",
    "ReviewVerdict",
    "SharedMemoryEngine",
    "SpecialistAgent",
    "TaskGraphEngine",
    "UnauthorizedCrossTaskCommunicationError",
]

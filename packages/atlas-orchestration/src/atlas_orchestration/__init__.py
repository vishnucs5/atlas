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
from atlas_orchestration.registry import (
    AgentBudgetExhaustedError,
    AgentNotFoundError,
    AgentRegistry,
    AgentUnavailableError,
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

__version__ = "0.1.0"

__all__ = [
    "AgentBudgetExhaustedError",
    "AgentMessageRouter",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentUnavailableError",
    "BrowserSpecialist",
    "CircularDelegationError",
    "CodingSpecialist",
    "CyclicDependencyError",
    "DataAnalysisSpecialist",
    "DesktopSpecialist",
    "DuplicateMessageError",
    "ExpiredMessageError",
    "InvalidNodeStateError",
    "MemoryAccessDeniedError",
    "NodeNotFoundError",
    "PolicyViolationError",
    "QASpecialist",
    "ResearchSpecialist",
    "SharedMemoryEngine",
    "SpecialistAgent",
    "TaskGraphEngine",
    "UnauthorizedCrossTaskCommunicationError",
]

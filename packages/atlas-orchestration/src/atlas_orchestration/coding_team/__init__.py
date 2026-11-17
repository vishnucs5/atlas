"""ATLAS Multi-Agent Coding Environment and Specialist Engineering Team."""

from atlas_orchestration.coding_team.code_reviewer import (
    CodeReviewFinding,
    CodeReviewResult,
    IndependentCodeReviewer,
)
from atlas_orchestration.coding_team.conflict_detector import (
    ConflictManager,
    ConflictType,
    DetectedConflict,
)
from atlas_orchestration.coding_team.shared_context import (
    CodingSharedContext,
    SharedContextItem,
    TrustLevel,
)
from atlas_orchestration.coding_team.specialists import (
    BackendEngineerSpecialist,
    CodeReviewerSpecialist,
    DatabaseEngineerSpecialist,
    DebuggingEngineerSpecialist,
    DocumentationEngineerSpecialist,
    FrontendEngineerSpecialist,
    InfrastructureEngineerSpecialist,
    RepositoryExplorerSpecialist,
    SecurityAuditorSpecialist,
    SoftwareArchitectSpecialist,
    TestingEngineerSpecialist,
    create_specialist_roster,
)
from atlas_orchestration.coding_team.supervisor import CodingTeamSupervisor
from atlas_orchestration.coding_team.workspace_isolation import (
    AgentWorkspace,
    WorkspaceIsolationManager,
    WorkspaceIsolationMode,
)

__all__ = [
    "AgentWorkspace",
    "BackendEngineerSpecialist",
    "CodeReviewFinding",
    "CodeReviewResult",
    "CodeReviewerSpecialist",
    "CodingSharedContext",
    "CodingTeamSupervisor",
    "ConflictManager",
    "ConflictType",
    "DatabaseEngineerSpecialist",
    "DebuggingEngineerSpecialist",
    "DetectedConflict",
    "DocumentationEngineerSpecialist",
    "FrontendEngineerSpecialist",
    "IndependentCodeReviewer",
    "InfrastructureEngineerSpecialist",
    "RepositoryExplorerSpecialist",
    "SecurityAuditorSpecialist",
    "SharedContextItem",
    "SoftwareArchitectSpecialist",
    "TestingEngineerSpecialist",
    "TrustLevel",
    "WorkspaceIsolationManager",
    "WorkspaceIsolationMode",
    "create_specialist_roster",
]

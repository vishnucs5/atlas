"""ATLAS Autonomous Self-Improvement, Evaluation & Adaptive Intelligence Platform.

Phase 14 implementation: Task Evaluation, Experience Learning, Failure Analysis,
Strategy Optimization, Adaptive Routing, Experimentation, Regression Intelligence,
Agent Analytics, Controlled Knowledge, Safety Governor, and Promotion Management.
"""

from __future__ import annotations

from atlas_adaptive.adaptive_router import (
    AdaptiveModelRouter,
    DataPrivacyRoutingError,
    MediaSensitivity,
    ModelRouteCandidate,
)
from atlas_adaptive.agent_analytics import (
    AgentMetrics,
    AgentPerformanceIntelligence,
)
from atlas_adaptive.evaluator import (
    EvaluationError,
    TaskDomain,
    TaskEvaluationEngine,
    TaskEvaluationMetric,
    TaskEvaluationResult,
)
from atlas_adaptive.experience import (
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceStore,
)
from atlas_adaptive.experimentation import (
    AutomatedExperimentationEngine,
    ExperimentDefinition,
    ExperimentReport,
    ExperimentStatus,
    TrialResult,
)
from atlas_adaptive.failure_analyzer import (
    AttributedCause,
    FailureAnalysisEngine,
    FailureAnalysisResult,
    FailureCategory,
)
from atlas_adaptive.governor import (
    ChangeCategory,
    ProposedChange,
    ProtectedComponentModificationError,
    RiskLevel,
    SafetyGovernor,
    SafetyGovernorError,
    SelfApprovalProhibitedError,
    UnauthorizedPromotionError,
)
from atlas_adaptive.knowledge import (
    ContradictionDetectedError,
    ControlledKnowledgeStore,
    KnowledgeCandidate,
    KnowledgeStatus,
)
from atlas_adaptive.optimizer import (
    OptimizationResult,
    StrategyCandidate,
    StrategyOptimizationEngine,
)
from atlas_adaptive.promotion import (
    PromotionManager,
    PromotionRecord,
    PromotionStage,
)
from atlas_adaptive.regression import (
    BaselineMetric,
    RegressionAlert,
    RegressionIntelligenceSystem,
)

__version__ = "0.14.0"

__all__ = [
    # Task Evaluation
    "TaskDomain",
    "TaskEvaluationMetric",
    "TaskEvaluationResult",
    "TaskEvaluationEngine",
    "EvaluationError",
    # Experience Learning
    "ExperienceOutcome",
    "ExperienceRecord",
    "ExperienceStore",
    # Failure Analysis
    "FailureCategory",
    "AttributedCause",
    "FailureAnalysisResult",
    "FailureAnalysisEngine",
    # Strategy Optimization
    "StrategyCandidate",
    "OptimizationResult",
    "StrategyOptimizationEngine",
    # Adaptive Model Routing
    "MediaSensitivity",
    "ModelRouteCandidate",
    "AdaptiveModelRouter",
    "DataPrivacyRoutingError",
    # Automated Experimentation
    "ExperimentStatus",
    "TrialResult",
    "ExperimentDefinition",
    "ExperimentReport",
    "AutomatedExperimentationEngine",
    # Regression Intelligence
    "BaselineMetric",
    "RegressionAlert",
    "RegressionIntelligenceSystem",
    # Agent Performance Intelligence
    "AgentMetrics",
    "AgentPerformanceIntelligence",
    # Controlled Knowledge
    "KnowledgeStatus",
    "KnowledgeCandidate",
    "ContradictionDetectedError",
    "ControlledKnowledgeStore",
    # Safety Governor
    "RiskLevel",
    "ChangeCategory",
    "ProposedChange",
    "SafetyGovernor",
    "SafetyGovernorError",
    "ProtectedComponentModificationError",
    "UnauthorizedPromotionError",
    "SelfApprovalProhibitedError",
    # Promotion & Rollback
    "PromotionStage",
    "PromotionRecord",
    "PromotionManager",
]

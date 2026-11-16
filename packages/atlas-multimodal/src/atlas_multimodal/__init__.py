"""ATLAS Multimodal Autonomous Perception & Intelligence Platform.

Phase 13 implementation: Visual Perception, Grounding, Audio/Video Intelligence,
Document OCR, Episodic Memory, Perception-Driven Planning, and Distributed Inference.
"""

from __future__ import annotations

from atlas_multimodal.audio import (
    AudioConsentManager,
    AudioConsentToken,
    AudioIntelligenceEngine,
    AudioIntelligenceError,
    AudioObservation,
    TranscriptionSegment,
    UnauthorizedRecordingError,
)
from atlas_multimodal.document import (
    DecompressionBombError,
    DecompressionBombProtector,
    DocumentAnalysisResult,
    DocumentIntelligenceEngine,
    DocumentIntelligenceError,
    DocumentPage,
    ExtractedCell,
    ExtractedTable,
)
from atlas_multimodal.grounding import (
    CoordinateSpace,
    GroundingError,
    OutOfBoundsCoordinateError,
    ScreenGeometry,
    StaleCoordinateGuard,
    StaleObservationError,
    VisualGroundingTransformer,
)
from atlas_multimodal.inference import (
    DataPrivacyRoutingError,
    MediaSensitivity,
    MultimodalInferenceError,
    MultimodalInferenceRouter,
    PromptInjectionDetectedError,
    PromptInjectionScanner,
)
from atlas_multimodal.memory import (
    CrossTenantMemoryAccessViolation,
    MultimodalMemoryError,
    MultimodalMemoryRecord,
    MultimodalMemoryStore,
    TenantContextRequiredError,
)
from atlas_multimodal.perception_planner import (
    PerceptionActionBlockedError,
    PerceptionPlannerBridge,
    PerceptionPlannerError,
    PerceptionUncertaintyError,
    PlannedVisualAction,
)
from atlas_multimodal.provider import (
    MockMultimodalAdapter,
    ModalityNegotiationError,
    MultimodalCapability,
    MultimodalCostAccounting,
    MultimodalError,
    MultimodalModality,
    MultimodalModelAdapter,
    MultimodalRequest,
    MultimodalResponse,
    MultimodalRouter,
    ProviderUnavailableError,
    UnsupportedModalityError,
)
from atlas_multimodal.video import (
    TemporalEvent,
    VideoFrame,
    VideoObservation,
    VideoUnderstandingEngine,
)
from atlas_multimodal.visual import (
    BoundingBox,
    DetectedElement,
    OCRTextBlock,
    UIElementType,
    VisualObservation,
    VisualPerceptionEngine,
)

__version__ = "0.13.0"

__all__ = [
    # Provider & Routing
    "MultimodalModality",
    "MultimodalCapability",
    "MultimodalRequest",
    "MultimodalResponse",
    "MultimodalCostAccounting",
    "MultimodalModelAdapter",
    "MockMultimodalAdapter",
    "MultimodalRouter",
    "MultimodalError",
    "UnsupportedModalityError",
    "ProviderUnavailableError",
    "ModalityNegotiationError",
    # Visual Perception
    "UIElementType",
    "BoundingBox",
    "DetectedElement",
    "OCRTextBlock",
    "VisualObservation",
    "VisualPerceptionEngine",
    # Grounding & Coordinates
    "CoordinateSpace",
    "ScreenGeometry",
    "VisualGroundingTransformer",
    "StaleCoordinateGuard",
    "GroundingError",
    "StaleObservationError",
    "OutOfBoundsCoordinateError",
    # Video Understanding
    "VideoFrame",
    "TemporalEvent",
    "VideoObservation",
    "VideoUnderstandingEngine",
    # Audio Intelligence
    "AudioConsentToken",
    "TranscriptionSegment",
    "AudioObservation",
    "AudioConsentManager",
    "AudioIntelligenceEngine",
    "AudioIntelligenceError",
    "UnauthorizedRecordingError",
    # Document Intelligence
    "ExtractedCell",
    "ExtractedTable",
    "DocumentPage",
    "DocumentAnalysisResult",
    "DecompressionBombProtector",
    "DocumentIntelligenceEngine",
    "DocumentIntelligenceError",
    "DecompressionBombError",
    # Episodic Memory
    "MultimodalMemoryRecord",
    "MultimodalMemoryStore",
    "MultimodalMemoryError",
    "CrossTenantMemoryAccessViolation",
    "TenantContextRequiredError",
    # Perception Planner & Policy
    "PlannedVisualAction",
    "PerceptionPlannerBridge",
    "PerceptionPlannerError",
    "PerceptionUncertaintyError",
    "PerceptionActionBlockedError",
    # Distributed Inference & Security
    "MediaSensitivity",
    "PromptInjectionScanner",
    "MultimodalInferenceRouter",
    "MultimodalInferenceError",
    "PromptInjectionDetectedError",
    "DataPrivacyRoutingError",
]

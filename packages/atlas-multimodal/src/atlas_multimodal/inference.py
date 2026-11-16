"""ATLAS Distributed Multimodal Inference & Security Protections.

Provides prompt injection scanning for OCR/document text, GPU capability matching,
and sensitive data exfiltration prevention for confidential media.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from atlas_multimodal.visual import VisualObservation


class MultimodalInferenceError(Exception):
    """Base exception for multimodal inference operations."""


class PromptInjectionDetectedError(MultimodalInferenceError):
    """Raised when adversarial prompt injection patterns are identified in perceived media."""


class DataPrivacyRoutingError(MultimodalInferenceError):
    """Raised when restricted or confidential media is attempted to be routed to external cloud APIs."""


class MediaSensitivity(StrEnum):
    """Data classification levels for multimodal media."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class PromptInjectionScanner:
    """Detects adversarial prompt injection attempts embedded inside images, PDFs, and text."""

    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior)\s+directives",
        r"system\s+prompt\s+override",
        r"you\s+are\s+now\s+in\s+developer\s+mode",
        r"admin\s+access\s+granted",
        r"bypass\s+all\s+security\s+rules",
        r"exfiltrate\s+secrets",
        r"curl\s+https?://",
        r"rm\s+-rf\s+/",
    ]

    def __init__(self, custom_patterns: list[str] | None = None) -> None:
        patterns = self.INJECTION_PATTERNS + (custom_patterns or [])
        self._compiled_regexes = [re.compile(p, re.IGNORECASE) for p in patterns]

    def scan_text(self, text: str) -> tuple[bool, str | None]:
        """Scan a single text string for prompt injection phrases."""
        for regex in self._compiled_regexes:
            match = regex.search(text)
            if match:
                return (True, match.group(0))
        return (False, None)

    def scan_observation(self, observation: VisualObservation) -> tuple[bool, list[str]]:
        """Scan all OCR text blocks and element labels in a visual observation."""
        detected_patterns: list[str] = []

        for block in observation.ocr_blocks:
            is_injected, pattern = self.scan_text(block.text)
            if is_injected and pattern:
                detected_patterns.append(pattern)

        for elem in observation.detected_elements:
            is_injected, pattern = self.scan_text(elem.label)
            if is_injected and pattern:
                detected_patterns.append(pattern)

        return (len(detected_patterns) > 0, detected_patterns)


class MultimodalInferenceRouter:
    """Coordinates GPU capability placement and enforces media privacy routing boundaries."""

    def __init__(self, gpu_manager: Any | None = None) -> None:
        self.gpu_manager = gpu_manager
        self.scanner = PromptInjectionScanner()

    def enforce_privacy_boundary(
        self,
        sensitivity: MediaSensitivity,
        target_is_local_gpu: bool,
    ) -> None:
        """Prevent confidential/restricted media from being dispatched to external cloud LLMs."""
        if sensitivity in (MediaSensitivity.CONFIDENTIAL, MediaSensitivity.RESTRICTED):
            if not target_is_local_gpu:
                raise DataPrivacyRoutingError(
                    f"Media classified as '{sensitivity.value}' cannot be sent to external "
                    "cloud APIs. On-premises local GPU execution is strictly required."
                )

    def match_gpu_placement(
        self,
        required_vram_gb: float,
        preferred_vendor: str | None = None,
    ) -> str:
        """Find a capable GPU worker node matching memory requirements."""
        if self.gpu_manager is None:
            return "worker_gpu_default"

        # Check GPU inventory if available
        if hasattr(self.gpu_manager, "find_compatible_worker"):
            from atlas_distributed.gpu import GPUWorkloadRequirement

            req = GPUWorkloadRequirement(
                task_id="mm_inference",
                min_vram_gb=required_vram_gb,
                required_vendor=preferred_vendor,
            )
            worker_id = self.gpu_manager.find_compatible_worker(req)
            if worker_id:
                return worker_id
        elif hasattr(self.gpu_manager, "find_capable_worker"):
            worker_id = self.gpu_manager.find_capable_worker(
                required_vram_gb=required_vram_gb,
                preferred_vendor=preferred_vendor,
            )
            if worker_id:
                return worker_id

        # Fallback simulation
        return "worker_gpu_onprem_01"

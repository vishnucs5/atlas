"""ATLAS Visual Perception Engine.

Provides models for UI elements, bounding boxes, OCR blocks, visual observations,
visual hashing, state diffing, and anomaly detection.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class UIElementType(StrEnum):
    """Types of detected graphical user interface elements."""

    BUTTON = "BUTTON"
    INPUT = "INPUT"
    DIALOG = "DIALOG"
    WINDOW = "WINDOW"
    TEXT_BLOCK = "TEXT_BLOCK"
    ICON = "ICON"
    CHECKBOX = "CHECKBOX"
    LINK = "LINK"
    MODAL = "MODAL"


class BoundingBox(BaseModel):
    """Normalized bounding box coordinates in [0.0, 1.0] space."""

    ymin: float
    xmin: float
    ymax: float
    xmax: float

    @field_validator("ymin", "xmin", "ymax", "xmax")
    @classmethod
    def check_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Coordinate must be in range [0.0, 1.0], got {v}")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.ymin > self.ymax:
            raise ValueError(f"ymin ({self.ymin}) cannot be greater than ymax ({self.ymax})")
        if self.xmin > self.xmax:
            raise ValueError(f"xmin ({self.xmin}) cannot be greater than xmax ({self.xmax})")

    @property
    def center_point(self) -> tuple[float, float]:
        """Returns the normalized (x_center, y_center) coordinates."""
        return (round((self.xmin + self.xmax) / 2.0, 6), round((self.ymin + self.ymax) / 2.0, 6))

    @property
    def area(self) -> float:
        """Returns the normalized area."""
        return (self.xmax - self.xmin) * (self.ymax - self.ymin)

    def intersects(self, other: BoundingBox) -> bool:
        """Checks if this box intersects with another box."""
        return not (
            self.xmax < other.xmin
            or self.xmin > other.xmax
            or self.ymax < other.ymin
            or self.ymin > other.ymax
        )


class DetectedElement(BaseModel):
    """A UI element identified on the screen or viewport."""

    element_id: str = Field(default_factory=lambda: f"elem_{uuid.uuid4().hex[:8]}")
    element_type: UIElementType
    label: str = ""
    bounding_box: BoundingBox
    confidence: float = 1.0
    is_clickable: bool = True
    is_visible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class OCRTextBlock(BaseModel):
    """An extracted text snippet with its location."""

    text: str
    bounding_box: BoundingBox
    confidence: float = 1.0


class VisualObservation(BaseModel):
    """A comprehensive snapshot of a graphical screen or viewport."""

    observation_id: str = Field(default_factory=lambda: f"obs_vis_{uuid.uuid4().hex[:10]}")
    worker_id: str
    task_id: str
    tenant_id: str = "default"
    timestamp: float = Field(default_factory=time.time)
    viewport_width: int = 1920
    viewport_height: int = 1080
    device_pixel_ratio: float = 1.0
    image_ref: str | None = None
    visual_state_hash: str = ""
    detected_elements: list[DetectedElement] = Field(default_factory=list)
    ocr_blocks: list[OCRTextBlock] = Field(default_factory=list)

    def find_element_by_label(self, label: str) -> DetectedElement | None:
        """Find the first element matching a given label (case-insensitive)."""
        label_lower = label.strip().lower()
        for elem in self.detected_elements:
            if elem.label.strip().lower() == label_lower:
                return elem
        return None

    def get_all_text(self) -> str:
        """Return all OCR text joined as a single string."""
        return " ".join(block.text for block in self.ocr_blocks)


class VisualPerceptionEngine:
    """Engine for visual feature extraction, state hashing, and comparison."""

    @staticmethod
    def compute_visual_hash(content: bytes | str) -> str:
        """Compute a deterministic hash representing visual content."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return f"sha256:{hashlib.sha256(content).hexdigest()}"

    @classmethod
    def compare_visual_states(
        cls,
        obs1: VisualObservation,
        obs2: VisualObservation,
        anomaly_types: list[UIElementType] | None = None,
    ) -> dict[str, Any]:
        """Compare two visual observations to detect state transitions or anomalies."""
        if anomaly_types is None:
            anomaly_types = [UIElementType.DIALOG, UIElementType.MODAL]

        hash_identical = obs1.visual_state_hash == obs2.visual_state_hash and bool(
            obs1.visual_state_hash
        )

        # Check detected element differences
        elems1_by_id = {e.element_id: e for e in obs1.detected_elements}
        elems2_by_id = {e.element_id: e for e in obs2.detected_elements}

        added_ids = set(elems2_by_id.keys()) - set(elems1_by_id.keys())
        removed_ids = set(elems1_by_id.keys()) - set(elems2_by_id.keys())

        # Check for newly appeared anomalies (e.g. popup modal or error dialog)
        anomalies_detected: list[DetectedElement] = []
        for new_id in added_ids:
            elem = elems2_by_id[new_id]
            if elem.element_type in anomaly_types:
                anomalies_detected.append(elem)

        # Compute a simple element-based similarity score
        total_unique = len(set(elems1_by_id.keys()).union(set(elems2_by_id.keys())))
        intersection = len(set(elems1_by_id.keys()).intersection(set(elems2_by_id.keys())))
        similarity = 1.0 if total_unique == 0 else (intersection / total_unique)

        return {
            "identical": hash_identical,
            "similarity_score": 1.0 if hash_identical else similarity,
            "elements_added": [elems2_by_id[i] for i in added_ids],
            "elements_removed": [elems1_by_id[i] for i in removed_ids],
            "anomalies_detected": anomalies_detected,
            "has_anomaly": len(anomalies_detected) > 0,
        }

    @classmethod
    def extract_roi(
        cls,
        observation: VisualObservation,
        roi_box: BoundingBox,
    ) -> list[DetectedElement]:
        """Extract all detected elements intersecting with the Region of Interest."""
        return [
            elem for elem in observation.detected_elements if elem.bounding_box.intersects(roi_box)
        ]

"""ATLAS Visual Grounding and Coordinate Transformation Engine.

Handles conversion between Normalized, Viewport, Screen, and Multi-Monitor spaces,
along with DPR scaling, browser zoom adjustments, and stale coordinate rejection.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel

from atlas_multimodal.visual import BoundingBox, VisualObservation


class CoordinateSpace(StrEnum):
    """Supported coordinate spaces in ATLAS."""

    NORMALIZED = "NORMALIZED"
    VIEWPORT = "VIEWPORT"
    SCREEN = "SCREEN"


class GroundingError(Exception):
    """Base exception for coordinate grounding operations."""


class StaleObservationError(GroundingError):
    """Raised when an action is attempted on an observation exceeding the freshness threshold."""


class OutOfBoundsCoordinateError(GroundingError):
    """Raised when a coordinate falls outside the viewport or screen boundaries."""


class ScreenGeometry(BaseModel):
    """Physical and logical display geometry for screen grounding."""

    monitor_id: str = "primary"
    origin_x: int = 0
    origin_y: int = 0
    width_px: int = 1920
    height_px: int = 1080
    device_pixel_ratio: float = 1.0
    zoom_factor: float = 1.0
    window_offset_x: int = 0
    window_offset_y: int = 0


class VisualGroundingTransformer:
    """Transforms coordinates across Normalized, Viewport, and Physical Screen spaces."""

    @staticmethod
    def normalized_to_viewport(
        box: BoundingBox,
        viewport_w: int,
        viewport_h: int,
        zoom_factor: float = 1.0,
    ) -> tuple[float, float]:
        """Convert a normalized bounding box to viewport center coordinates (x_vp, y_vp)."""
        x_norm, y_norm = box.center_point
        # Viewport coordinates scale with viewport dimensions and zoom factor
        x_vp = round(x_norm * viewport_w * zoom_factor, 6)
        y_vp = round(y_norm * viewport_h * zoom_factor, 6)
        return (x_vp, y_vp)

    @staticmethod
    def viewport_to_screen(
        x_vp: float,
        y_vp: float,
        geometry: ScreenGeometry,
    ) -> tuple[int, int]:
        """Convert viewport coordinates to physical screen coordinates."""
        # Scale by DPR, add window chrome offset, and add monitor canvas origin
        phys_x = (x_vp * geometry.device_pixel_ratio) + geometry.window_offset_x + geometry.origin_x
        phys_y = (y_vp * geometry.device_pixel_ratio) + geometry.window_offset_y + geometry.origin_y
        return (round(phys_x), round(phys_y))

    @classmethod
    def normalized_to_screen(
        cls,
        box: BoundingBox,
        geometry: ScreenGeometry,
        viewport_w: int,
        viewport_h: int,
    ) -> tuple[int, int]:
        """Direct transformation from normalized bounding box to physical screen pixel coordinates."""
        x_vp, y_vp = cls.normalized_to_viewport(
            box=box,
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            zoom_factor=geometry.zoom_factor,
        )
        return cls.viewport_to_screen(x_vp=x_vp, y_vp=y_vp, geometry=geometry)


class StaleCoordinateGuard:
    """Enforces freshness and boundary invariants on visually-grounded actions."""

    def __init__(self, max_age_seconds: float = 5.0) -> None:
        self.max_age_seconds = max_age_seconds

    def validate_bounds(self, target_box: BoundingBox) -> None:
        """Validate that bounding box coordinates fall within [0.0, 1.0]."""
        if not (0.0 <= target_box.xmin <= 1.0 and 0.0 <= target_box.xmax <= 1.0):
            raise OutOfBoundsCoordinateError(
                f"X coordinates ({target_box.xmin}, {target_box.xmax}) out of [0, 1] viewport bounds"
            )
        if not (0.0 <= target_box.ymin <= 1.0 and 0.0 <= target_box.ymax <= 1.0):
            raise OutOfBoundsCoordinateError(
                f"Y coordinates ({target_box.ymin}, {target_box.ymax}) out of [0, 1] viewport bounds"
            )

    def validate(
        self,
        observation: VisualObservation,
        target_box: BoundingBox | None = None,
        current_time: float | None = None,
    ) -> None:
        """Validate that observation is fresh and target is within viewport bounds."""
        now = time.time() if current_time is None else current_time
        age = now - observation.timestamp

        if age > self.max_age_seconds:
            raise StaleObservationError(
                f"Visual observation is stale (age={age:.2f}s > threshold={self.max_age_seconds}s). "
                "Fresh visual capture required before action execution."
            )

        if target_box is not None:
            # Check bounds within [0.0, 1.0]
            if not (0.0 <= target_box.xmin <= 1.0 and 0.0 <= target_box.xmax <= 1.0):
                raise OutOfBoundsCoordinateError(
                    f"X coordinates ({target_box.xmin}, {target_box.xmax}) out of [0, 1] viewport bounds"
                )
            if not (0.0 <= target_box.ymin <= 1.0 and 0.0 <= target_box.ymax <= 1.0):
                raise OutOfBoundsCoordinateError(
                    f"Y coordinates ({target_box.ymin}, {target_box.ymax}) out of [0, 1] viewport bounds"
                )

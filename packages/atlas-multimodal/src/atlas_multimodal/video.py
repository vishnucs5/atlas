"""ATLAS Video Understanding Engine.

Provides temporal frame sampling, scene segmentation, keyframe extraction,
and timestamp-preserved event summarization.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from pydantic import BaseModel, Field


class VideoFrame(BaseModel):
    """An individual sampled video frame."""

    frame_index: int
    timestamp_offset_sec: float
    image_ref: str
    visual_hash: str
    is_keyframe: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TemporalEvent(BaseModel):
    """A semantic event occurring over a time interval in a video."""

    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    start_time_sec: float
    end_time_sec: float
    label: str
    description: str
    confidence: float = 1.0


class VideoObservation(BaseModel):
    """Structured perception output representing an analyzed video stream."""

    video_id: str = Field(default_factory=lambda: f"vid_{uuid.uuid4().hex[:10]}")
    duration_seconds: float
    fps: float = 1.0
    total_frames_sampled: int
    keyframes: list[VideoFrame] = Field(default_factory=list)
    events: list[TemporalEvent] = Field(default_factory=list)

    def get_events_at_time(self, timestamp_sec: float) -> list[TemporalEvent]:
        """Return all events active at the specified timestamp."""
        return [e for e in self.events if e.start_time_sec <= timestamp_sec <= e.end_time_sec]


class VideoUnderstandingEngine:
    """Engine for sampling, scene detection, and temporal event summarization."""

    @classmethod
    def sample_frames(
        cls,
        video_id: str,
        duration_sec: float,
        fps_target: float = 1.0,
        max_frames: int = 60,
    ) -> list[VideoFrame]:
        """Sample video frames across duration at target fps, clamped by max_frames."""
        if duration_sec <= 0:
            raise ValueError("Video duration must be greater than zero.")

        # Determine step size in seconds
        interval_sec = 1.0 / max(fps_target, 0.01)
        total_possible = int(duration_sec / interval_sec) + 1
        num_frames = min(total_possible, max_frames)

        frames: list[VideoFrame] = []
        for i in range(num_frames):
            ts = min(round(i * interval_sec, 3), duration_sec)
            content_token = f"{video_id}:{i}:{ts}".encode()
            h = f"sha256:{hashlib.sha256(content_token).hexdigest()}"
            frames.append(
                VideoFrame(
                    frame_index=i,
                    timestamp_offset_sec=ts,
                    image_ref=f"artifacts/{video_id}/frames/frame_{i:04d}.png",
                    visual_hash=h,
                    is_keyframe=(i == 0),
                )
            )
        return frames

    @classmethod
    def detect_scene_boundaries(
        cls,
        frames: list[VideoFrame],
        simulated_transitions: list[int] | None = None,
    ) -> list[VideoFrame]:
        """Detect scene transitions and mark corresponding frames as keyframes."""
        transitions = set(simulated_transitions or [])
        transitions.add(0)  # First frame is always a keyframe

        for frame in frames:
            if frame.frame_index in transitions:
                frame.is_keyframe = True

        return [f for f in frames if f.is_keyframe]

    @classmethod
    def summarize_temporal_events(
        cls,
        video_id: str,
        duration_sec: float,
        frames: list[VideoFrame],
        events: list[TemporalEvent],
    ) -> VideoObservation:
        """Construct full video observation with keyframes and temporal events."""
        keyframes = [f for f in frames if f.is_keyframe]
        if not keyframes and frames:
            frames[0].is_keyframe = True
            keyframes = [frames[0]]

        return VideoObservation(
            video_id=video_id,
            duration_seconds=duration_sec,
            fps=round(len(frames) / max(duration_sec, 0.01), 2),
            total_frames_sampled=len(frames),
            keyframes=keyframes,
            events=events,
        )

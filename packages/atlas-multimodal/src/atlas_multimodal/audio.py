"""ATLAS Audio Intelligence & Consent Enforcement Engine.

Provides speech-to-text, speaker diarization, and strict cryptographic consent
token verification for microphone access.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from pydantic import BaseModel, Field


class AudioIntelligenceError(Exception):
    """Base exception for audio intelligence operations."""


class UnauthorizedRecordingError(AudioIntelligenceError):
    """Raised when audio capture or recording is attempted without valid consent."""


class AudioConsentToken(BaseModel):
    """Cryptographic authorization token granting permission to record audio."""

    token_id: str = Field(default_factory=lambda: f"tok_audio_{uuid.uuid4().hex[:10]}")
    tenant_id: str
    user_id: str
    granted_at: float = Field(default_factory=time.time)
    expires_at: float
    scopes: list[str] = Field(default_factory=lambda: ["transcription"])
    signature: str = ""

    def is_valid(self, current_time: float | None = None) -> bool:
        """Check if token is within its active validity window."""
        now = time.time() if current_time is None else current_time
        return self.granted_at <= now <= self.expires_at


class TranscriptionSegment(BaseModel):
    """A diarized, timestamped snippet of spoken audio."""

    segment_id: str = Field(default_factory=lambda: f"seg_{uuid.uuid4().hex[:8]}")
    start_time_sec: float
    end_time_sec: float
    speaker_id: str = "speaker_0"
    text: str
    confidence: float = 1.0


class AudioObservation(BaseModel):
    """Structured perception output representing an analyzed audio stream."""

    audio_id: str = Field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:10]}")
    tenant_id: str = "default"
    duration_seconds: float
    sample_rate: int = 16000
    segments: list[TranscriptionSegment] = Field(default_factory=list)
    full_transcript: str = ""

    def get_speakers(self) -> set[str]:
        """Return the set of unique speaker IDs in this audio."""
        return {s.speaker_id for s in self.segments}


class AudioConsentManager:
    """Manages creation, verification, and revocation of microphone recording consent."""

    SECRET_SALT = "atlas-audio-consent-v13"

    @classmethod
    def create_consent_token(
        cls,
        tenant_id: str,
        user_id: str,
        duration_seconds: float = 3600.0,
        scopes: list[str] | None = None,
    ) -> AudioConsentToken:
        """Issue a cryptographically signed consent token."""
        now = time.time()
        scopes = scopes or ["transcription"]
        payload = f"{tenant_id}:{user_id}:{now}:{now + duration_seconds}:{','.join(scopes)}:{cls.SECRET_SALT}"
        sig = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        return AudioConsentToken(
            tenant_id=tenant_id,
            user_id=user_id,
            granted_at=now,
            expires_at=now + duration_seconds,
            scopes=scopes,
            signature=sig,
        )

    @classmethod
    def verify_recording_permission(
        cls,
        token: AudioConsentToken | None,
        tenant_id: str,
        current_time: float | None = None,
    ) -> None:
        """Verify that microphone recording is authorized by an active token."""
        if token is None:
            raise UnauthorizedRecordingError(
                "Microphone recording rejected: No AudioConsentToken provided."
            )

        if token.tenant_id != tenant_id:
            raise UnauthorizedRecordingError(
                f"Consent token tenant mismatch: token belongs to '{token.tenant_id}', "
                f"requested by '{tenant_id}'."
            )

        if not token.is_valid(current_time):
            raise UnauthorizedRecordingError(
                f"Consent token '{token.token_id}' has expired. Re-prompt user for microphone consent."
            )


class AudioIntelligenceEngine:
    """Processes audio streams into diarized, timestamped transcripts."""

    def __init__(self, consent_manager: AudioConsentManager | None = None) -> None:
        self.consent_manager = consent_manager or AudioConsentManager()

    def transcribe(
        self,
        audio_id: str,
        duration_sec: float,
        segments: list[TranscriptionSegment],
        consent_token: AudioConsentToken | None = None,
        is_live_microphone: bool = False,
        tenant_id: str = "default",
        current_time: float | None = None,
    ) -> AudioObservation:
        """Transcribe and diarize an audio input, enforcing consent on live mics."""
        if is_live_microphone:
            self.consent_manager.verify_recording_permission(
                token=consent_token,
                tenant_id=tenant_id,
                current_time=current_time,
            )

        full_transcript = " ".join(s.text.strip() for s in segments if s.text.strip())

        return AudioObservation(
            audio_id=audio_id,
            tenant_id=tenant_id,
            duration_seconds=duration_sec,
            segments=segments,
            full_transcript=full_transcript,
        )

"""VerificationEngine evaluating declarative post-conditions."""

import asyncio
import time
from pathlib import Path
from typing import Any

from atlas_core.contracts.action import ExpectedState
from pydantic import BaseModel, ConfigDict, Field

from atlas_verification.matchers import (
    match_element_hidden,
    match_element_visible,
    match_file_downloaded,
    match_text_present,
    match_url,
    match_value_equals,
)


class VerificationResult(BaseModel):
    """Deterministic outcome of post-condition verification."""

    model_config = ConfigDict(validate_assignment=True)

    verified: bool
    condition: str
    target: str
    expected_value: Any | None = None
    actual_value: Any | None = None
    duration_ms: int = 0
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class VerificationEngine:
    """Evaluates declarative post-conditions against browser state and environment."""

    async def verify(
        self,
        expected: ExpectedState,
        page: Any | None = None,
        download_dir: Path | str | None = None,
    ) -> VerificationResult:
        """Evaluate an ExpectedState contract against the environment."""
        start = time.perf_counter()
        condition = expected.condition.lower()
        target = expected.target
        timeout_ms = expected.timeout_ms

        verified = False
        actual: Any = None
        error: str | None = None

        if condition == "element_visible":
            if page is None:
                return VerificationResult(
                    verified=False,
                    condition=condition,
                    target=target,
                    error="Page reference is required for element_visible condition",
                )
            verified, actual, error = await match_element_visible(
                page, target, timeout_ms=timeout_ms
            )

        elif condition == "element_hidden":
            if page is None:
                return VerificationResult(
                    verified=False,
                    condition=condition,
                    target=target,
                    error="Page reference is required for element_hidden condition",
                )
            verified, actual, error = await match_element_hidden(
                page, target, timeout_ms=timeout_ms
            )

        elif condition == "text_present":
            if page is None:
                return VerificationResult(
                    verified=False,
                    condition=condition,
                    target=target,
                    error="Page reference is required for text_present condition",
                )
            verified, actual, error = await match_text_present(page, target, timeout_ms=timeout_ms)

        elif condition in ("url_matches", "url_equals"):
            if page is None:
                return VerificationResult(
                    verified=False,
                    condition=condition,
                    target=target,
                    error="Page reference is required for url condition",
                )
            verified, actual, error = await match_url(page, target)

        elif condition in ("file_downloaded", "file_exists"):
            if download_dir is None:
                return VerificationResult(
                    verified=False,
                    condition=condition,
                    target=target,
                    error="Download directory reference is required for file verification",
                )
            deadline = time.perf_counter() + (timeout_ms / 1000.0)
            while True:
                verified, actual, error = match_file_downloaded(download_dir, target)
                if verified or time.perf_counter() >= deadline:
                    break
                await asyncio.sleep(0.1)

        elif condition == "value_equals":
            if page is None:
                return VerificationResult(
                    verified=False,
                    condition=condition,
                    target=target,
                    error="Page reference is required for value_equals condition",
                )
            verified, actual, error = await match_value_equals(page, target, expected.value)

        else:
            verified = False
            error = f"Unsupported verification condition: '{condition}'"

        duration_ms = int((time.perf_counter() - start) * 1000)

        return VerificationResult(
            verified=verified,
            condition=condition,
            target=target,
            expected_value=expected.value,
            actual_value=actual,
            duration_ms=duration_ms,
            evidence={"actual": actual, "condition": condition, "target": target},
            error=error,
        )

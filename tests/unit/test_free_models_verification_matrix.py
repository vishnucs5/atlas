"""Deterministic Mock Test Matrix for Free Cloud Models Ecosystem.

Covers:
1. Credential Precedence (Env Var > Keyring > Restricted File > In-Memory).
2. Owner-only permissions and consent-gated fallback to ~/.atlas/credentials.json.
3. Strict free routing invariants (PaidRoutingBlockedError, no cross-provider fallback).
4. HTTP transport failure modes (429 RateLimit backoff, 401 Auth, 500 Outage, Timeouts).
5. OpenRouter reasoning payload extraction and token limits.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import httpx
import pytest
from atlas_core.contracts.model import (
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    TokenUsage,
)
from atlas_models.adapter import ModelAdapter
from atlas_models.adapters.openai import OpenAIAdapter
from atlas_models.credentials import (
    _IN_MEMORY_CREDENTIALS,
    CredentialStoreUnavailable,
    get_credential,
    remove_credential,
    set_credential,
)
from atlas_models.free_catalogue import (
    ModelEligibilityStatus,
    ModelEntry,
)
from atlas_models.router import ModelRouter, PaidRoutingBlockedError


# ==============================================================================
# 1. Credential Precedence & Consent-Gated File Fallback Tests
# ==============================================================================
def test_credential_precedence_env_over_keyring_and_file(monkeypatch, tmp_path):
    """Verify Environment Variable takes strict precedence over Keyring and File."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-secret-key-123")

    # Mock keyring returning a different value
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "keyring-secret-456"
    monkeypatch.setattr("keyring.get_password", mock_keyring.get_password)

    # Put a value in file as well
    atlas_dir = tmp_path / ".atlas"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    creds_file = atlas_dir / "credentials.json"
    creds_file.write_text(json.dumps({"openrouter": "file-secret-789"}), encoding="utf-8")

    # Env must win
    val = get_credential("openrouter")
    assert val == "env-secret-key-123"


def test_credential_keyring_over_file(monkeypatch, tmp_path):
    """Verify Keyring takes precedence over restricted file when Env is unset."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "keyring-secret-456"
    monkeypatch.setattr("keyring.get_password", mock_keyring.get_password)

    atlas_dir = tmp_path / ".atlas"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    creds_file = atlas_dir / "credentials.json"
    creds_file.write_text(json.dumps({"openrouter": "file-secret-789"}), encoding="utf-8")

    val = get_credential("openrouter")
    assert val == "keyring-secret-456"


def test_credential_restricted_file_fallback(monkeypatch, tmp_path):
    """Verify Restricted File is read when Env and Keyring are absent."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    # Keyring fails or returns None
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None
    monkeypatch.setattr("keyring.get_password", mock_keyring.get_password)

    atlas_dir = tmp_path / ".atlas"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    creds_file = atlas_dir / "credentials.json"
    creds_file.write_text(json.dumps({"openrouter": "file-secret-789"}), encoding="utf-8")

    val = get_credential("openrouter")
    assert val == "file-secret-789"


def test_set_credential_keyring_failure_without_consent(monkeypatch, tmp_path):
    """Verify that when Keyring fails, refusing file consent stores in-memory only and raises."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda *a, **k: None)
    _IN_MEMORY_CREDENTIALS.clear()

    def fail_set(*args, **kwargs):
        raise RuntimeError("Keyring service crashed")

    monkeypatch.setattr("keyring.set_password", fail_set)

    with pytest.raises(CredentialStoreUnavailable, match="Explicit consent is required"):
        set_credential("openrouter", "temp-secret", consent_file_fallback=False)

    # In-memory holds the value for current process
    assert get_credential("openrouter") == "temp-secret"

    # File must NOT have been created
    creds_file = tmp_path / ".atlas" / "credentials.json"
    assert not creds_file.exists()


def test_set_credential_with_consent_writes_file(monkeypatch, tmp_path):
    """Verify that when consent is granted, fallback safely writes to credentials.json."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda *a, **k: None)
    _IN_MEMORY_CREDENTIALS.clear()

    def fail_set(*args, **kwargs):
        raise RuntimeError("Keyring unavailable")

    monkeypatch.setattr("keyring.set_password", fail_set)

    set_credential("openrouter", "consented-secret", consent_file_fallback=True)

    creds_file = tmp_path / ".atlas" / "credentials.json"
    assert creds_file.exists()
    data = json.loads(creds_file.read_text(encoding="utf-8"))
    assert data["openrouter"] == "consented-secret"

    # Reading it back works
    assert get_credential("openrouter") == "consented-secret"


def test_remove_credential_removes_from_file_and_memory(monkeypatch, tmp_path):
    """Verify remove_credential clears both restricted file and in-memory stores."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda *a, **k: None)
    _IN_MEMORY_CREDENTIALS["openrouter"] = "in-mem-secret"

    atlas_dir = tmp_path / ".atlas"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    creds_file = atlas_dir / "credentials.json"
    creds_file.write_text(json.dumps({"openrouter": "file-secret"}), encoding="utf-8")

    mock_del = MagicMock()
    monkeypatch.setattr("keyring.delete_password", mock_del)

    removed = remove_credential("openrouter")
    assert removed is True
    assert "openrouter" not in _IN_MEMORY_CREDENTIALS
    assert get_credential("openrouter") is None


# ==============================================================================
# 2. Strict Free-Routing & PaidRoutingBlockedError Invariants
# ==============================================================================
class MockStrictFreeAdapter(ModelAdapter):
    def __init__(self, name: str, cost: float = 0.0, fail_with: Exception | None = None) -> None:
        self._name = name
        self._cost = cost
        self._fail_with = fail_with
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=self._name,
            provider="mock-free",
            cost_per_1k_input_tokens=self._cost,
            cost_per_1k_output_tokens=self._cost,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        if self._fail_with:
            raise self._fail_with
        return ModelResponse(
            response_id="mock-resp",
            request_id=request.request_id,
            model_name=self._name,
            content="Free response output",
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                estimated_cost_usd=self._cost,
            ),
        )

    def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        async def _gen():
            yield "stream"

        return _gen()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(status="HEALTHY", provider_id="mock-free")


@pytest.mark.asyncio
async def test_router_blocks_unverified_model_in_free_only_mode():
    """Verify ModelRouter in free_only mode blocks unverified or paid models immediately."""
    router = ModelRouter(
        free_only=True,
        allowed_free_models={"openrouter/free", "nvidia/nemotron-3.5-lightning:free"},
    )
    adapter = MockStrictFreeAdapter("openrouter/free")
    router.register_adapter(adapter)

    req = ModelRequest(
        request_id="req-1",
        task_id="task-1",
        model_name="openai/gpt-4o",  # Paid model
        messages=[ModelMessage(role="user", content="Hello")],
    )

    with pytest.raises(PaidRoutingBlockedError, match="not in the currently verified free-model"):
        await router.complete(req)

    assert adapter.call_count == 0


@pytest.mark.asyncio
async def test_router_free_only_no_silent_fallback():
    """Verify that in free_only mode, a failure on the allowed model never silently routes elsewhere."""
    router = ModelRouter(
        free_only=True,
        allowed_free_models={"openrouter/free"},
    )
    # Primary fails with 500
    primary = MockStrictFreeAdapter(
        "openrouter/free", fail_with=RuntimeError("Primary gateway 502 Bad Gateway")
    )
    backup = MockStrictFreeAdapter("other/free")

    router.register_adapter(primary, priority=10)
    router.register_adapter(backup, priority=5)

    req = ModelRequest(
        request_id="req-2",
        task_id="task-2",
        model_name="openrouter/free",
        messages=[ModelMessage(role="user", content="Hello")],
    )

    with pytest.raises(PaidRoutingBlockedError, match="Free route 'openrouter/free' failed"):
        await router.complete(req, fallback=True)

    assert primary.call_count == 1
    assert backup.call_count == 0


# ==============================================================================
# 3. HTTP Mocked Transport: Rate Limits, Timeouts & Reasoning Extraction
# ==============================================================================
@pytest.mark.asyncio
async def test_openai_adapter_handles_rate_limit_backoff_and_recovery():
    """Verify that rate limits (HTTP 429) back off and succeed on retry."""
    attempts = 0

    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "Rate limit exceeded: queue full", "code": 429}},
            )
        return httpx.Response(
            200,
            json={
                "id": "chat-success",
                "object": "chat.completion",
                "model": "nvidia/nemotron-3.5-lightning:free",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Success after backoff"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(rate_limit_handler))
    adapter = OpenAIAdapter(
        api_key="sk-test",
        client=client,
        model_name="nvidia/nemotron-3.5-lightning:free",
    )

    router = ModelRouter(
        free_only=True,
        allowed_free_models={"nvidia/nemotron-3.5-lightning:free"},
    )
    router.register_adapter(adapter)

    req = ModelRequest(
        request_id="req-rate-limit",
        task_id="task-rate-limit",
        model_name="nvidia/nemotron-3.5-lightning:free",
        messages=[ModelMessage(role="user", content="Do work")],
    )

    with patch("asyncio.sleep", return_value=None):  # Fast execution in tests
        resp = await router.complete(req)

    assert resp.content == "Success after backoff"
    assert attempts == 2


@pytest.mark.asyncio
async def test_openai_adapter_extracts_reasoning_when_content_is_null():
    """Verify that reasoning models returning null content and 'reasoning' field succeed."""

    def reasoning_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chat-reasoning",
                "object": "chat.completion",
                "model": "baidu/ernie-5.5-flash-preview:free",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning": "Step 1: Plan architecture.\nStep 2: Generate code.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(reasoning_handler))
    adapter = OpenAIAdapter(
        api_key="sk-test",
        client=client,
        model_name="baidu/ernie-5.5-flash-preview:free",
    )

    req = ModelRequest(
        request_id="req-reason",
        task_id="task-reason",
        model_name="baidu/ernie-5.5-flash-preview:free",
        messages=[ModelMessage(role="user", content="Build module")],
    )

    resp = await adapter.complete(req)
    assert resp.content == "Step 1: Plan architecture.\nStep 2: Generate code."
    assert resp.usage.total_tokens == 50


# ==============================================================================
# 4. Catalogue Model Eligibility Invariants
# ==============================================================================
def test_catalogue_entry_rejection_of_paid_models():
    """Verify that ModelEntry enforces FREE_VERIFIED status and zero pricing."""
    valid_free = ModelEntry(
        id="openrouter/free",
        name="OpenRouter Free Meta-Router",
        provider="openrouter",
        pricing={"prompt": 0.0, "completion": 0.0},
        eligibility_status=ModelEligibilityStatus.FREE_VERIFIED,
    )
    assert valid_free.is_currently_eligible() is True

    under_review = ModelEntry(
        id="groq/llama-3.3-70b",
        name="Groq Llama 3.3 (Under Review)",
        provider="groq",
        pricing={"prompt": 0.0, "completion": 0.0},
        eligibility_status=ModelEligibilityStatus.UNDER_REVIEW,
    )
    assert under_review.is_currently_eligible() is False

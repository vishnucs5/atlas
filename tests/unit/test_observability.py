import asyncio
import io
import json
import logging

import pytest
from atlas_observability.logging import (
    bind_context,
    clear_context,
    context_scope,
    get_context,
    get_logger,
    mask_data,
    mask_secrets,
    unbind_context,
)


@pytest.fixture(autouse=True)
def reset_logging_context():
    """Ensure logging context is cleared before and after each test."""
    clear_context()
    yield
    clear_context()


def test_mask_secrets():
    """Baseline test from specification: verify secret redaction in string text."""
    raw = "My API key is sk-proj-1234567890abcdef12345 and password=supersecret"
    masked = mask_secrets(raw)
    assert "sk-proj-1234567890abcdef12345" not in masked
    assert "supersecret" not in masked
    assert "[REDACTED]" in masked


def test_structured_json_logging():
    """Baseline test from specification: verify structured JSON output and context binding."""
    stream = io.StringIO()
    logger = get_logger("atlas.test", stream=stream)
    bind_context(task_id="task_999", correlation_id="corr_888")
    logger.info("Task execution step started", action="browser.click")
    output = stream.getvalue()
    record = json.loads(output)
    assert record["message"] == "Task execution step started"
    assert record["task_id"] == "task_999"
    assert record["correlation_id"] == "corr_888"
    assert record["action"] == "browser.click"
    assert "timestamp" in record
    assert record["level"] == "INFO"
    assert record["logger"] == "atlas.test"


def test_mask_secrets_various_provider_keys():
    """Verify redacting OpenAI, Anthropic, Gemini, AWS, GitHub keys."""
    keys_text = (
        "OpenAI: sk-proj-abcdef12345678901234567890\n"
        "Anthropic: sk-ant-api03-abcdef123456789012345678901234567890\n"
        "Gemini: AIzaSyD9ABCDEF1234567890123456789012345\n"
        "AWS: AKIAIOSFODNN7EXAMPLE\n"
        "GitHub: ghp_1234567890abcdef1234567890abcdef123456"
    )
    masked = mask_secrets(keys_text)
    assert "sk-proj-abcdef12345678901234567890" not in masked
    assert "sk-ant-api03-abcdef123456789012345678901234567890" not in masked
    assert "AIzaSyD9ABCDEF1234567890123456789012345" not in masked
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert "ghp_1234567890abcdef1234567890abcdef123456" not in masked


def test_mask_secrets_bearer_and_key_value_pairs():
    """Verify redacting Bearer tokens and sensitive key-value pairs."""
    text = (
        "Authorization: Bearer my_super_secret_access_token_123456\n"
        '{"api_key": "secret_api_key_value_9999", "password": "pass_12345", "token": "tok_xyz888"}\n'
        "url: https://api.atlas.dev/v1/run?secret_key=topsecretkey123&client_secret=clientsecret456"
    )
    masked = mask_secrets(text)
    assert "my_super_secret_access_token_123456" not in masked
    assert "secret_api_key_value_9999" not in masked
    assert "pass_12345" not in masked
    assert "tok_xyz888" not in masked
    assert "topsecretkey123" not in masked
    assert "clientsecret456" not in masked


def test_mask_secrets_jwt_and_pem_private_keys():
    """Verify redacting JWT tokens and PEM private keys."""
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y1234567890abcdef\n"
        "-----END RSA PRIVATE KEY-----"
    )
    raw = f"Token is {jwt} and Key is {pem}"
    masked = mask_secrets(raw)
    assert jwt not in masked
    assert "MIIEowIBAAKCAQEA0Y1234567890abcdef" not in masked


def test_mask_secrets_leaves_benign_text_intact():
    """Verify non-sensitive text is not modified."""
    plain = "Executing step browser.click on selector #submit-btn with timeout 5000ms"
    assert mask_secrets(plain) == plain


def test_mask_data_nested_structures():
    """Verify mask_data recursively redacts dicts, lists, and primitives."""
    payload = {
        "user": "alice",
        "password": "plain_password_123",
        "api_key": "sk-proj-99999999999999999999",
        "metadata": {
            "token": "tok_nested_12345",
            "items": ["safe_item", "secret password=innersecret in string"],
        },
        "count": 42,
    }
    cleaned = mask_data(payload)
    assert cleaned["user"] == "alice"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["metadata"]["token"] == "[REDACTED]"
    assert cleaned["metadata"]["items"][0] == "safe_item"
    assert "innersecret" not in cleaned["metadata"]["items"][1]
    assert cleaned["count"] == 42


def test_context_binding_and_unbinding():
    """Verify bind_context, get_context, unbind_context, and clear_context."""
    assert get_context() == {}
    bind_context(session_id="sess_1", task_id="task_1")
    assert get_context() == {"session_id": "sess_1", "task_id": "task_1"}

    bind_context(correlation_id="corr_1")
    assert get_context() == {
        "session_id": "sess_1",
        "task_id": "task_1",
        "correlation_id": "corr_1",
    }

    unbind_context("session_id")
    assert get_context() == {"task_id": "task_1", "correlation_id": "corr_1"}

    clear_context()
    assert get_context() == {}


def test_context_scope_manager():
    """Verify context_scope sets temporary context and restores previous on exit."""
    bind_context(task_id="task_base")
    assert get_context() == {"task_id": "task_base"}

    with context_scope(task_id="task_scoped", step_id="step_1"):
        assert get_context() == {"task_id": "task_scoped", "step_id": "step_1"}

    assert get_context() == {"task_id": "task_base"}


def test_structured_logging_levels_and_formatting():
    """Verify logging at debug, info, warning, error, critical levels."""
    stream = io.StringIO()
    logger = get_logger("atlas.levels", stream=stream, level=logging.DEBUG)

    logger.debug("Debug message", step=1)
    logger.info("Info message", step=2)
    logger.warning("Warning message", step=3)
    logger.error("Error message", step=4)
    logger.critical("Critical message", step=5)

    lines = [json.loads(line) for line in stream.getvalue().strip().split("\n") if line]
    assert len(lines) == 5
    assert [entry["level"] for entry in lines] == [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]
    assert [entry["message"] for entry in lines] == [
        "Debug message",
        "Info message",
        "Warning message",
        "Error message",
        "Critical message",
    ]
    assert [entry["step"] for entry in lines] == [1, 2, 3, 4, 5]


def test_structured_logging_secret_masking_in_logs():
    """Constitution Rule 6: Verify secrets in log message and kwargs are redacted."""
    stream = io.StringIO()
    logger = get_logger("atlas.secure", stream=stream)

    logger.info(
        "Request failed for sk-proj-1234567890abcdef12345",
        password="supersecret_password",
        token="sk-ant-1234567890abcdef1234567890",
        safe_param="value_ok",
    )

    output = stream.getvalue()
    assert "sk-proj-1234567890abcdef12345" not in output
    assert "supersecret_password" not in output
    assert "sk-ant-1234567890abcdef1234567890" not in output
    assert "value_ok" in output

    record = json.loads(output)
    assert "[REDACTED]" in record["message"]
    assert record["password"] == "[REDACTED]"
    assert record["safe_param"] == "value_ok"


def test_structured_logging_exception_capture():
    """Verify logger.exception serializes traceback with secrets redacted."""
    stream = io.StringIO()
    logger = get_logger("atlas.error", stream=stream)

    try:
        raise ValueError("Invalid credentials with key sk-proj-1234567890abcdef12345")
    except ValueError:
        logger.exception("Failed to connect to provider")

    output = stream.getvalue()
    assert "sk-proj-1234567890abcdef12345" not in output
    record = json.loads(output)
    assert record["level"] == "ERROR"
    assert record["message"] == "Failed to connect to provider"
    assert "exception" in record
    assert "ValueError" in record["exception"]
    assert "[REDACTED]" in record["exception"]


def test_structured_logger_instance_bind():
    """Verify logger.bind returns a new StructuredLogger instance with permanent bound attrs."""
    stream = io.StringIO()
    logger = get_logger("atlas.bound", stream=stream)
    worker_logger = logger.bind(worker_id="worker_42", role="executor")

    worker_logger.info("Worker started")
    record = json.loads(stream.getvalue().strip())
    assert record["worker_id"] == "worker_42"
    assert record["role"] == "executor"
    assert record["message"] == "Worker started"


@pytest.mark.asyncio
async def test_contextvars_async_isolation():
    """Verify context is isolated between asynchronous tasks."""
    results = {}

    async def task_worker(worker_id: str, task_id: str):
        bind_context(worker_id=worker_id, task_id=task_id)
        await asyncio.sleep(0.01)
        results[worker_id] = get_context()

    await asyncio.gather(
        task_worker("w1", "task_aaa"),
        task_worker("w2", "task_bbb"),
    )

    assert results["w1"]["task_id"] == "task_aaa"
    assert results["w1"]["worker_id"] == "w1"
    assert results["w2"]["task_id"] == "task_bbb"
    assert results["w2"]["worker_id"] == "w2"

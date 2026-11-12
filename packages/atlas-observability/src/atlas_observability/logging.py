"""Context-bound structured JSON logging and high-performance secret redaction.

Ensures adherence to ATLAS Constitution Rule 6: No Secret Leaks.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import sys
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import IO, Any

# ---------------------------------------------------------------------------
# Secret Redaction Engine
# ---------------------------------------------------------------------------

# Sensitive normalized key names that trigger redaction in dict structures
_SENSITIVE_KEY_NAMES_NORM: set[str] = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "apikey",
    "secretkey",
    "accesstoken",
    "authtoken",
    "refreshtoken",
    "sessiontoken",
    "csrftoken",
    "apitoken",
    "idtoken",
    "token",
    "privatekey",
    "clientsecret",
    "clienttoken",
    "accesskey",
    "secretaccesskey",
    "awssecretaccesskey",
    "bearer",
    "basic",
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
}

_SENSITIVE_SUFFIXES: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "apikey",
    "secretkey",
    "accesskey",
    "secretaccesskey",
)

# Token metric / count keys that should never be redacted as secrets
_TOKEN_METRIC_NAMES: frozenset[str] = frozenset(
    {
        "prompttokens",
        "completiontokens",
        "totaltokens",
        "inputtokens",
        "outputtokens",
        "usagetokens",
        "maxtokens",
        "numtokens",
        "tokens",
    }
)


def is_sensitive_key(key: str) -> bool:
    """Determine if a key name suggests sensitive content."""
    norm = re.sub(r"[-_]", "", str(key).lower())
    if norm in _TOKEN_METRIC_NAMES:
        return False
    if norm in _SENSITIVE_KEY_NAMES_NORM:
        return True
    if any(norm.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True
    if norm.endswith("token"):
        return True
    return False


# Reusable regex fragment for sensitive key names in key-value logging
_SENSITIVE_KEY_RE = (
    r"(?:password|passwd|pwd|api[_-]?key|secret[_-]?key|secret|auth[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|session[_-]?token|csrf[_-]?token|api[_-]?token|"
    r"id[_-]?token|client[_-]?secret|private[_-]?key|token|access[_-]?key|"
    r"secret[_-]?access[_-]?key|aws[_-]?secret[_-]?access[_-]?key)"
)

# Compiled regular expressions for pattern-based secret redaction
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    # PEM Private Keys
    (
        re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # OpenAI API Keys (legacy sk-, sk-proj-, sk-admin-)
    (
        re.compile(r"\bsk-(?:proj-|admin-)?[a-zA-Z0-9_\-]{20,}\b"),
        "[REDACTED]",
    ),
    # Anthropic API Keys (sk-ant-...)
    (
        re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b"),
        "[REDACTED]",
    ),
    # Google / Gemini API Keys (AIzaSy...)
    (
        re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
        "[REDACTED]",
    ),
    # AWS Access Key IDs
    (
        re.compile(r"\b(?:AKIA|ASIA|AROA)[0-9A-Z]{16}\b"),
        "[REDACTED]",
    ),
    # GitHub Personal Access Tokens
    (
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-zA-Z0-9_]{36,}\b"),
        "[REDACTED]",
    ),
    # JWT Tokens (eyJ...)
    (
        re.compile(r"\beyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\b"),
        "[REDACTED]",
    ),
    # Bearer and Basic Tokens in headers (supports base64 Basic auth with padding)
    (
        re.compile(
            r"(?i)\b((?:bearer|basic)\s+)([a-zA-Z0-9_\-\.=/+]{10,})(?=[^a-zA-Z0-9_\-\.=/+]|$)"
        ),
        r"\g<1>[REDACTED]",
    ),
    # Quoted key-value pairs in JSON, configs, or queries
    (
        re.compile(rf"""(?i)(["']?{_SENSITIVE_KEY_RE}["']?\s*[:=]\s*["'])([^"'\r\n]+)(["'])"""),
        r"\g<1>[REDACTED]\g<3>",
    ),
    # Unquoted key-value pairs (CLI flags, URL params, key=value strings)
    (
        re.compile(rf"""(?i)(["']?{_SENSITIVE_KEY_RE}["']?\s*[:=]\s*)([^\s,;"'&>]+)"""),
        r"\g<1>[REDACTED]",
    ),
]


def mask_secrets(text: str) -> str:
    """Redact sensitive credentials, keys, passwords, and tokens from a string.

    Args:
        text: Input string potentially containing sensitive credentials.

    Returns:
        Safe string with sensitive patterns replaced with redaction markers.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)

    return text


def mask_data(obj: Any, seen: set[int] | None = None) -> Any:
    """Recursively redact secrets across dictionaries, lists, and primitives.

    Args:
        obj: Arbitrary data structure (dict, list, string, primitive).
        seen: Internal set to guard against circular references.

    Returns:
        Sanitized data structure safe for logging and persistent storage.
    """
    if obj is None:
        return None
    if isinstance(obj, str):
        return mask_secrets(obj)
    if isinstance(obj, (int, float, bool)):
        return obj

    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return "[CIRCULAR_REFERENCE]"
    seen.add(obj_id)

    try:
        if isinstance(obj, dict):
            sanitized: dict[str, Any] = {}
            for k, v in obj.items():
                k_str = str(k)
                if is_sensitive_key(k_str):
                    sanitized[k_str] = "[REDACTED]"
                else:
                    sanitized[k_str] = mask_data(v, seen)
            return sanitized
        elif isinstance(obj, (list, tuple)):
            masked_items = [mask_data(item, seen) for item in obj]
            return tuple(masked_items) if isinstance(obj, tuple) else masked_items
        elif isinstance(obj, set):
            return [mask_data(item, seen) for item in sorted(obj, key=str)]
        elif hasattr(obj, "__dict__"):
            return mask_data(vars(obj), seen)
        else:
            return mask_secrets(str(obj))
    finally:
        seen.remove(obj_id)


# ---------------------------------------------------------------------------
# Execution Context Management
# ---------------------------------------------------------------------------

_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "atlas_logging_context", default=None
)


def bind_context(**kwargs: Any) -> None:
    """Bind metadata keys and values to the current execution context."""
    current = _context.get() or {}
    _context.set({**current, **kwargs})


def unbind_context(*keys: str) -> None:
    """Remove specific metadata keys from the current execution context."""
    current = dict(_context.get() or {})
    for k in keys:
        current.pop(k, None)
    _context.set(current)


def clear_context() -> None:
    """Clear all metadata keys from the current execution context."""
    _context.set({})


def get_context() -> dict[str, Any]:
    """Retrieve a copy of the current context metadata."""
    return dict(_context.get() or {})


@contextlib.contextmanager
def context_scope(**kwargs: Any) -> Generator[dict[str, Any], None, None]:
    """Context manager for temporary context binding that automatically reverts on exit."""
    current = _context.get() or {}
    token = _context.set({**current, **kwargs})
    try:
        yield get_context()
    finally:
        _context.reset(token)


# ---------------------------------------------------------------------------
# Structured JSON Formatter
# ---------------------------------------------------------------------------


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON with context tags and secret masking."""

    _STANDARD_LOG_RECORD_ATTRS: frozenset[str] = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "_atlas_extra",
            "_atlas_instance_context",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        # ISO 8601 UTC timestamp
        utc_dt = datetime.fromtimestamp(record.created, tz=UTC)
        timestamp_str = utc_dt.isoformat().replace("+00:00", "Z")

        data: dict[str, Any] = {
            "timestamp": timestamp_str,
            "level": record.levelname,
            "logger": record.name,
        }

        # Format and mask message
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        data["message"] = mask_secrets(msg)

        # Contextvars metadata
        bound_ctx = get_context()
        for k, v in mask_data(bound_ctx).items():
            data[k] = v

        # Logger instance-level bound metadata
        instance_ctx = getattr(record, "_atlas_instance_context", {})
        if instance_ctx:
            for k, v in mask_data(instance_ctx).items():
                data[k] = v

        # Call-site extra arguments
        call_extra = getattr(record, "_atlas_extra", {})
        if call_extra:
            for k, v in mask_data(call_extra).items():
                data[k] = v

        # Standard logging extra attributes (if caller logged with extra={...})
        for k, v in record.__dict__.items():
            if k not in self._STANDARD_LOG_RECORD_ATTRS and k not in data:
                data[k] = mask_data(v)

        # Format exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            data["exception"] = mask_secrets(exc_text)
        elif record.exc_text:
            data["exception"] = mask_secrets(record.exc_text)

        return json.dumps(data, default=str)


# ---------------------------------------------------------------------------
# Structured Logger Wrapper
# ---------------------------------------------------------------------------


class StructuredLogger:
    """Wrapper around standard library Logger providing kwargs support and secret safety."""

    def __init__(
        self,
        logger: logging.Logger,
        bound_context: dict[str, Any] | None = None,
    ) -> None:
        self._logger = logger
        self._bound_context: dict[str, Any] = bound_context or {}

    @property
    def name(self) -> str:
        return self._logger.name

    @property
    def level(self) -> int:
        return self._logger.level

    @property
    def handlers(self) -> list[logging.Handler]:
        return self._logger.handlers

    def setLevel(self, level: int | str) -> None:
        self._logger.setLevel(level)

    def isEnabledFor(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)

    def addHandler(self, hdlr: logging.Handler) -> None:
        self._logger.addHandler(hdlr)

    def removeHandler(self, hdlr: logging.Handler) -> None:
        self._logger.removeHandler(hdlr)

    def bind(self, **kwargs: Any) -> StructuredLogger:
        """Create a new StructuredLogger instance with permanently bound context."""
        merged = {**self._bound_context, **kwargs}
        return StructuredLogger(self._logger, bound_context=merged)

    def _log(
        self,
        level: int,
        msg: str,
        *args: Any,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 2,
        **kwargs: Any,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return

        if "exc_info" in kwargs and exc_info is None:
            exc_info = kwargs.pop("exc_info")

        extra = {
            "_atlas_extra": kwargs,
            "_atlas_instance_context": self._bound_context,
        }

        self._logger.log(
            level,
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=extra,
        )

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def warn(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def fatal(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, exc_info: Any = True, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, *args, exc_info=exc_info, **kwargs)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(level, msg, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


# ---------------------------------------------------------------------------
# Logger Factory
# ---------------------------------------------------------------------------


def get_logger(
    name: str = "atlas",
    stream: IO[str] | None = None,
    level: int | str = logging.INFO,
) -> StructuredLogger:
    """Retrieve or create a context-bound StructuredLogger with secret masking.

    Args:
        name: Hierarchical logger name.
        stream: Optional output stream. Defaults to stdout.
        level: Minimum log level.

    Returns:
        Configured StructuredLogger instance.
    """
    base_logger = logging.getLogger(name)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    base_logger.setLevel(level)

    if stream is not None:
        # Clear previous atlas handlers on this logger to allow dynamic stream redirection
        base_logger.handlers = [
            h for h in base_logger.handlers if not getattr(h, "_atlas_handler", False)
        ]
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredJsonFormatter())
        handler._atlas_handler = True  # type: ignore[attr-defined]
        base_logger.addHandler(handler)
        base_logger.propagate = False
    else:
        # Attach default stdout handler if none present
        if not any(getattr(h, "_atlas_handler", False) for h in base_logger.handlers):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(StructuredJsonFormatter())
            handler._atlas_handler = True  # type: ignore[attr-defined]
            base_logger.addHandler(handler)
            base_logger.propagate = False

    return StructuredLogger(base_logger)

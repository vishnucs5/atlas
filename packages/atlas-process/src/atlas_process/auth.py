"""ATLAS Process Authentication & Multi-Tenant Authorization.

Provides caller identity resolution, API key authentication, HMAC token verification,
session integration with Enterprise IAM, and multi-tenant access control for process APIs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, Field


@dataclass
class ProcessCallerIdentity:
    """Represents an authenticated caller issuing requests to process APIs."""

    caller_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    is_service: bool = False

    def has_role(self, role: str) -> bool:
        return role.upper() in [r.upper() for r in self.roles]

    def is_admin(self) -> bool:
        return (
            self.has_role("ADMIN") or self.has_role("SYSTEM_ADMIN") or self.has_role("SUPERADMIN")
        )


class TokenClaims(BaseModel):
    """Claims carried in a signed process bearer token."""

    sub: str  # caller_id
    tid: str  # tenant_id
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    exp: float
    iat: float = Field(default_factory=time.time)
    jti: str = Field(default_factory=lambda: secrets.token_hex(12))


# In-memory registry for API keys and global IAM engine reference
_REGISTERED_API_KEYS: dict[str, ProcessCallerIdentity] = {}
_IAM_ENGINE: Any | None = None
_DEFAULT_TOKEN_SECRET = secrets.token_hex(32)


def set_token_secret(secret: str) -> None:
    """Set custom signing secret for bearer tokens."""
    global _DEFAULT_TOKEN_SECRET
    _DEFAULT_TOKEN_SECRET = secret


def set_iam_engine(iam_engine: Any | None) -> None:
    """Set the enterprise IAM engine used for session token validation."""
    global _IAM_ENGINE
    _IAM_ENGINE = iam_engine


def register_api_key(api_key: str, identity: ProcessCallerIdentity) -> None:
    """Register an API key with an associated caller identity."""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    _REGISTERED_API_KEYS[key_hash] = identity


def revoke_api_key(api_key: str) -> bool:
    """Revoke a previously registered API key."""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    return _REGISTERED_API_KEYS.pop(key_hash, None) is not None


def clear_api_keys() -> None:
    """Clear all registered API keys."""
    _REGISTERED_API_KEYS.clear()


def issue_process_token(
    caller_id: str,
    tenant_id: str,
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
    ttl_seconds: float = 3600.0,
    secret: str | None = None,
) -> str:
    """Generate a tamper-evident HMAC signed bearer token for process API calls."""
    signing_secret = secret or _DEFAULT_TOKEN_SECRET
    now = time.time()
    claims = TokenClaims(
        sub=caller_id,
        tid=tenant_id,
        roles=roles or ["USER"],
        scopes=scopes or ["process:execute", "process:read"],
        iat=now,
        exp=now + ttl_seconds,
    )
    payload_bytes = json.dumps(claims.model_dump(), separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")

    signature = hmac.new(
        signing_secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"atk_proc_{payload_b64}.{sig_b64}"


def verify_process_token(token: str, secret: str | None = None) -> ProcessCallerIdentity:
    """Verify an HMAC signed process token and extract caller identity."""
    signing_secret = secret or _DEFAULT_TOKEN_SECRET
    if not token.startswith("atk_proc_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format.",
        )

    raw = token[len("atk_proc_") :]
    parts = raw.split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token structure.",
        )

    payload_b64, sig_b64 = parts
    # Verify signature in constant time
    expected_sig = hmac.new(
        signing_secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode("ascii").rstrip("=")

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature.",
        )

    # Decode and validate payload
    try:
        # Add back base64 padding
        padding = 4 - (len(payload_b64) % 4)
        if padding != 4:
            payload_b64 += "=" * padding
        payload_json = json.loads(
            base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        )
        claims = TokenClaims(**payload_json)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token payload: {exc}",
        ) from exc

    if time.time() > claims.exp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )

    return ProcessCallerIdentity(
        caller_id=claims.sub,
        tenant_id=claims.tid,
        roles=claims.roles,
        scopes=claims.scopes,
        is_service=False,
    )


def get_current_identity(
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> ProcessCallerIdentity:
    """FastAPI security dependency resolving caller identity from Bearer token or API key."""
    # 1. API key authentication via X-API-Key header
    if x_api_key:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        if key_hash in _REGISTERED_API_KEYS:
            return _REGISTERED_API_KEYS[key_hash]

        # Check IAM engine if available
        if _IAM_ENGINE is not None:
            try:
                svc = _IAM_ENGINE.authenticate_api_key(x_api_key)
                return ProcessCallerIdentity(
                    caller_id=svc.service_id,
                    tenant_id=svc.org_id,
                    roles=["SERVICE"],
                    scopes=svc.scopes,
                    is_service=True,
                )
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    # 2. Bearer token authentication via Authorization header
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header must use Bearer scheme.",
            )
        token = authorization[len("Bearer ") :].strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty bearer token.",
            )

        # Check if it's an atlas_proc signed token
        if token.startswith("atk_proc_"):
            return verify_process_token(token)

        # Check if it's a registered API key passed via Bearer
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        if key_hash in _REGISTERED_API_KEYS:
            return _REGISTERED_API_KEYS[key_hash]

        # Check IAM engine session
        if _IAM_ENGINE is not None:
            try:
                session = _IAM_ENGINE.validate_session(token)
                return ProcessCallerIdentity(
                    caller_id=session.user_id,
                    tenant_id=session.org_id,
                    roles=[str(session.role.value)]
                    if hasattr(session.role, "value")
                    else [str(session.role)],
                    scopes=["process:all"],
                    is_service=False,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Session authentication failed: {exc}",
                ) from exc

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unrecognized bearer token.",
        )

    # 3. No credentials provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials required (provide Authorization Bearer token or X-API-Key header).",
    )


def verify_tenant_access(caller: ProcessCallerIdentity, target_tenant_id: str) -> None:
    """Enforce strict multi-tenant authorization boundaries."""
    if caller.is_admin():
        return

    if caller.tenant_id != target_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cross-tenant access forbidden: caller tenant '{caller.tenant_id}' cannot access resources of tenant '{target_tenant_id}'.",
        )

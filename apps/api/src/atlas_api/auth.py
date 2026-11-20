"""Authentication and Role-Based Access Control (RBAC) for the ATLAS REST API."""

import hashlib
import hmac
import os
import time
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from pydantic import BaseModel


class Role(StrEnum):
    """User and service identity roles governing ATLAS API operations."""

    ADMIN = "admin"
    OPERATOR = "operator"
    WORKER = "worker"
    VIEWER = "viewer"


class AuthenticatedUser(BaseModel):
    """Authenticated API client profile."""

    role: Role
    token_preview: str
    user_id: str


def _configured_api_key(name: str, development_default: str) -> str:
    """Load an API key, refusing unsafe implicit credentials in production."""
    value = os.getenv(name)
    if value:
        return value
    if os.getenv("ATLAS_ENV", "development").lower() == "production":
        raise RuntimeError(f"{name} must be set when ATLAS_ENV=production.")
    return development_default


# Configurable API keys per role. Production must always provide unique secrets.
DEFAULT_KEYS = {
    Role.ADMIN: _configured_api_key("ATLAS_API_KEY_ADMIN", "admin-key"),
    Role.OPERATOR: _configured_api_key("ATLAS_API_KEY_OPERATOR", "operator-key"),
    Role.WORKER: _configured_api_key("ATLAS_API_KEY_WORKER", "worker-key"),
    Role.VIEWER: _configured_api_key("ATLAS_API_KEY_VIEWER", "viewer-key"),
}

# Role permission hierarchy mapping: which roles are satisfied by a given user role
ROLE_PERMISSIONS: dict[Role, set[Role]] = {
    Role.ADMIN: {Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER},
    Role.OPERATOR: {Role.OPERATOR, Role.VIEWER},
    Role.WORKER: {Role.WORKER, Role.VIEWER},
    Role.VIEWER: {Role.VIEWER},
}

# Token revocation and expiration registry
_REVOKED_TOKENS: set[str] = set()
_TOKEN_EXPIRATIONS: dict[str, float] = {}


def revoke_token(token: str) -> None:
    """Revoke an active API token."""
    _REVOKED_TOKENS.add(token.strip())


def is_token_revoked(token: str) -> bool:
    """Check if an API token has been explicitly revoked."""
    return token.strip() in _REVOKED_TOKENS


def set_token_expiry(token: str, expires_at: float) -> None:
    """Set an explicit UNIX epoch expiration timestamp for a token."""
    _TOKEN_EXPIRATIONS[token.strip()] = expires_at


def reset_token_registry() -> None:
    """Reset the token revocation and expiration registries (for testing)."""
    _REVOKED_TOKENS.clear()
    _TOKEN_EXPIRATIONS.clear()


def _extract_token(
    authorization: str | None = None,
    x_api_key: str | None = None,
    api_key_query: str | None = None,
) -> str | None:
    """Extract API key from Bearer header, X-API-Key header, or query parameter."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if api_key_query and api_key_query.strip():
        return api_key_query.strip()
    return None


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    api_key: Annotated[str | None, Query(alias="api_key")] = None,
) -> AuthenticatedUser:
    """Validate API token and resolve client role using constant-time comparison."""
    token = _extract_token(authorization, x_api_key, api_key)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required (Bearer token or X-API-Key).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_token_revoked(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key or token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token in _TOKEN_EXPIRATIONS and time.time() > _TOKEN_EXPIRATIONS[token]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key or token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison against configured keys to defeat timing side-channel attacks
    token_bytes = token.encode("utf-8")
    matched_role: Role | None = None
    for role, key in DEFAULT_KEYS.items():
        key_bytes = key.encode("utf-8")
        if hmac.compare_digest(token_bytes, key_bytes):
            matched_role = role
            break

    if matched_role is not None:
        user_hash = hashlib.sha256(token_bytes).hexdigest()[:8]
        user_id = f"user_{matched_role.value}_{user_hash}"
        return AuthenticatedUser(
            role=matched_role,
            token_preview=token[:4] + "***",
            user_id=user_id,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key or token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(*allowed_roles: Role):
    """FastAPI dependency factory enforcing RBAC permission boundaries."""

    def dependency(
        current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        user_permissions = ROLE_PERMISSIONS.get(current_user.role, set())
        if not any(req in user_permissions for req in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Role '{current_user.role.value}' does not have sufficient privileges.",
            )
        return current_user

    return dependency

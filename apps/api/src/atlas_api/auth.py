"""Authentication and Role-Based Access Control (RBAC) for the ATLAS REST API."""

import os
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


# Configurable API keys per role
DEFAULT_KEYS = {
    Role.ADMIN: os.getenv("ATLAS_API_KEY_ADMIN", "admin-key"),
    Role.OPERATOR: os.getenv("ATLAS_API_KEY_OPERATOR", "operator-key"),
    Role.WORKER: os.getenv("ATLAS_API_KEY_WORKER", "worker-key"),
    Role.VIEWER: os.getenv("ATLAS_API_KEY_VIEWER", "viewer-key"),
}

# Role permission hierarchy mapping: which roles are satisfied by a given user role
ROLE_PERMISSIONS: dict[Role, set[Role]] = {
    Role.ADMIN: {Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER},
    Role.OPERATOR: {Role.OPERATOR, Role.VIEWER},
    Role.WORKER: {Role.WORKER, Role.VIEWER},
    Role.VIEWER: {Role.VIEWER},
}


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
    """Validate API token and resolve client role."""
    token = _extract_token(authorization, x_api_key, api_key)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required (Bearer token or X-API-Key).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Match token to configured keys
    for role, key in DEFAULT_KEYS.items():
        if token == key:
            return AuthenticatedUser(role=role, token_preview=token[:4] + "***")

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

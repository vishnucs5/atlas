"""Enterprise Identity and Access Management (IAM), RBAC, ABAC, SSO/SCIM, and Service Identity."""

import hashlib
import ipaddress
import logging
import secrets
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas_enterprise.models import (
    ABACContext,
    IdentityProviderConfig,
    MembershipRole,
    OrganizationMembership,
    PermissionAction,
    ServiceIdentity,
    SessionToken,
    TenantOwnedResource,
    User,
)
from atlas_enterprise.organization import EnterpriseOrganizationManager

logger = logging.getLogger("atlas.enterprise.iam")


class EnterpriseIAMError(Exception):
    """Base exception for enterprise IAM operations."""


class UnauthorizedError(EnterpriseIAMError):
    """Raised when an operation lacks necessary RBAC permissions."""


class PrivilegeEscalationError(EnterpriseIAMError):
    """Raised when a user attempts to grant or claim unauthorized privileges."""


class SessionExpiredError(EnterpriseIAMError):
    """Raised when a session token has passed its expiration time."""


class SessionRevokedError(EnterpriseIAMError):
    """Raised when a revoked session token is presented."""


class ABACPolicyViolationError(EnterpriseIAMError):
    """Raised when dynamic contextual attributes violate an ABAC policy."""


class IdentityFederationError(EnterpriseIAMError):
    """Raised when federated IdP authentication or assertion validation fails."""


class ServiceIdentityNotFoundError(EnterpriseIAMError):
    """Raised when a service identity or API key cannot be located."""


# Granular RBAC Role-to-Permission Mapping
ROLE_PERMISSIONS: dict[MembershipRole, set[PermissionAction]] = {
    MembershipRole.ORG_OWNER: set(PermissionAction),
    MembershipRole.ORG_ADMIN: {p for p in PermissionAction if p != PermissionAction.ORG_DELETE},
    MembershipRole.SECURITY_ADMIN: {
        PermissionAction.ORG_READ,
        PermissionAction.MEMBER_MANAGE,
        PermissionAction.IAM_MANAGE_ROLES,
        PermissionAction.IAM_MANAGE_POLICY,
        PermissionAction.IAM_MANAGE_CREDENTIALS,
        PermissionAction.AUDIT_READ,
        PermissionAction.AUDIT_EXPORT,
        PermissionAction.APPROVAL_DECIDE,
        PermissionAction.AGENT_READ,
        PermissionAction.WORKFLOW_READ,
    },
    MembershipRole.DEPT_ADMIN: {
        PermissionAction.ORG_READ,
        PermissionAction.DEPT_MANAGE,
        PermissionAction.AGENT_REGISTER,
        PermissionAction.AGENT_READ,
        PermissionAction.AGENT_UPDATE,
        PermissionAction.AGENT_EXECUTE,
        PermissionAction.WORKFLOW_REGISTER,
        PermissionAction.WORKFLOW_PUBLISH,
        PermissionAction.WORKFLOW_READ,
        PermissionAction.WORKFLOW_EXECUTE,
        PermissionAction.SKILL_READ,
        PermissionAction.INTEGRATION_READ,
        PermissionAction.COST_READ,
        PermissionAction.BUDGET_MANAGE,
        PermissionAction.APPROVAL_SUBMIT,
    },
    MembershipRole.DEVELOPER: {
        PermissionAction.ORG_READ,
        PermissionAction.AGENT_REGISTER,
        PermissionAction.AGENT_READ,
        PermissionAction.AGENT_UPDATE,
        PermissionAction.AGENT_EXECUTE,
        PermissionAction.WORKFLOW_REGISTER,
        PermissionAction.WORKFLOW_READ,
        PermissionAction.SKILL_READ,
        PermissionAction.INTEGRATION_READ,
        PermissionAction.APPROVAL_SUBMIT,
    },
    MembershipRole.WORKFLOW_PUBLISHER: {
        PermissionAction.ORG_READ,
        PermissionAction.WORKFLOW_REGISTER,
        PermissionAction.WORKFLOW_PUBLISH,
        PermissionAction.WORKFLOW_READ,
        PermissionAction.SKILL_MANAGE,
        PermissionAction.SKILL_READ,
        PermissionAction.AGENT_READ,
    },
    MembershipRole.OPERATOR: {
        PermissionAction.ORG_READ,
        PermissionAction.AGENT_READ,
        PermissionAction.AGENT_EXECUTE,
        PermissionAction.WORKFLOW_READ,
        PermissionAction.WORKFLOW_EXECUTE,
        PermissionAction.INTEGRATION_INVOKE,
        PermissionAction.APPROVAL_SUBMIT,
        PermissionAction.AUDIT_READ,
    },
    MembershipRole.AUDITOR: {
        PermissionAction.ORG_READ,
        PermissionAction.AUDIT_READ,
        PermissionAction.AUDIT_EXPORT,
        PermissionAction.COST_READ,
        PermissionAction.AGENT_READ,
        PermissionAction.WORKFLOW_READ,
    },
    MembershipRole.VIEWER: {
        PermissionAction.ORG_READ,
        PermissionAction.AGENT_READ,
        PermissionAction.WORKFLOW_READ,
        PermissionAction.COST_READ,
    },
}

# Role hierarchy levels used for privilege escalation prevention
ROLE_HIERARCHY_LEVEL: dict[MembershipRole, int] = {
    MembershipRole.ORG_OWNER: 100,
    MembershipRole.ORG_ADMIN: 90,
    MembershipRole.SECURITY_ADMIN: 80,
    MembershipRole.DEPT_ADMIN: 70,
    MembershipRole.DEVELOPER: 50,
    MembershipRole.WORKFLOW_PUBLISHER: 50,
    MembershipRole.OPERATOR: 40,
    MembershipRole.AUDITOR: 30,
    MembershipRole.VIEWER: 10,
}

CLEARANCE_LEVELS: dict[str, int] = {
    "standard": 0,
    "confidential": 1,
    "secret": 2,
    "top_secret": 3,
}


def can_assign_role(caller_role: MembershipRole, target_role: MembershipRole) -> bool:
    """Evaluate whether caller_role has authority to grant target_role."""
    if caller_role == MembershipRole.ORG_OWNER:
        return True
    caller_level = ROLE_HIERARCHY_LEVEL.get(caller_role, 0)
    target_level = ROLE_HIERARCHY_LEVEL.get(target_role, 0)
    # Caller can only grant roles strictly lower than their own level
    # and only if caller is at least a DEPT_ADMIN (level >= 70)
    if caller_level < 70:
        return False
    return caller_level > target_level


class ABACPolicyEngine:
    """Evaluates dynamic contextual and resource attributes for access control."""

    @staticmethod
    def evaluate(
        context: ABACContext,
        resource: TenantOwnedResource | None = None,
        policy_rules: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Evaluate contextual attributes against resource constraints and policy rules.

        Returns (is_allowed, violation_reason).
        """
        rules = policy_rules or {}

        # 1. IP allowlist evaluation
        allowed_ips = rules.get("allowed_ips", [])
        if allowed_ips and context.client_ip:
            client_ip_obj = ipaddress.ip_address(context.client_ip)
            ip_matched = False
            for allowed in allowed_ips:
                try:
                    if "/" in allowed:
                        if client_ip_obj in ipaddress.ip_network(allowed, strict=False):
                            ip_matched = True
                            break
                    elif client_ip_obj == ipaddress.ip_address(allowed):
                        ip_matched = True
                        break
                except ValueError:
                    continue
            if not ip_matched:
                return False, f"Client IP {context.client_ip} not in authorized network allowlist"

        # 2. Working hours restriction evaluation
        allowed_hours = rules.get("allowed_hours")  # Tuple/List of (start_hour, end_hour)
        if allowed_hours and len(allowed_hours) == 2:
            start_hour, end_hour = allowed_hours
            current_hour = context.current_time.hour
            if not (start_hour <= current_hour < end_hour):
                return (
                    False,
                    f"Access denied outside authorized operating hours ({start_hour}:00 - {end_hour}:00 UTC)",
                )

        # 3. Security clearance evaluation
        required_clearance = rules.get("required_clearance")
        if required_clearance:
            user_clearance = CLEARANCE_LEVELS.get(context.security_clearance.lower(), 0)
            req_clearance = CLEARANCE_LEVELS.get(required_clearance.lower(), 0)
            if user_clearance < req_clearance:
                return (
                    False,
                    f"Insufficient security clearance: required {required_clearance}, subject has {context.security_clearance}",
                )

        # 4. Department boundary evaluation
        if resource and resource.department_id and context.department_id:
            if resource.department_id != context.department_id:
                # If resource is departmental, and user is departmental, departments must match
                is_admin_override = rules.get("admin_override", False)
                if not is_admin_override:
                    return (
                        False,
                        f"Cross-department resource access rejected: resource belongs to {resource.department_id}",
                    )

        return True, None


class EnterpriseIAMEngine:
    """Enterprise Identity & Access Management engine for ATLAS."""

    def __init__(self, org_manager: EnterpriseOrganizationManager) -> None:
        self.org_manager = org_manager
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionToken] = {}
        self._user_sessions: dict[str, set[str]] = {}
        self._idps: dict[str, IdentityProviderConfig] = {}
        self._service_identities: dict[str, ServiceIdentity] = {}
        self._api_key_hashes: dict[str, str] = {}  # hash -> service_id

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def create_session(
        self,
        user_id: str,
        org_id: str,
        client_ip: str | None = None,
        ttl_hours: float = 8.0,
    ) -> SessionToken:
        """Create an authenticated session token for a user in an organization."""
        with self._lock:
            user = self.org_manager.get_user(user_id)
            if not user.is_active:
                raise UnauthorizedError(f"User {user_id} is inactive or deprovisioned")

            org = self.org_manager.get_organization(org_id)
            if org.status != "ACTIVE":
                raise UnauthorizedError(f"Organization {org_id} is {org.status}")

            membership = self.org_manager.get_membership(org_id, user_id)
            if not membership or not membership.is_active:
                raise UnauthorizedError(f"User {user_id} has no active membership in {org_id}")

            token_id = f"atk_sess_{secrets.token_hex(24)}"
            now = datetime.now(UTC)
            expires_at = now + timedelta(hours=ttl_hours)

            session = SessionToken(
                token_id=token_id,
                user_id=user_id,
                org_id=org_id,
                role=membership.role,
                department_id=membership.department_id,
                client_ip=client_ip,
                issued_at=now,
                expires_at=expires_at,
                is_revoked=False,
            )

            self._sessions[token_id] = session
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = set()
            self._user_sessions[user_id].add(token_id)

            logger.info(
                "Created session %s for user %s (role=%s, org=%s)",
                token_id,
                user_id,
                membership.role,
                org_id,
            )
            return session

    def validate_session(self, token_id: str, client_ip: str | None = None) -> SessionToken:
        """Validate active session token, verifying expiry and revocation status."""
        with self._lock:
            session = self._sessions.get(token_id)
            if not session:
                raise UnauthorizedError("Invalid or unknown session token")

            if session.is_revoked:
                raise SessionRevokedError(f"Session {token_id} has been revoked")

            now = datetime.now(UTC)
            if now > session.expires_at:
                raise SessionExpiredError(
                    f"Session {token_id} expired at {session.expires_at.isoformat()}"
                )

            user = self.org_manager.get_user(session.user_id)
            if not user.is_active:
                raise UnauthorizedError(f"User {session.user_id} is deactivated")

            return session

    def revoke_session(self, token_id: str) -> None:
        """Revoke a specific session token."""
        with self._lock:
            session = self._sessions.get(token_id)
            if session:
                session.is_revoked = True
                logger.info("Revoked session %s for user %s", token_id, session.user_id)

    def revoke_user_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user (e.g. on deprovisioning or security event)."""
        with self._lock:
            revoked_count = 0
            session_ids = self._user_sessions.get(user_id, set())
            for sid in session_ids:
                session = self._sessions.get(sid)
                if session and not session.is_revoked:
                    session.is_revoked = True
                    revoked_count += 1
            logger.info("Revoked %d sessions for user %s", revoked_count, user_id)
            return revoked_count

    # -------------------------------------------------------------------------
    # Authorization & Permission Evaluation
    # -------------------------------------------------------------------------

    def evaluate_permission(
        self,
        user_id: str,
        org_id: str,
        action: PermissionAction,
        resource: TenantOwnedResource | None = None,
        abac_context: ABACContext | None = None,
        policy_rules: dict[str, Any] | None = None,
    ) -> bool:
        """Evaluate if user_id in org_id has permission for action, considering RBAC and ABAC."""
        with self._lock:
            # 1. Organization boundary check
            if resource and resource.org_id != org_id:
                return False

            # 2. RBAC check
            membership = self.org_manager.get_membership(org_id, user_id)
            if not membership or not membership.is_active:
                return False

            allowed_actions = ROLE_PERMISSIONS.get(membership.role, set())
            if action not in allowed_actions:
                return False

            # 3. ABAC evaluation if context or policy rules are supplied
            effective_rules = dict(policy_rules or {})
            # Org-level admins get admin override on departmental boundaries
            if membership.role in {
                MembershipRole.ORG_OWNER,
                MembershipRole.ORG_ADMIN,
                MembershipRole.SECURITY_ADMIN,
                MembershipRole.AUDITOR,
            }:
                effective_rules["admin_override"] = True

            if abac_context:
                allowed, _reason = ABACPolicyEngine.evaluate(
                    abac_context, resource=resource, policy_rules=effective_rules
                )
                if not allowed:
                    return False

            return True

    def assert_permission(
        self,
        user_id: str,
        org_id: str,
        action: PermissionAction,
        resource: TenantOwnedResource | None = None,
        abac_context: ABACContext | None = None,
        policy_rules: dict[str, Any] | None = None,
    ) -> None:
        """Assert user has permission; raise UnauthorizedError or ABACPolicyViolationError if denied."""
        with self._lock:
            if resource and resource.org_id != org_id:
                raise UnauthorizedError(
                    f"Cross-tenant access rejected: user org {org_id} != resource org {resource.org_id}"
                )

            membership = self.org_manager.get_membership(org_id, user_id)
            if not membership or not membership.is_active:
                raise UnauthorizedError(
                    f"User {user_id} has no active membership in organization {org_id}"
                )

            allowed_actions = ROLE_PERMISSIONS.get(membership.role, set())
            if action not in allowed_actions:
                raise UnauthorizedError(
                    f"Action '{action}' is not permitted for role '{membership.role}' in organization '{org_id}'"
                )

            effective_rules = dict(policy_rules or {})
            if membership.role in {
                MembershipRole.ORG_OWNER,
                MembershipRole.ORG_ADMIN,
                MembershipRole.SECURITY_ADMIN,
                MembershipRole.AUDITOR,
            }:
                effective_rules["admin_override"] = True

            if abac_context:
                allowed, reason = ABACPolicyEngine.evaluate(
                    abac_context, resource=resource, policy_rules=effective_rules
                )
                if not allowed:
                    raise ABACPolicyViolationError(f"ABAC policy violation: {reason}")

    # -------------------------------------------------------------------------
    # Privilege Escalation Guard
    # -------------------------------------------------------------------------

    def assign_role(
        self,
        caller_user_id: str,
        target_user_id: str,
        org_id: str,
        new_role: MembershipRole,
        department_id: str | None = None,
    ) -> OrganizationMembership:
        """Assign or update a user's role while strictly enforcing privilege escalation guards."""
        with self._lock:
            caller_membership = self.org_manager.get_membership(org_id, caller_user_id)
            if not caller_membership or not caller_membership.is_active:
                raise UnauthorizedError(
                    f"Caller {caller_user_id} has no active membership in {org_id}"
                )

            # Verify caller has privilege to grant this role
            if not can_assign_role(caller_membership.role, new_role):
                raise PrivilegeEscalationError(
                    f"Caller with role '{caller_membership.role}' cannot assign higher or equal role '{new_role}'"
                )

            # Prevent users from escalating their own role
            if caller_user_id == target_user_id:
                raise PrivilegeEscalationError(
                    "Self-elevation is strictly prohibited: users cannot modify their own role"
                )

            # Perform the assignment
            _, membership = self.org_manager.add_member(
                org_id=org_id,
                user_id=target_user_id,
                role=new_role,
                department_id=department_id,
            )
            logger.info(
                "Caller %s assigned role %s to %s in org %s",
                caller_user_id,
                new_role,
                target_user_id,
                org_id,
            )
            return membership

    # -------------------------------------------------------------------------
    # Service Identity & Cryptographic API Keys
    # -------------------------------------------------------------------------

    def create_service_identity(
        self,
        org_id: str,
        name: str,
        scopes: list[str],
        department_id: str | None = None,
        expires_in_days: int = 90,
    ) -> tuple[ServiceIdentity, str]:
        """Create a service identity and return (ServiceIdentity, raw_secret_api_key).

        The raw secret API key is returned exactly once and never persisted in plain text.
        """
        with self._lock:
            self.org_manager.get_organization(org_id)
            service_id = f"svc_{uuid.uuid4().hex[:12]}"
            raw_key = f"atk_live_{secrets.token_urlsafe(32)}"
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

            now = datetime.now(UTC)
            expires_at = now + timedelta(days=expires_in_days) if expires_in_days > 0 else None

            svc = ServiceIdentity(
                service_id=service_id,
                org_id=org_id,
                department_id=department_id,
                name=name,
                api_key_hash=key_hash,
                scopes=scopes,
                is_active=True,
                expires_at=expires_at,
            )

            self._service_identities[service_id] = svc
            self._api_key_hashes[key_hash] = service_id
            logger.info("Created service identity %s (%s) for org %s", service_id, name, org_id)
            return svc, raw_key

    def authenticate_api_key(self, raw_api_key: str) -> ServiceIdentity:
        """Authenticate an incoming raw API key against stored cryptographic hashes."""
        with self._lock:
            key_hash = hashlib.sha256(raw_api_key.encode()).hexdigest()
            service_id = self._api_key_hashes.get(key_hash)
            if not service_id:
                raise UnauthorizedError("Invalid API key")

            svc = self._service_identities.get(service_id)
            if not svc or not svc.is_active:
                raise UnauthorizedError(f"Service identity {service_id} is inactive or revoked")

            if svc.expires_at and datetime.now(UTC) > svc.expires_at:
                raise UnauthorizedError(f"API key for service identity {service_id} has expired")

            return svc

    def rotate_api_key(self, service_id: str, expires_in_days: int = 90) -> str:
        """Rotate the API key for an existing service identity, invalidating the old key."""
        with self._lock:
            svc = self._service_identities.get(service_id)
            if not svc:
                raise ServiceIdentityNotFoundError(f"Service identity {service_id} not found")

            # Remove old hash mapping
            old_hash = svc.api_key_hash
            self._api_key_hashes.pop(old_hash, None)

            # Generate new key
            raw_key = f"atk_live_{secrets.token_urlsafe(32)}"
            new_hash = hashlib.sha256(raw_key.encode()).hexdigest()

            svc.api_key_hash = new_hash
            svc.updated_at = datetime.now(UTC)
            if expires_in_days > 0:
                svc.expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

            self._api_key_hashes[new_hash] = service_id
            logger.info("Rotated API key for service identity %s", service_id)
            return raw_key

    def revoke_service_identity(self, service_id: str) -> None:
        """Revoke a service identity and invalidate its keys."""
        with self._lock:
            svc = self._service_identities.get(service_id)
            if svc:
                svc.is_active = False
                self._api_key_hashes.pop(svc.api_key_hash, None)
                logger.info("Revoked service identity %s", service_id)

    # -------------------------------------------------------------------------
    # Enterprise SSO / Identity Federation (OIDC / SAML / SCIM)
    # -------------------------------------------------------------------------

    def register_idp(self, config: IdentityProviderConfig) -> None:
        """Register or update an enterprise Identity Provider configuration."""
        with self._lock:
            self._idps[config.idp_id] = config
            logger.info(
                "Registered IdP %s (%s) for org %s", config.idp_id, config.idp_type, config.org_id
            )

    def authenticate_sso(
        self,
        idp_id: str,
        assertion: dict[str, Any],
        client_ip: str | None = None,
    ) -> tuple[User, SessionToken]:
        """Authenticate federated SSO assertion, provision/update user, and issue session."""
        with self._lock:
            idp = self._idps.get(idp_id)
            if not idp or not idp.is_active:
                raise IdentityFederationError(f"IdP {idp_id} not registered or inactive")

            email = assertion.get("email")
            if not email or "@" not in email:
                raise IdentityFederationError("SSO assertion missing valid email")

            # Domain allowlist check
            domain = email.split("@")[1]
            if idp.domain_allowlist and domain not in idp.domain_allowlist:
                raise IdentityFederationError(
                    f"Email domain '{domain}' not in IdP authorized domain allowlist"
                )

            sub = str(assertion.get("sub", email))
            full_name = assertion.get("name", email.split("@")[0].capitalize())
            groups = assertion.get("groups", [])

            # Map groups to enterprise role
            assigned_role = MembershipRole.VIEWER
            for group, role in idp.role_mapping.items():
                if group in groups:
                    assigned_role = role
                    break

            # Find or provision user
            user_id = f"usr_{hashlib.sha256(sub.encode()).hexdigest()[:12]}"
            try:
                user = self.org_manager.get_user(user_id)
            except Exception:
                user = self.org_manager.provision_user(
                    user_id=user_id, email=email, full_name=full_name
                )

            # Ensure membership exists in organization
            membership = self.org_manager.get_membership(idp.org_id, user_id)
            if not membership:
                self.org_manager.add_member(org_id=idp.org_id, user_id=user_id, role=assigned_role)

            session = self.create_session(user_id=user_id, org_id=idp.org_id, client_ip=client_ip)
            return user, session

    # -------------------------------------------------------------------------
    # SCIM 2.0 Directory Synchronization
    # -------------------------------------------------------------------------

    def scim_provision_user(self, org_id: str, scim_payload: dict[str, Any]) -> User:
        """Provision a user via SCIM 2.0 protocol payload."""
        with self._lock:
            email = scim_payload.get("userName") or scim_payload.get("email")
            if not email:
                raise EnterpriseIAMError("SCIM payload missing userName/email")

            user_id = (
                scim_payload.get("externalId")
                or f"usr_{hashlib.sha256(email.encode()).hexdigest()[:12]}"
            )
            full_name = scim_payload.get("displayName") or email.split("@")[0]

            user = self.org_manager.provision_user(
                user_id=user_id, email=email, full_name=full_name
            )

            # Add member to org with default or mapped role
            role_str = scim_payload.get("role", MembershipRole.DEVELOPER)
            try:
                role = MembershipRole(role_str)
            except ValueError:
                role = MembershipRole.DEVELOPER

            dept_id = scim_payload.get("departmentId")
            self.org_manager.add_member(
                org_id=org_id, user_id=user_id, role=role, department_id=dept_id
            )
            logger.info("SCIM provisioned user %s in org %s (role=%s)", user_id, org_id, role)
            return user

    def scim_deprovision_user(self, org_id: str, user_id: str) -> None:
        """Deprovision a user via SCIM 2.0: deactivate account and revoke all active sessions."""
        with self._lock:
            user = self.org_manager.get_user(user_id)
            user.is_active = False

            # Deactivate membership
            membership = self.org_manager.get_membership(org_id, user_id)
            if membership:
                membership.is_active = False

            # Revoke all active sessions immediately
            revoked_count = self.revoke_user_sessions(user_id)
            logger.info(
                "SCIM deprovisioned user %s in org %s; deactivated membership and revoked %d sessions",
                user_id,
                org_id,
                revoked_count,
            )

    def scim_update_user(self, org_id: str, user_id: str, scim_payload: dict[str, Any]) -> User:
        """Update a user via SCIM 2.0 attributes."""
        with self._lock:
            user = self.org_manager.get_user(user_id)
            if "displayName" in scim_payload:
                user.full_name = scim_payload["displayName"]
            if "active" in scim_payload:
                is_active = bool(scim_payload["active"])
                user.is_active = is_active
                if not is_active:
                    self.revoke_user_sessions(user_id)

            if "role" in scim_payload:
                membership = self.org_manager.get_membership(org_id, user_id)
                if membership:
                    try:
                        membership.role = MembershipRole(scim_payload["role"])
                    except ValueError:
                        pass

            return user

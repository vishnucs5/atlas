"""Enterprise Persistent Storage Layer for ATLAS.

Provides durable SQLite and PostgreSQL persistence for enterprise entities:
- Organizations, Departments, Teams, Projects, Users, Memberships
- Active Sessions & Deprovisioned Tokens
- Cryptographically Scoped Service Identities
- Registered Autonomous Agents & Policy Envelopes
- Third-Party Connectors & Vaulted Secrets
- Chained Audit Records & Tamper Hashes
- Operational Cost Records & Department Budgets
"""

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_enterprise.models import (
    AgentLifecycleStatus,
    AuditRecord,
    ConnectorStatus,
    ConnectorType,
    CostRecord,
    Department,
    DepartmentBudget,
    EnterpriseAgentRecord,
    EnterprisePolicyEnvelope,
    GovernanceScopeType,
    IntegrationConnectorRecord,
    MembershipRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
    Project,
    ServiceIdentity,
    SessionToken,
    Team,
    User,
)

logger = logging.getLogger("atlas.enterprise.storage")

ENTERPRISE_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS enterprise_organizations (
    org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    retention_days INTEGER NOT NULL DEFAULT 90,
    max_concurrent_workers INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_departments (
    dept_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    lead_user_id TEXT,
    budget_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, slug)
);

CREATE TABLE IF NOT EXISTS enterprise_teams (
    team_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    lead_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, slug)
);

CREATE TABLE IF NOT EXISTS enterprise_projects (
    project_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT,
    team_id TEXT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, slug)
);

CREATE TABLE IF NOT EXISTS enterprise_users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    external_idp_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_memberships (
    membership_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    department_id TEXT,
    team_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS enterprise_sessions (
    token_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    role TEXT NOT NULL,
    department_id TEXT,
    client_ip TEXT,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    is_revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS enterprise_service_identities (
    service_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT,
    name TEXT NOT NULL,
    api_key_hash TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_agents (
    agent_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT,
    team_id TEXT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '1.0.0',
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    model_constraints TEXT NOT NULL DEFAULT '{}',
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    allowed_skills TEXT NOT NULL DEFAULT '[]',
    allowed_workflows TEXT NOT NULL DEFAULT '[]',
    resource_limits TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_policies (
    scope_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    disallowed_tools TEXT NOT NULL DEFAULT '[]',
    disallowed_skills TEXT NOT NULL DEFAULT '[]',
    disallowed_models TEXT NOT NULL DEFAULT '[]',
    require_approval_for_tools TEXT NOT NULL DEFAULT '[]',
    require_dual_custody INTEGER NOT NULL DEFAULT 0,
    max_cost_per_task_usd REAL NOT NULL DEFAULT 100.0,
    rules TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_connectors (
    connector_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT,
    name TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    secret_id TEXT NOT NULL,
    rate_limit_rpm INTEGER NOT NULL DEFAULT 60,
    verification_evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_vault_secrets (
    secret_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    encrypted_data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_audit_records (
    org_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    department_id TEXT,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    action TEXT NOT NULL,
    target_resource_id TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    PRIMARY KEY (org_id, sequence)
);

CREATE TABLE IF NOT EXISTS enterprise_cost_records (
    record_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT,
    task_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    compute_duration_ms INTEGER NOT NULL DEFAULT 0,
    model_cost_usd REAL NOT NULL DEFAULT 0.0,
    compute_cost_usd REAL NOT NULL DEFAULT 0.0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_department_budgets (
    budget_key TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    department_id TEXT NOT NULL,
    allocated_usd REAL NOT NULL DEFAULT 0.0,
    spent_usd REAL NOT NULL DEFAULT 0.0,
    alert_threshold_pct REAL NOT NULL DEFAULT 80.0,
    hard_cap_enabled INTEGER NOT NULL DEFAULT 1,
    currency TEXT NOT NULL DEFAULT 'USD',
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, department_id)
);

CREATE INDEX IF NOT EXISTS idx_ent_depts_org ON enterprise_departments(org_id);
CREATE INDEX IF NOT EXISTS idx_ent_members_org ON enterprise_memberships(org_id);
CREATE INDEX IF NOT EXISTS idx_ent_members_user ON enterprise_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_ent_agents_org ON enterprise_agents(org_id);
CREATE INDEX IF NOT EXISTS idx_ent_connectors_org ON enterprise_connectors(org_id);
CREATE INDEX IF NOT EXISTS idx_ent_audit_org_seq ON enterprise_audit_records(org_id, sequence);
CREATE INDEX IF NOT EXISTS idx_ent_cost_org ON enterprise_cost_records(org_id);
"""


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val))


def _parse_json(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(str(val))
    except Exception:
        return {}


class EnterpriseStorage:
    """Thread-safe SQLite and PostgreSQL storage repository for ATLAS enterprise entities."""

    def __init__(self, db_path: str = ":memory:", postgres_url: str | None = None) -> None:
        self.db_path = db_path
        self.postgres_url = postgres_url
        self._lock = threading.RLock()
        self._mem_uri: str | None = None
        self._standing_conn: sqlite3.Connection | None = None

        if self.postgres_url:
            self._init_postgres()
        else:
            self._init_sqlite()

    # -------------------------------------------------------------------------
    # Database Initialization & Unified Execution
    # -------------------------------------------------------------------------

    def _init_sqlite(self) -> None:
        with self._lock:
            if self.db_path == ":memory:":
                self._mem_uri = f"file:mem_ent_{id(self)}?mode=memory&cache=shared"
                self._standing_conn = sqlite3.connect(
                    self._mem_uri, uri=True, check_same_thread=False
                )
                self._standing_conn.execute("PRAGMA journal_mode = WAL;")
                self._standing_conn.execute("PRAGMA foreign_keys = ON;")
                self._standing_conn.executescript(ENTERPRISE_SCHEMA_SQLITE)
                self._standing_conn.commit()
            else:
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.executescript(ENTERPRISE_SCHEMA_SQLITE)
                conn.commit()
                conn.close()

    def _init_postgres(self) -> None:
        import psycopg

        pg_ddl = ENTERPRISE_SCHEMA_SQLITE.replace("REAL", "DOUBLE PRECISION")
        with psycopg.connect(self.postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute(pg_ddl)
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_uri:
            conn = sqlite3.connect(self._mem_uri, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _execute(self, query: str, params: tuple = ()) -> None:
        if self.postgres_url:
            import psycopg

            pg_query = query.replace("?", "%s")
            with psycopg.connect(self.postgres_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(pg_query, params)
                conn.commit()
        else:
            conn = self._get_connection()
            try:
                conn.execute(query, params)
                conn.commit()
            finally:
                conn.close()

    def _fetchone(self, query: str, params: tuple = ()) -> dict[str, Any] | None:
        if self.postgres_url:
            import psycopg
            from psycopg.rows import dict_row

            pg_query = query.replace("?", "%s")
            with psycopg.connect(self.postgres_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(pg_query, params)
                    row = cur.fetchone()
                    return dict(row) if row else None
        else:
            conn = self._get_connection()
            try:
                row = conn.execute(query, params).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def _fetchall(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        if self.postgres_url:
            import psycopg
            from psycopg.rows import dict_row

            pg_query = query.replace("?", "%s")
            with psycopg.connect(self.postgres_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(pg_query, params)
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
        else:
            conn = self._get_connection()
            try:
                rows = conn.execute(query, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # Organizations
    # -------------------------------------------------------------------------

    def save_organization(self, org: Organization) -> None:
        with self._lock:
            created_str = org.created_at.isoformat()
            updated_str = getattr(org, "updated_at", org.created_at).isoformat()
            self._execute(
                """
                INSERT INTO enterprise_organizations (
                    org_id, name, slug, status, settings, retention_days, max_concurrent_workers, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    settings=excluded.settings,
                    retention_days=excluded.retention_days,
                    max_concurrent_workers=excluded.max_concurrent_workers,
                    updated_at=excluded.updated_at
                """,
                (
                    org.org_id,
                    org.name,
                    org.slug,
                    org.status.value if hasattr(org.status, "value") else str(org.status),
                    json.dumps(org.settings),
                    org.retention_days,
                    org.max_concurrent_workers,
                    created_str,
                    updated_str,
                ),
            )

    def get_organization(self, org_id: str) -> Organization | None:
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM enterprise_organizations WHERE org_id = ?", (org_id,)
            )
            if not row:
                return None
            return Organization(
                org_id=row["org_id"],
                name=row["name"],
                slug=row["slug"],
                status=OrganizationStatus(row["status"]),
                settings=_parse_json(row["settings"]),
                retention_days=row["retention_days"],
                max_concurrent_workers=row["max_concurrent_workers"],
                created_at=_parse_dt(row["created_at"]),
            )

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        with self._lock:
            row = self._fetchone("SELECT * FROM enterprise_organizations WHERE slug = ?", (slug,))
            if not row:
                return None
            return Organization(
                org_id=row["org_id"],
                name=row["name"],
                slug=row["slug"],
                status=OrganizationStatus(row["status"]),
                settings=_parse_json(row["settings"]),
                retention_days=row["retention_days"],
                max_concurrent_workers=row["max_concurrent_workers"],
                created_at=_parse_dt(row["created_at"]),
            )

    def list_organizations(self) -> list[Organization]:
        with self._lock:
            rows = self._fetchall("SELECT * FROM enterprise_organizations ORDER BY created_at ASC")
            return [
                Organization(
                    org_id=r["org_id"],
                    name=r["name"],
                    slug=r["slug"],
                    status=OrganizationStatus(r["status"]),
                    settings=_parse_json(r["settings"]),
                    retention_days=r["retention_days"],
                    max_concurrent_workers=r["max_concurrent_workers"],
                    created_at=_parse_dt(r["created_at"]),
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Departments, Teams, Projects
    # -------------------------------------------------------------------------

    def save_department(self, dept: Department) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO enterprise_departments (
                    dept_id, org_id, name, slug, lead_user_id, budget_usd, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dept_id) DO UPDATE SET
                    name=excluded.name,
                    lead_user_id=excluded.lead_user_id,
                    budget_usd=excluded.budget_usd,
                    updated_at=excluded.updated_at
                """,
                (
                    dept.department_id,
                    dept.org_id,
                    dept.name,
                    dept.slug,
                    dept.lead_user_id,
                    dept.budget_usd,
                    dept.created_at.isoformat(),
                    dept.updated_at.isoformat(),
                ),
            )

    def list_departments(self, org_id: str) -> list[Department]:
        with self._lock:
            rows = self._fetchall(
                "SELECT * FROM enterprise_departments WHERE org_id = ? ORDER BY name ASC",
                (org_id,),
            )
            return [
                Department(
                    department_id=r["dept_id"],
                    org_id=r["org_id"],
                    name=r["name"],
                    slug=r["slug"],
                    lead_user_id=r["lead_user_id"],
                    budget_usd=r["budget_usd"],
                    created_at=_parse_dt(r["created_at"]),
                    updated_at=_parse_dt(r["updated_at"]),
                )
                for r in rows
            ]

    def save_team(self, team: Team) -> None:
        with self._lock:
            slug = getattr(team, "slug", team.name.lower().replace(" ", "-"))
            lead_id = getattr(team, "lead_user_id", None)
            self._execute(
                """
                INSERT INTO enterprise_teams (
                    team_id, org_id, department_id, name, slug, lead_user_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO UPDATE SET
                    name=excluded.name,
                    lead_user_id=excluded.lead_user_id,
                    updated_at=excluded.updated_at
                """,
                (
                    team.team_id,
                    team.org_id,
                    team.department_id,
                    team.name,
                    slug,
                    lead_id,
                    team.created_at.isoformat(),
                    team.updated_at.isoformat(),
                ),
            )

    def save_project(self, project: Project) -> None:
        with self._lock:
            slug = getattr(project, "slug", project.name.lower().replace(" ", "-"))
            self._execute(
                """
                INSERT INTO enterprise_projects (
                    project_id, org_id, department_id, team_id, name, slug, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    project.project_id,
                    project.org_id,
                    project.department_id,
                    project.team_id,
                    project.name,
                    slug,
                    project.status,
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                ),
            )

    # -------------------------------------------------------------------------
    # Users & Memberships
    # -------------------------------------------------------------------------

    def save_user(self, user: User) -> None:
        with self._lock:
            ext_idp = getattr(user, "external_idp_id", None)
            created_str = user.created_at.isoformat()
            updated_str = getattr(user, "updated_at", user.created_at).isoformat()
            self._execute(
                """
                INSERT INTO enterprise_users (
                    user_id, email, full_name, is_active, external_idp_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email=excluded.email,
                    full_name=excluded.full_name,
                    is_active=excluded.is_active,
                    external_idp_id=excluded.external_idp_id,
                    updated_at=excluded.updated_at
                """,
                (
                    user.user_id,
                    user.email,
                    user.full_name,
                    1 if user.is_active else 0,
                    ext_idp,
                    created_str,
                    updated_str,
                ),
            )

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            row = self._fetchone("SELECT * FROM enterprise_users WHERE user_id = ?", (user_id,))
            if not row:
                return None
            return User(
                user_id=row["user_id"],
                email=row["email"],
                full_name=row["full_name"],
                is_active=bool(row["is_active"]),
                created_at=_parse_dt(row["created_at"]),
            )

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock:
            row = self._fetchone("SELECT * FROM enterprise_users WHERE email = ?", (email,))
            if not row:
                return None
            return User(
                user_id=row["user_id"],
                email=row["email"],
                full_name=row["full_name"],
                is_active=bool(row["is_active"]),
                created_at=_parse_dt(row["created_at"]),
            )

    def save_membership(self, mem: OrganizationMembership) -> None:
        with self._lock:
            team_id = getattr(mem, "team_id", None)
            assigned_str = mem.assigned_at.isoformat()
            self._execute(
                """
                INSERT INTO enterprise_memberships (
                    membership_id, org_id, user_id, role, department_id, team_id, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, user_id) DO UPDATE SET
                    role=excluded.role,
                    department_id=excluded.department_id,
                    team_id=excluded.team_id,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
                """,
                (
                    mem.membership_id,
                    mem.org_id,
                    mem.user_id,
                    mem.role.value if hasattr(mem.role, "value") else str(mem.role),
                    mem.department_id,
                    team_id,
                    1 if mem.is_active else 0,
                    assigned_str,
                    assigned_str,
                ),
            )

    def get_membership(self, org_id: str, user_id: str) -> OrganizationMembership | None:
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM enterprise_memberships WHERE org_id = ? AND user_id = ?",
                (org_id, user_id),
            )
            if not row:
                return None
            return OrganizationMembership(
                membership_id=row["membership_id"],
                org_id=row["org_id"],
                user_id=row["user_id"],
                role=MembershipRole(row["role"]),
                department_id=row["department_id"],
                is_active=bool(row["is_active"]),
                assigned_at=_parse_dt(row["created_at"]),
            )

    def list_memberships(self, org_id: str) -> list[OrganizationMembership]:
        with self._lock:
            rows = self._fetchall(
                "SELECT * FROM enterprise_memberships WHERE org_id = ?", (org_id,)
            )
            return [
                OrganizationMembership(
                    membership_id=r["membership_id"],
                    org_id=r["org_id"],
                    user_id=r["user_id"],
                    role=MembershipRole(r["role"]),
                    department_id=r["department_id"],
                    is_active=bool(r["is_active"]),
                    assigned_at=_parse_dt(r["created_at"]),
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Sessions & Service Identities
    # -------------------------------------------------------------------------

    def save_session(self, session: SessionToken) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO enterprise_sessions (
                    token_id, user_id, org_id, role, department_id, client_ip, issued_at, expires_at, is_revoked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    is_revoked=excluded.is_revoked
                """,
                (
                    session.token_id,
                    session.user_id,
                    session.org_id,
                    session.role.value if hasattr(session.role, "value") else str(session.role),
                    session.department_id,
                    session.client_ip,
                    session.issued_at.isoformat(),
                    session.expires_at.isoformat(),
                    1 if session.is_revoked else 0,
                ),
            )

    def get_session(self, token_id: str) -> SessionToken | None:
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM enterprise_sessions WHERE token_id = ?", (token_id,)
            )
            if not row:
                return None
            return SessionToken(
                token_id=row["token_id"],
                user_id=row["user_id"],
                org_id=row["org_id"],
                role=MembershipRole(row["role"]),
                department_id=row["department_id"],
                client_ip=row["client_ip"],
                issued_at=_parse_dt(row["issued_at"]),
                expires_at=_parse_dt(row["expires_at"]),
                is_revoked=bool(row["is_revoked"]),
            )

    def save_service_identity(self, svc: ServiceIdentity) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO enterprise_service_identities (
                    service_id, org_id, department_id, name, api_key_hash, scopes, is_active, created_at, expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET
                    name=excluded.name,
                    api_key_hash=excluded.api_key_hash,
                    scopes=excluded.scopes,
                    is_active=excluded.is_active,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                """,
                (
                    svc.service_id,
                    svc.org_id,
                    svc.department_id,
                    svc.name,
                    svc.api_key_hash,
                    json.dumps(svc.scopes),
                    1 if svc.is_active else 0,
                    svc.created_at.isoformat(),
                    svc.expires_at.isoformat() if svc.expires_at else None,
                    svc.updated_at.isoformat(),
                ),
            )

    def get_service_identity_by_hash(self, api_key_hash: str) -> ServiceIdentity | None:
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM enterprise_service_identities WHERE api_key_hash = ?",
                (api_key_hash,),
            )
            if not row:
                return None
            return ServiceIdentity(
                service_id=row["service_id"],
                org_id=row["org_id"],
                department_id=row["department_id"],
                name=row["name"],
                api_key_hash=row["api_key_hash"],
                scopes=_parse_json(row["scopes"]),
                is_active=bool(row["is_active"]),
                created_at=_parse_dt(row["created_at"]),
                expires_at=_parse_dt(row["expires_at"]) if row["expires_at"] else None,
                updated_at=_parse_dt(row["updated_at"]),
            )

    # -------------------------------------------------------------------------
    # Autonomous Agents & Policies
    # -------------------------------------------------------------------------

    def save_agent(self, agent: EnterpriseAgentRecord) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO enterprise_agents (
                    agent_id, org_id, department_id, team_id, name, description, version,
                    owner_user_id, status, model_constraints, allowed_tools, allowed_skills,
                    allowed_workflows, resource_limits, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    version=excluded.version,
                    status=excluded.status,
                    model_constraints=excluded.model_constraints,
                    allowed_tools=excluded.allowed_tools,
                    allowed_skills=excluded.allowed_skills,
                    allowed_workflows=excluded.allowed_workflows,
                    resource_limits=excluded.resource_limits,
                    updated_at=excluded.updated_at
                """,
                (
                    agent.agent_id,
                    agent.org_id,
                    agent.department_id,
                    agent.team_id,
                    agent.name,
                    agent.description,
                    agent.version,
                    agent.owner_user_id,
                    agent.status.value if hasattr(agent.status, "value") else str(agent.status),
                    json.dumps(agent.model_constraints),
                    json.dumps(agent.allowed_tools),
                    json.dumps(agent.allowed_skills),
                    json.dumps(agent.allowed_workflows),
                    json.dumps(agent.resource_limits),
                    agent.created_at.isoformat(),
                    agent.updated_at.isoformat(),
                ),
            )

    def get_agent(self, agent_id: str) -> EnterpriseAgentRecord | None:
        with self._lock:
            row = self._fetchone("SELECT * FROM enterprise_agents WHERE agent_id = ?", (agent_id,))
            if not row:
                return None
            return EnterpriseAgentRecord(
                agent_id=row["agent_id"],
                org_id=row["org_id"],
                department_id=row["department_id"],
                team_id=row["team_id"],
                name=row["name"],
                description=row["description"],
                version=row["version"],
                owner_user_id=row["owner_user_id"],
                status=AgentLifecycleStatus(row["status"]),
                model_constraints=_parse_json(row["model_constraints"]),
                allowed_tools=_parse_json(row["allowed_tools"]),
                allowed_skills=_parse_json(row["allowed_skills"]),
                allowed_workflows=_parse_json(row["allowed_workflows"]),
                resource_limits=_parse_json(row["resource_limits"]),
                created_at=_parse_dt(row["created_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )

    def list_agents(self, org_id: str) -> list[EnterpriseAgentRecord]:
        with self._lock:
            rows = self._fetchall(
                "SELECT * FROM enterprise_agents WHERE org_id = ? ORDER BY name ASC",
                (org_id,),
            )
            return [
                EnterpriseAgentRecord(
                    agent_id=r["agent_id"],
                    org_id=r["org_id"],
                    department_id=r["department_id"],
                    team_id=r["team_id"],
                    name=r["name"],
                    description=r["description"],
                    version=r["version"],
                    owner_user_id=r["owner_user_id"],
                    status=AgentLifecycleStatus(r["status"]),
                    model_constraints=_parse_json(r["model_constraints"]),
                    allowed_tools=_parse_json(r["allowed_tools"]),
                    allowed_skills=_parse_json(r["allowed_skills"]),
                    allowed_workflows=_parse_json(r["allowed_workflows"]),
                    resource_limits=_parse_json(r["resource_limits"]),
                    created_at=_parse_dt(r["created_at"]),
                    updated_at=_parse_dt(r["updated_at"]),
                )
                for r in rows
            ]

    def save_policy(self, envelope: EnterprisePolicyEnvelope) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO enterprise_policies (
                    scope_id, policy_id, org_id, scope_type, disallowed_tools, disallowed_skills,
                    disallowed_models, require_approval_for_tools, require_dual_custody,
                    max_cost_per_task_usd, rules, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    policy_id=excluded.policy_id,
                    disallowed_tools=excluded.disallowed_tools,
                    disallowed_skills=excluded.disallowed_skills,
                    disallowed_models=excluded.disallowed_models,
                    require_approval_for_tools=excluded.require_approval_for_tools,
                    require_dual_custody=excluded.require_dual_custody,
                    max_cost_per_task_usd=excluded.max_cost_per_task_usd,
                    rules=excluded.rules,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
                """,
                (
                    envelope.scope_id,
                    envelope.policy_id,
                    envelope.org_id,
                    envelope.scope_type.value
                    if hasattr(envelope.scope_type, "value")
                    else str(envelope.scope_type),
                    json.dumps(envelope.disallowed_tools),
                    json.dumps(envelope.disallowed_skills),
                    json.dumps(envelope.disallowed_models),
                    json.dumps(envelope.require_approval_for_tools),
                    1 if envelope.require_dual_custody else 0,
                    envelope.max_cost_per_task_usd,
                    json.dumps(envelope.rules),
                    1 if envelope.is_active else 0,
                    envelope.created_at.isoformat(),
                    envelope.updated_at.isoformat(),
                ),
            )

    def get_policy(self, scope_id: str) -> EnterprisePolicyEnvelope | None:
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM enterprise_policies WHERE scope_id = ?", (scope_id,)
            )
            if not row:
                return None
            return EnterprisePolicyEnvelope(
                policy_id=row["policy_id"],
                org_id=row["org_id"],
                scope_type=GovernanceScopeType(row["scope_type"]),
                scope_id=row["scope_id"],
                disallowed_tools=_parse_json(row["disallowed_tools"]),
                disallowed_skills=_parse_json(row["disallowed_skills"]),
                disallowed_models=_parse_json(row["disallowed_models"]),
                require_approval_for_tools=_parse_json(row["require_approval_for_tools"]),
                require_dual_custody=bool(row["require_dual_custody"]),
                max_cost_per_task_usd=row["max_cost_per_task_usd"],
                rules=_parse_json(row["rules"]),
                is_active=bool(row["is_active"]),
                created_at=_parse_dt(row["created_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )

    # -------------------------------------------------------------------------
    # Connectors & Vault Secrets
    # -------------------------------------------------------------------------

    def save_connector(self, connector: IntegrationConnectorRecord) -> None:
        with self._lock:
            ver_ev = getattr(connector, "verification_evidence", None)
            ver_ev_str = json.dumps(ver_ev) if ver_ev else None
            self._execute(
                """
                INSERT INTO enterprise_connectors (
                    connector_id, org_id, department_id, name, connector_type, provider,
                    status, config, secret_id, rate_limit_rpm, verification_evidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    config=excluded.config,
                    secret_id=excluded.secret_id,
                    rate_limit_rpm=excluded.rate_limit_rpm,
                    verification_evidence=excluded.verification_evidence,
                    updated_at=excluded.updated_at
                """,
                (
                    connector.connector_id,
                    connector.org_id,
                    connector.department_id,
                    connector.name,
                    connector.connector_type.value
                    if hasattr(connector.connector_type, "value")
                    else str(connector.connector_type),
                    connector.provider,
                    connector.status.value
                    if hasattr(connector.status, "value")
                    else str(connector.status),
                    json.dumps(connector.config),
                    connector.secret_id,
                    connector.rate_limit_rpm,
                    ver_ev_str,
                    connector.created_at.isoformat(),
                    connector.updated_at.isoformat(),
                ),
            )

    def get_connector(self, connector_id: str) -> IntegrationConnectorRecord | None:
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM enterprise_connectors WHERE connector_id = ?", (connector_id,)
            )
            if not row:
                return None
            return IntegrationConnectorRecord(
                connector_id=row["connector_id"],
                org_id=row["org_id"],
                department_id=row["department_id"],
                name=row["name"],
                connector_type=ConnectorType(row["connector_type"]),
                provider=row["provider"],
                status=ConnectorStatus(row["status"]),
                config=_parse_json(row["config"]),
                secret_id=row["secret_id"],
                rate_limit_rpm=row["rate_limit_rpm"],
                created_at=_parse_dt(row["created_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )

    def list_connectors(self, org_id: str | None = None) -> list[IntegrationConnectorRecord]:
        with self._lock:
            if org_id:
                rows = self._fetchall(
                    "SELECT * FROM enterprise_connectors WHERE org_id = ? ORDER BY name ASC",
                    (org_id,),
                )
            else:
                rows = self._fetchall("SELECT * FROM enterprise_connectors ORDER BY created_at ASC")
            return [
                IntegrationConnectorRecord(
                    connector_id=r["connector_id"],
                    org_id=r["org_id"],
                    department_id=r["department_id"],
                    name=r["name"],
                    connector_type=ConnectorType(r["connector_type"]),
                    provider=r["provider"],
                    status=ConnectorStatus(r["status"]),
                    config=_parse_json(r["config"]),
                    secret_id=r["secret_id"],
                    rate_limit_rpm=r["rate_limit_rpm"],
                    created_at=_parse_dt(r["created_at"]),
                    updated_at=_parse_dt(r["updated_at"]),
                )
                for r in rows
            ]

    def save_vault_secret(self, secret_id: str, org_id: str, encrypted_data: str) -> None:
        with self._lock:
            now = datetime.now(UTC).isoformat()
            self._execute(
                """
                INSERT INTO enterprise_vault_secrets (secret_id, org_id, encrypted_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(secret_id) DO UPDATE SET
                    encrypted_data=excluded.encrypted_data,
                    updated_at=excluded.updated_at
                """,
                (secret_id, org_id, encrypted_data, now, now),
            )

    def get_vault_secret(self, secret_id: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._fetchone(
                "SELECT org_id, encrypted_data FROM enterprise_vault_secrets WHERE secret_id = ?",
                (secret_id,),
            )
            if not row:
                return None
            return row["org_id"], row["encrypted_data"]

    # -------------------------------------------------------------------------
    # Audit Records & Cryptographic Chaining
    # -------------------------------------------------------------------------

    def save_audit_record(self, record: AuditRecord) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO enterprise_audit_records (
                    org_id, sequence, department_id, event_type, actor_id, actor_type,
                    action, target_resource_id, details, timestamp, record_hash, previous_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, sequence) DO UPDATE SET
                    record_hash=excluded.record_hash
                """,
                (
                    record.org_id,
                    record.sequence,
                    record.department_id,
                    record.event_type,
                    record.actor_id,
                    record.actor_type,
                    record.action,
                    record.target_resource_id,
                    json.dumps(record.details, default=str),
                    record.timestamp.isoformat(),
                    record.record_hash,
                    record.previous_hash,
                ),
            )

    def get_audit_records(
        self, org_id: str, limit: int = 100, offset: int = 0
    ) -> list[AuditRecord]:
        with self._lock:
            rows = self._fetchall(
                """
                SELECT * FROM enterprise_audit_records
                WHERE org_id = ?
                ORDER BY sequence ASC
                LIMIT ? OFFSET ?
                """,
                (org_id, limit, offset),
            )
            return [
                AuditRecord(
                    record_id=f"audit_{r['org_id']}_{r['sequence']}",
                    org_id=r["org_id"],
                    sequence=r["sequence"],
                    department_id=r["department_id"],
                    event_type=r["event_type"],
                    actor_id=r["actor_id"],
                    actor_type=r["actor_type"],
                    action=r["action"],
                    target_resource_id=r["target_resource_id"],
                    details=_parse_json(r["details"]),
                    timestamp=_parse_dt(r["timestamp"]),
                    record_hash=r["record_hash"],
                    previous_hash=r["previous_hash"],
                )
                for r in rows
            ]

    def get_latest_audit_record(self, org_id: str) -> AuditRecord | None:
        with self._lock:
            row = self._fetchone(
                """
                SELECT * FROM enterprise_audit_records
                WHERE org_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (org_id,),
            )
            if not row:
                return None
            return AuditRecord(
                record_id=f"audit_{row['org_id']}_{row['sequence']}",
                org_id=row["org_id"],
                sequence=row["sequence"],
                department_id=row["department_id"],
                event_type=row["event_type"],
                actor_id=row["actor_id"],
                actor_type=row["actor_type"],
                action=row["action"],
                target_resource_id=row["target_resource_id"],
                details=_parse_json(row["details"]),
                timestamp=_parse_dt(row["timestamp"]),
                record_hash=row["record_hash"],
                previous_hash=row["previous_hash"],
            )

    # -------------------------------------------------------------------------
    # Costs & Department Budgets
    # -------------------------------------------------------------------------

    def save_cost_record(self, record: CostRecord) -> None:
        with self._lock:
            rec_at = getattr(record, "recorded_at", record.created_at).isoformat()
            self._execute(
                """
                INSERT INTO enterprise_cost_records (
                    record_id, org_id, department_id, task_id, model_name, prompt_tokens,
                    completion_tokens, compute_duration_ms, model_cost_usd, compute_cost_usd,
                    total_cost_usd, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO NOTHING
                """,
                (
                    record.record_id,
                    record.org_id,
                    record.department_id,
                    record.task_id,
                    record.model_name,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.compute_duration_ms,
                    getattr(record, "token_cost_usd", 0.0),
                    getattr(record, "compute_cost_usd", 0.0),
                    record.total_cost_usd,
                    rec_at,
                ),
            )

    def get_cost_records(self, org_id: str, department_id: str | None = None) -> list[CostRecord]:
        with self._lock:
            if department_id:
                rows = self._fetchall(
                    """
                    SELECT * FROM enterprise_cost_records
                    WHERE org_id = ? AND department_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (org_id, department_id),
                )
            else:
                rows = self._fetchall(
                    """
                    SELECT * FROM enterprise_cost_records
                    WHERE org_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (org_id,),
                )
            return [
                CostRecord(
                    record_id=r["record_id"],
                    org_id=r["org_id"],
                    department_id=r["department_id"],
                    task_id=r["task_id"],
                    model_name=r["model_name"],
                    prompt_tokens=r["prompt_tokens"],
                    completion_tokens=r["completion_tokens"],
                    total_tokens=r["prompt_tokens"] + r["completion_tokens"],
                    compute_duration_ms=r["compute_duration_ms"],
                    token_cost_usd=r["model_cost_usd"],
                    compute_cost_usd=r["compute_cost_usd"],
                    total_cost_usd=r["total_cost_usd"],
                    recorded_at=_parse_dt(r["timestamp"]),
                )
                for r in rows
            ]

    def save_budget(self, budget: DepartmentBudget) -> None:
        with self._lock:
            key = f"{budget.org_id}:{budget.department_id}"
            now = datetime.now(UTC).isoformat()
            self._execute(
                """
                INSERT INTO enterprise_department_budgets (
                    budget_key, org_id, department_id, allocated_usd, spent_usd,
                    alert_threshold_pct, hard_cap_enabled, currency, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, department_id) DO UPDATE SET
                    allocated_usd=excluded.allocated_usd,
                    spent_usd=excluded.spent_usd,
                    alert_threshold_pct=excluded.alert_threshold_pct,
                    hard_cap_enabled=excluded.hard_cap_enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    budget.org_id,
                    budget.department_id,
                    budget.allocated_usd,
                    budget.spent_usd,
                    budget.alert_threshold_pct,
                    1 if budget.hard_cap_enabled else 0,
                    getattr(budget, "currency", "USD"),
                    now,
                ),
            )

    def get_budget(self, org_id: str, department_id: str) -> DepartmentBudget | None:
        with self._lock:
            row = self._fetchone(
                """
                SELECT * FROM enterprise_department_budgets
                WHERE org_id = ? AND department_id = ?
                """,
                (org_id, department_id),
            )
            if not row:
                return None
            return DepartmentBudget(
                budget_id=f"bgt_{row['org_id']}_{row['department_id']}",
                org_id=row["org_id"],
                department_id=row["department_id"],
                allocated_usd=row["allocated_usd"],
                spent_usd=row["spent_usd"],
                alert_threshold_pct=row["alert_threshold_pct"],
                hard_cap_enabled=bool(row["hard_cap_enabled"]),
            )

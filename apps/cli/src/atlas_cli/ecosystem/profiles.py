"""Workspace profiles for project-specific tool suites, languages, and strict privilege limits."""

import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PrivilegeBoundaryViolationError(Exception):
    """Raised when a workspace profile attempts to grant privileges beyond user permissions."""


class WorkspaceProfile(BaseModel):
    """Configuration profile tailoring tools, test runners, and context policies to a project type."""

    model_config = ConfigDict(validate_assignment=True)

    profile_id: str
    name: str
    description: str = ""
    relevant_tools: list[str] = Field(default_factory=list)
    test_command: str = "pytest"
    format_command: str = "ruff format ."
    lint_command: str = "ruff check ."
    language_support: list[str] = Field(default_factory=list)
    model_preference: str = "hermetic-default"
    max_context_tokens: int = 8000
    max_parallel_workers: int = 4
    privilege_ceiling: str = "STANDARD_USER"


class WorkspaceProfileManager:
    """Manages workspace profiles and strictly enforces that profiles do not elevate user permissions."""

    BUILTIN_PROFILES: dict[str, WorkspaceProfile] = {
        "python-dev": WorkspaceProfile(
            profile_id="python-dev",
            name="Python Development",
            description="Optimized for Python development with pytest and ruff.",
            relevant_tools=["file.read", "file.write", "terminal.execute", "test.run"],
            test_command="uv run pytest -q",
            format_command="uv run ruff format .",
            lint_command="uv run ruff check .",
            language_support=["python"],
            max_context_tokens=8000,
            max_parallel_workers=4,
        ),
        "typescript-dev": WorkspaceProfile(
            profile_id="typescript-dev",
            name="TypeScript Development",
            description="Tailored for TypeScript, React, Node.js with npm/jest and prettier.",
            relevant_tools=["file.read", "file.write", "terminal.execute", "test.run"],
            test_command="npm test",
            format_command="npx prettier --write .",
            lint_command="npx eslint .",
            language_support=["typescript", "javascript"],
            max_context_tokens=8000,
            max_parallel_workers=4,
        ),
        "java-backend": WorkspaceProfile(
            profile_id="java-backend",
            name="Java Backend Development",
            description="Optimized for Java, Spring Boot, Maven with JUnit test runners.",
            relevant_tools=["file.read", "file.write", "terminal.execute", "test.run"],
            test_command="mvn test",
            format_command="mvn spotless:apply",
            lint_command="mvn checkstyle:check",
            language_support=["java"],
            max_context_tokens=8000,
            max_parallel_workers=4,
        ),
        "machine-learning": WorkspaceProfile(
            profile_id="machine-learning",
            name="Machine Learning & Data Science",
            description="High-context token budget with data analysis and Jupyter support.",
            relevant_tools=["file.read", "file.write", "terminal.execute", "data.analyze"],
            test_command="pytest",
            format_command="ruff format .",
            lint_command="ruff check .",
            language_support=["python"],
            max_context_tokens=16000,
            max_parallel_workers=2,
        ),
        "infrastructure": WorkspaceProfile(
            profile_id="infrastructure",
            name="Infrastructure & DevOps",
            description="Docker, Kubernetes, and CI/CD automation profile.",
            relevant_tools=["file.read", "file.write", "terminal.execute"],
            test_command="docker build .",
            format_command="terraform fmt",
            lint_command="hadolint Dockerfile",
            language_support=["dockerfile", "yaml", "terraform"],
            max_context_tokens=8000,
            max_parallel_workers=2,
        ),
        "security-review": WorkspaceProfile(
            profile_id="security-review",
            name="Security Review & Audit",
            description="Focused on vulnerability analysis, secret detection, and policy auditing.",
            relevant_tools=["file.read", "security.audit", "policy.evaluate"],
            test_command="pip-audit",
            format_command="ruff format --check .",
            lint_command="ruff check .",
            language_support=["python", "typescript", "go", "rust"],
            max_context_tokens=6000,
            max_parallel_workers=2,
        ),
    }

    def __init__(self, current_profile_id: str = "python-dev") -> None:
        self._lock = threading.RLock()
        self.profiles: dict[str, WorkspaceProfile] = dict(self.BUILTIN_PROFILES)
        self.active_profile: WorkspaceProfile = self.profiles[current_profile_id]

    def get_profile(self, profile_id: str) -> WorkspaceProfile:
        """Retrieve profile by ID."""
        with self._lock:
            if profile_id not in self.profiles:
                msg = f"Workspace profile '{profile_id}' not found."
                raise KeyError(msg)
            return self.profiles[profile_id]

    def list_profiles(self) -> list[WorkspaceProfile]:
        """List all available profiles."""
        with self._lock:
            return list(self.profiles.values())

    def switch_profile(
        self,
        profile_id: str,
        authenticated_user_role: str = "MEMBER",
    ) -> WorkspaceProfile:
        """Switch active profile with privilege boundary enforcement."""
        with self._lock:
            target = self.get_profile(profile_id)
            self.verify_privilege_boundary(target, authenticated_user_role)
            self.active_profile = target
            return target

    def detect_profile(self, repo_root: Path | str) -> WorkspaceProfile:
        """Auto-detect appropriate profile based on repository manifest files."""
        root = Path(repo_root)
        if (root / "package.json").is_file() or (root / "tsconfig.json").is_file():
            return self.profiles["typescript-dev"]
        if (root / "pom.xml").is_file() or (root / "build.gradle").is_file():
            return self.profiles["java-backend"]
        if (root / "Dockerfile").is_file() and not (root / "pyproject.toml").is_file():
            return self.profiles["infrastructure"]
        # Default to python-dev
        return self.profiles["python-dev"]

    def set_active_profile(
        self,
        profile_id: str,
        authenticated_user_role: str = "MEMBER",
    ) -> WorkspaceProfile:
        """Set active profile by identifier."""
        return self.switch_profile(profile_id, authenticated_user_role)

    def detect_profile_for_workspace(self, repo_root: Path | str) -> WorkspaceProfile:
        """Alias for auto-detecting profile based on repo root."""
        return self.detect_profile(repo_root)

    def verify_privilege_boundary(
        self,
        profile: WorkspaceProfile | str | None = None,
        user_role: str | None = None,
        requested_ceiling: str | None = None,
        user_ceiling: str | None = None,
    ) -> bool:
        """Assert profile privilege ceiling does not exceed user's authenticated role."""
        req = requested_ceiling or (
            profile.privilege_ceiling
            if isinstance(profile, WorkspaceProfile)
            else (profile or "STANDARD_USER")
        )
        user = user_ceiling or user_role or "STANDARD_USER"

        hierarchy = {
            "ROOT_ADMIN": 4,
            "ADMIN_ELEVATED": 3,
            "STANDARD_USER": 2,
            "RESTRICTED": 1,
            "OWNER": 4,
            "ADMIN": 3,
            "MEMBER": 2,
            "VIEWER": 1,
        }
        req_rank = hierarchy.get(str(req).upper(), 2)
        user_rank = hierarchy.get(str(user).upper(), 2)

        if req_rank > user_rank:
            raise PrivilegeBoundaryViolationError(
                f"Requested ceiling '{req}' exceeds authenticated user ceiling '{user}'. "
                "Workspace profiles cannot elevate user permissions."
            )
        return True

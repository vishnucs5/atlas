"""Header and welcome presentation for ATLAS conversation-first terminal."""

from __future__ import annotations

import os
from pathlib import Path

from atlas_coding.explorer import RepositoryExplorer
from atlas_coding.git import GitPorcelain

from atlas_cli.adapters.client import AtlasClient

VERSION = "0.16.8"


class ConversationHeader:
    """Renders compact status header and welcome screen for conversation mode."""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        client: AtlasClient | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or os.getcwd()).resolve()
        self.client = client or AtlasClient()
        self.explorer = RepositoryExplorer(repo_root=self.repo_root)
        self.git = GitPorcelain(explorer=self.explorer)

    def get_git_branch(self) -> str:
        """Retrieve current git branch safely."""
        try:
            return self.git.get_current_branch() or "main"
        except Exception:
            return "detached"

    def get_model_identifier(self) -> str:
        """Retrieve configured or active model identifier."""
        try:
            from atlas_cli.configuration.manager import ConfigManager

            cfg = ConfigManager()
            model = cfg.get("default_model", "openrouter/free")
            provider = cfg.get("provider", "local")
            if provider == "anthropic":
                return f"{model} (Claude-compatible)"
            elif provider == "openai":
                return f"{model} (OpenAI-compatible)"
            elif provider == "gemini":
                return f"{model} (Gemini-compatible)"
            return model
        except Exception:
            return "openrouter/free"

    def get_execution_mode(self) -> str:
        """Determine whether execution is Local or Remote."""
        try:
            health = self.client.get_server_health()
            if health.get("status") in ("ok", "healthy"):
                return "Remote Control Plane"
        except Exception:
            pass
        return "Local"

    def render_header(self, session_id: str | None = None) -> str:
        """Generate compact 2-line header with Aegis emblem."""
        from atlas_cli.conversation.branding import AegisBranding

        branding = AegisBranding()
        branch = self.get_git_branch()
        model = self.get_model_identifier()
        mode = self.get_execution_mode()

        return branding.render_compact_header(
            repo_path=str(self.repo_root),
            branch=branch,
            model=model,
            mode=mode,
            session_id=session_id,
        )

    def render_welcome(self) -> str:
        """Generate full Aegis welcome screen matching the visual identity."""
        from atlas_cli.conversation.branding import AegisBranding

        branding = AegisBranding()
        branch = self.get_git_branch()
        model = self.get_model_identifier()
        mode = self.get_execution_mode()

        return branding.render_welcome_screen(
            repo_path=str(self.repo_root),
            branch=branch,
            model=model,
            mode=mode,
            status="Ready",
        )

"""Main Conversation-First Terminal Application for ATLAS CLI."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from atlas_coding.engine import CodingEngine
from atlas_models.router import PaidRoutingBlockedError

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.conversation.composer import PromptComposer, SlashCommandDispatcher
from atlas_cli.conversation.header import ConversationHeader
from atlas_cli.conversation.inspector import AdvancedInspector
from atlas_cli.conversation.renderer import (
    ConversationRenderer,
    stream_markdown,
)
from atlas_cli.events.stream import EventStreamSubscriber
from atlas_cli.rendering.formatters import (
    BOLD,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    colorize,
    render_diff,
)
from atlas_cli.sessions.manager import SessionManager


class ConversationApp:
    """Claude Code-inspired, conversation-first terminal application."""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        client: AtlasClient | None = None,
        session_id: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or os.getcwd()).resolve()
        self.client = client or AtlasClient()
        self.header = ConversationHeader(repo_root=self.repo_root, client=self.client)
        self.renderer = ConversationRenderer()
        self.composer = PromptComposer()
        self.dispatcher = SlashCommandDispatcher(app=self, repo_root=str(self.repo_root))
        self.sess_mgr = SessionManager()
        self.subscriber = EventStreamSubscriber()
        self.inspector = AdvancedInspector(
            client=self.client,
            repo_root=str(self.repo_root),
            subscriber=self.subscriber,
        )
        self.engine = CodingEngine(repo_root=self.repo_root)
        self._model_router = None

        if session_id:
            existing = self.sess_mgr.get_session(session_id)
            if existing:
                self.session = existing
            else:
                self.session = self.sess_mgr.create_session(objective="Interactive Conversation")
        else:
            self.session = self.sess_mgr.create_session(objective="Interactive Conversation")

        if "messages" not in self.session:
            self.session["messages"] = []

    def open_inspector(self) -> None:
        """Open the on-demand 8-panel diagnostic inspector."""
        self.inspector.show()
        # Reprint welcome upon returning to conversation
        os.system("cls" if os.name == "nt" else "clear")
        print(self.header.render_welcome())

    def compact_session(self) -> None:
        """Compact conversation messages to optimize context."""
        msg_count = len(self.session.get("messages", []))
        if msg_count > 6:
            # Retain first user goal and last 4 messages
            compacted = [self.session["messages"][0]] + self.session["messages"][-4:]
            self.session["messages"] = compacted
            self.sess_mgr.save_session(self.session["session_id"], self.session)
            print(
                colorize(
                    f"Compacted conversation from {msg_count} to {len(compacted)} messages.", GREEN
                )
            )
        else:
            print(colorize("Session history is already compact.", DIM))

    def handle_pending_approvals(self) -> bool:
        """Prompt user for any pending Action Firewall approvals adhering to Section 5.

        Returns True if turn can continue, False if operator cancelled or denied.
        """
        pending = self.client.list_approvals(status="PENDING")
        if not pending:
            return True

        for req in pending:
            print("\n" + self.renderer.render_approval_card(req))
            while True:
                try:
                    choice = input(f"{BOLD}Choice [A/D/V/C]: {RESET}").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print(colorize("\n[Cancelled] Approval denied by operator.", RED))
                    return False

                if choice in ("a", "approve", "yes", "y"):
                    req_id = req.get("request_id") or req.get("id", "")
                    self.client.grant_approval(req_id)
                    print(colorize("✓ Action authorized.", GREEN))
                    break
                elif choice in ("d", "deny", "no", "n"):
                    req_id = req.get("request_id") or req.get("id", "")
                    self.client.deny_approval(req_id)
                    print(colorize("✗ Action rejected by operator.", RED))
                    return False
                elif choice in ("v", "view", "diff"):
                    diff_text = self.engine.git.diff()
                    if diff_text:
                        print(render_diff(diff_text))
                    else:
                        print(colorize("  No filesystem diffs generated yet.", DIM))
                elif choice in ("c", "cancel"):
                    print(colorize("Turn cancelled by operator.", YELLOW))
                    return False
                else:
                    print(
                        colorize(
                            "Please choose: [A]pprove, [D]eny, [V]iew details, or [C]ancel.", YELLOW
                        )
                    )

        return True

    def _get_model_router(self):
        """Create the shared strict free-only router when a conversation first needs it."""
        if self._model_router is None:
            from atlas_agent.runtime import ProductionRuntime

            self._model_router = ProductionRuntime().router
        return self._model_router

    def execute_turn(self, prompt: str) -> None:
        """Send a conversational turn to the configured free model without fabricating task state."""
        from atlas_core.contracts.model import ModelMessage, ModelRequest

        from atlas_cli.conversation.branding import AegisBranding

        print(self.renderer.render_user_prompt(prompt))
        self.session["messages"].append({"role": "user", "content": prompt})
        router = self._get_model_router()
        messages = [
            ModelMessage(role=item["role"], content=item["content"])
            for item in self.session["messages"][-12:]
            if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str)
        ]
        request = ModelRequest(
            request_id=f"conv_{uuid.uuid4().hex}",
            task_id=f"conversation_{self.session['session_id']}",
            model_name="default",
            messages=messages,
            system_prompt=(
                "You are ATLAS. Answer the user directly and accurately. "
                "Do not claim that files, tests, or actions were completed unless the user sees "
                "a verified ATLAS action result."
            ),
            max_tokens=4096,
        )
        print(
            self.renderer.render_activity(
                "Requesting free model", router.default_free_model, status="RUNNING"
            )
        )
        try:
            response = asyncio.run(router.complete(request, fallback=False))
        except Exception as exc:
            cause = exc.__cause__ or exc
            cause_str = str(cause)
            if "AUTHENTICATION" in cause_str or "denied" in cause_str.lower():
                detail = "provider denied inference access"
            elif (
                "RATE_LIMIT" in cause_str or "429" in cause_str or "rate limit" in cause_str.lower()
            ):
                detail = "provider rate limit reached"
            elif "TIMEOUT" in cause_str or "timed out" in cause_str.lower():
                detail = "request timed out"
            elif "FreeModelPriceChangedError" in type(cause).__name__:
                detail = "model pricing changed from free"
            elif isinstance(exc, PaidRoutingBlockedError) and exc.__cause__:
                detail = f"provider error: {exc.__cause__}"
            elif isinstance(exc, PaidRoutingBlockedError):
                detail = str(exc)
            else:
                detail = type(exc).__name__
            print(
                self.renderer.render_activity("Free model request failed", detail, status="FAILED")
            )
            print(
                colorize(
                    "No task or filesystem action was performed. Check the selected provider's key and account restrictions.",
                    DIM,
                )
            )
            return

        print(
            self.renderer.render_activity(
                "Free model responded",
                response.model_name,
                status="SUCCESS",
                duration_ms=response.latency_ms,
            )
        )
        reply = response.content or "The provider returned no text response."
        if response.tool_calls:
            reply += "\n\nThe model proposed tools, but ATLAS did not execute any action in this conversation turn."
        print()
        print(AegisBranding().render_assistant_marker())
        stream_markdown(reply)
        self.session["messages"].append({"role": "assistant", "content": reply})
        self.sess_mgr.save_session(self.session["session_id"], self.session)

    def run(self) -> int:
        """Main interactive conversation loop."""
        # Update composer context for persistent bottom footer
        self.composer.update_context(
            repo_name=self.repo_root.name,
            branch=self.header.get_git_branch(),
            model=self.header.get_model_identifier(),
        )

        # Print welcome banner
        print(self.header.render_welcome())

        while True:
            prompt = self.composer.prompt()
            if prompt is None:
                # EOF / Ctrl+D
                print(colorize("\nExiting ATLAS. Goodbye!", DIM))
                return 0

            if not prompt.strip():
                continue

            # Check for slash commands
            if self.composer.is_slash_command(prompt):
                should_continue = self.dispatcher.dispatch(prompt)
                if not should_continue:
                    return 0
                continue

            # Execute conversational coding turn
            try:
                self.execute_turn(prompt)
            except KeyboardInterrupt:
                print(colorize("\n[Interrupt] Turn cancelled by operator.", YELLOW))
            except Exception as e:
                print(colorize(f"\n[Error] Turn failed: {e}", RED))


def run_conversation_app(
    repo_root: str | Path | None = None,
    session_id: str | None = None,
    client: AtlasClient | None = None,
) -> int:
    """Entry point to launch the conversation-first interface."""
    app = ConversationApp(repo_root=repo_root, session_id=session_id, client=client)
    return app.run()

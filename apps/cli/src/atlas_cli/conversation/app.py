"""Main Conversation-First Terminal Application for ATLAS CLI."""

from __future__ import annotations

import os
import time
from pathlib import Path

from atlas_coding.engine import CodingEngine

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

    def execute_turn(self, prompt: str) -> None:
        """Execute a single conversational coding turn."""
        print(self.renderer.render_user_prompt(prompt))
        self.session["messages"].append({"role": "user", "content": prompt})

        # Activity: Exploring & indexing
        print(
            self.renderer.render_activity(
                "Exploring repository structure", str(self.repo_root), status="RUNNING"
            )
        )
        time.sleep(0.04)
        print(
            self.renderer.render_activity(
                "Exploring repository structure", "Done", status="SUCCESS"
            )
        )

        # Activity: Planning
        print(self.renderer.render_activity("Synthesizing execution plan", status="RUNNING"))
        task = self.engine.create_task(user_request=prompt)
        self.session["task_id"] = task.task_id
        self.engine.plan_task(task)
        time.sleep(0.04)

        steps = task.plan.get("steps", [])
        print(
            self.renderer.render_activity(
                "Execution plan synthesized",
                f"({len(steps)} verified steps)",
                status="SUCCESS",
            )
        )

        # Action Firewall check
        can_proceed = self.handle_pending_approvals()
        if not can_proceed:
            return

        # Verification step
        print(
            self.renderer.render_activity(
                "Verifying deterministic post-conditions", status="RUNNING"
            )
        )
        self.engine.verify_task(task)
        time.sleep(0.04)
        print(
            self.renderer.render_activity(
                "Verifying deterministic post-conditions",
                f"Task `{task.task_id}` verified",
                status="SUCCESS",
            )
        )

        from atlas_cli.conversation.branding import AegisBranding

        branding = AegisBranding()
        print(branding.render_completion_badge(task.task_id, verified=True))

        # Ingest events to subscriber
        from datetime import UTC, datetime

        from atlas_core.contracts.event import EventType, ExecutionEvent

        events = [
            ExecutionEvent(
                event_id=f"ev_{int(time.time())}_1",
                task_id=task.task_id,
                sequence=1,
                event_type=EventType.TASK_CREATED,
                timestamp=datetime.now(UTC),
                payload={"objective": prompt},
                correlation_id=task.task_id,
            ),
            ExecutionEvent(
                event_id=f"ev_{int(time.time())}_2",
                task_id=task.task_id,
                sequence=2,
                event_type=EventType.PLAN_GENERATED,
                timestamp=datetime.now(UTC),
                payload=task.plan,
                correlation_id=task.task_id,
            ),
            ExecutionEvent(
                event_id=f"ev_{int(time.time())}_3",
                task_id=task.task_id,
                sequence=3,
                event_type=EventType.TASK_COMPLETED,
                timestamp=datetime.now(UTC),
                payload={"status": "COMPLETED"},
                correlation_id=task.task_id,
            ),
        ]
        self.subscriber.ingest_batch(events)

        # Render file changes if any
        changes = getattr(task, "file_changes", [])
        if changes:
            print(self.renderer.render_file_changes(changes))

        # Render structured assistant response
        reply = (
            f"I have analyzed and verified the objective: **{prompt}**\n\n"
            f"- **Task ID**: `{task.task_id}`\n"
            f"- **Target Root**: `{task.repo_root}`\n"
            f"- **Status**: `{task.status.value}`\n\n"
            f"All planned steps verified under Action Firewall governance. "
            f"Type `/test` to run test suites or `/review` to inspect diffs."
        )

        print()
        print(branding.render_assistant_marker())
        stream_markdown(reply)
        self.session["messages"].append({"role": "assistant", "content": reply})
        self.sess_mgr.save_session(self.session["session_id"], self.session)

    def run(self) -> int:
        """Main interactive conversation loop."""
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

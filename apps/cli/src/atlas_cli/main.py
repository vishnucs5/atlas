"""Main entrypoint for ATLAS Developer CLI."""

import argparse
import signal
import sys

from atlas_cli.commands.agents import (
    run_agents_inspect,
    run_agents_list,
    run_agents_run,
)
from atlas_cli.commands.approval import (
    run_approval_deny,
    run_approval_grant,
    run_approval_list,
)
from atlas_cli.commands.coding import (
    run_coding_task,
    run_debug,
    run_plan,
    run_review,
    run_test,
)
from atlas_cli.commands.doctor import run_doctor
from atlas_cli.commands.environment import run_environment_test_browser
from atlas_cli.commands.governance import (
    run_config_cmd,
    run_permissions,
    run_status,
)
from atlas_cli.commands.init import run_init
from atlas_cli.commands.models import (
    run_models_configure,
    run_models_list,
    run_models_use,
)
from atlas_cli.commands.runtime import (
    run_logs,
    run_server_status,
    run_workers_list,
)
from atlas_cli.commands.sessions_cmd import (
    run_sessions_export,
    run_sessions_list,
    run_sessions_resume,
)
from atlas_cli.commands.task import (
    run_task_cancel,
    run_task_create,
    run_task_inspect,
    run_task_list,
    run_task_pause,
    run_task_resume,
)
from atlas_cli.commands.tools_plugins import (
    run_edition_info,
    run_mcp_list,
    run_plugins_install,
    run_plugins_list,
    run_profiles_list,
    run_skills_list,
    run_tools_list,
)
from atlas_cli.commands.worker import run_worker_daemon
from atlas_cli.conversation.app import run_conversation_app
from atlas_cli.minimal.runner import run_minimal
from atlas_cli.rendering.formatters import render_banner


def create_parser() -> argparse.ArgumentParser:
    """Construct top-level CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="ATLAS - Autonomous Task & Lifecycle Automation System",
    )
    parser.add_argument(
        "--tui", action="store_true", help="Launch interactive Terminal User Interface (TUI)"
    )
    parser.add_argument(
        "--inspector", action="store_true", help="Launch on-demand diagnostic inspector"
    )
    parser.add_argument(
        "--minimal", action="store_true", help="Run in minimal headless scriptable mode"
    )
    parser.add_argument(
        "-p",
        "--prompt",
        dest="prompt",
        type=str,
        default=None,
        help="Execute an autonomous coding task with specified prompt",
    )
    parser.add_argument("--version", "-v", action="store_true", help="Display ATLAS CLI version")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: atlas run <objective>
    run_parser = subparsers.add_parser("run", help="Execute an autonomous coding task")
    run_parser.add_argument("objective", type=str, help="Coding task objective")

    # Command: atlas doctor
    subparsers.add_parser(
        "doctor",
        help="Run environment diagnostics and verify system health",
        description="Verify Python version, OS platform, and SQLite WAL capability.",
    )

    # Command: atlas status
    subparsers.add_parser(
        "status",
        help="Display comprehensive cluster and control plane status",
    )

    # Command: atlas permissions
    subparsers.add_parser(
        "permissions",
        help="Display Action Firewall security policies and boundary rules",
    )

    # Command: atlas approvals
    subparsers.add_parser(
        "approvals",
        help="Interactive Action Firewall approval review",
    )

    # Command: atlas config
    cfg_parser = subparsers.add_parser("config", help="View or set configuration options")
    cfg_parser.add_argument("key", nargs="?", default=None, help="Config key")
    cfg_parser.add_argument("val", nargs="?", default=None, help="Config value")

    # Command: atlas plan <goal>
    plan_parser = subparsers.add_parser("plan", help="Synthesize execution plan for a goal")
    plan_parser.add_argument("goal", type=str, help="Goal or objective to plan")

    # Command: atlas review [--diff]
    review_parser = subparsers.add_parser(
        "review", help="Review workspace code and Action Firewall safety"
    )
    review_parser.add_argument(
        "--diff", action="store_true", help="Display unified diff of working tree"
    )

    # Command: atlas debug
    subparsers.add_parser("debug", help="Run diagnostic debug loop on current workspace")

    # Command: atlas test
    subparsers.add_parser("test", help="Dispatch QA specialist to run deterministic test suite")

    # Command: atlas models (list, use, configure)
    models_parser = subparsers.add_parser("models", help="Model adapter management")
    models_sub = models_parser.add_subparsers(dest="models_command", help="Models subcommands")
    models_sub.add_parser("list", help="List registered and available model adapters")
    m_use = models_sub.add_parser("use", help="Switch default active model")
    m_use.add_argument("model_name", type=str, help="Model name or identifier (e.g. openai/gpt-4o)")
    models_sub.add_parser("configure", help="Configure model credentials and provider keys")

    # Command: atlas agents (list, inspect, run)
    agents_parser = subparsers.add_parser("agents", help="Specialist agent fleet management")
    agents_sub = agents_parser.add_subparsers(dest="agents_command", help="Agents subcommands")
    agents_sub.add_parser("list", help="List active autonomous specialist agents")
    ag_ins = agents_sub.add_parser("inspect", help="Inspect specialist agent capabilities")
    ag_ins.add_argument("agent", type=str, help="Agent identifier to inspect")
    ag_run = agents_sub.add_parser("run", help="Dispatch task directly to specialist agent")
    ag_run.add_argument("agent", type=str, help="Agent identifier")
    ag_run.add_argument("objective", type=str, help="Task objective for agent")

    # Command: atlas sessions (list, resume, export)
    sess_parser = subparsers.add_parser("sessions", help="CLI session history and state management")
    sess_sub = sess_parser.add_subparsers(dest="sessions_command", help="Sessions subcommands")
    s_list = sess_sub.add_parser("list", help="List recorded CLI sessions")
    s_list.add_argument("--limit", type=int, default=50, help="Max sessions to list")
    s_res = sess_sub.add_parser("resume", help="Resume an existing CLI session")
    s_res.add_argument("session_id", type=str, help="Session ID to resume")
    s_exp = sess_sub.add_parser("export", help="Export session history to file")
    s_exp.add_argument("session_id", type=str, help="Session ID to export")
    s_exp.add_argument("--output", "-o", type=str, default=None, help="Output destination path")

    # Command: atlas tools
    tools_parser = subparsers.add_parser("tools", help="Tool registry operations")
    tools_sub = tools_parser.add_subparsers(dest="tools_command", help="Tools subcommands")
    tools_sub.add_parser("list", help="List registered execution tools")

    # Command: atlas plugins
    plugins_parser = subparsers.add_parser("plugins", help="Skill and plugin package management")
    plugins_sub = plugins_parser.add_subparsers(dest="plugins_command", help="Plugins subcommands")
    plugins_sub.add_parser("list", help="List installed plugins")
    p_inst = plugins_sub.add_parser("install", help="Install a plugin package")
    p_inst.add_argument("name", type=str, help="Plugin package identifier to install")

    # Command: atlas mcp
    mcp_parser = subparsers.add_parser("mcp", help="Model Context Protocol (MCP) servers")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", help="MCP subcommands")
    mcp_sub.add_parser("list", help="List registered MCP servers")

    # Command: atlas skills
    skills_parser = subparsers.add_parser("skills", help="Engineering workflow skills")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", help="Skills subcommands")
    skills_sub.add_parser("list", help="List registered engineering skills")

    # Command: atlas profiles
    profiles_parser = subparsers.add_parser("profiles", help="Workspace development profiles")
    profiles_sub = profiles_parser.add_subparsers(
        dest="profiles_command", help="Profiles subcommands"
    )
    profiles_sub.add_parser("list", help="List available workspace profiles")

    # Command: atlas edition
    subparsers.add_parser("edition", help="Display product edition and feature matrix")

    # Command: atlas server
    server_parser = subparsers.add_parser("server", help="Control plane API server management")
    server_sub = server_parser.add_subparsers(dest="server_command", help="Server subcommands")
    server_sub.add_parser("status", help="Check API server health and connectivity")

    # Command: atlas workers
    workers_parser = subparsers.add_parser("workers", help="Worker node fleet operations")
    workers_sub = workers_parser.add_subparsers(dest="workers_command", help="Workers subcommands")
    workers_sub.add_parser("list", help="List active and leased worker nodes")

    # Command: atlas logs
    logs_parser = subparsers.add_parser("logs", help="Audit and execution event logs")
    logs_parser.add_argument(
        "--limit", "-l", type=int, default=30, help="Number of recent log events"
    )

    # Command: atlas environment
    env_parser = subparsers.add_parser(
        "environment",
        help="Environment and driver runtime testing",
        description="Verify and test execution drivers and environment availability.",
    )
    env_subparsers = env_parser.add_subparsers(
        dest="env_command",
        help="Environment subcommands",
    )
    test_parser = env_subparsers.add_parser(
        "test",
        help="Run diagnostic test for specific execution runtime",
    )
    test_subparsers = test_parser.add_subparsers(
        dest="runtime_target",
        help="Runtime driver to test",
    )
    test_subparsers.add_parser(
        "browser",
        help="Test Playwright Chromium browser driver launch and connectivity",
    )

    # Command: atlas init
    subparsers.add_parser(
        "init",
        help="Initialize local .atlas/ workspace configuration and database",
        description="Scaffold .atlas configuration directory and initialize SQLite database.",
    )

    # Command: atlas task
    task_parser = subparsers.add_parser(
        "task",
        help="Task lifecycle operations (create, list, inspect, pause, resume, cancel)",
        description="Manage ATLAS tasks and inspect execution events.",
    )
    task_subparsers = task_parser.add_subparsers(
        dest="task_command",
        help="Task subcommands",
    )

    # Subcommand: atlas task create
    create_parser_cmd = task_subparsers.add_parser(
        "create",
        help="Create and persist a new task",
    )
    create_parser_cmd.add_argument(
        "objective",
        type=str,
        help="Objective statement describing what the task should accomplish",
    )
    create_parser_cmd.add_argument(
        "--priority",
        "-p",
        type=str,
        default="NORMAL",
        choices=["LOW", "NORMAL", "HIGH", "CRITICAL"],
        help="Execution priority (default: NORMAL)",
    )
    create_parser_cmd.add_argument(
        "--metadata",
        "-m",
        type=str,
        default=None,
        help="Optional JSON string containing task metadata attributes",
    )

    # Subcommand: atlas task list
    list_parser_cmd = task_subparsers.add_parser(
        "list",
        help="List tasks with optional filtering",
    )
    list_parser_cmd.add_argument(
        "--status",
        "-s",
        type=str,
        default=None,
        help="Filter tasks by status (e.g. CREATED, RUNNING, COMPLETED)",
    )
    list_parser_cmd.add_argument(
        "--limit",
        "-l",
        type=int,
        default=50,
        help="Maximum number of tasks to return (default: 50)",
    )
    list_parser_cmd.add_argument(
        "--offset",
        "-o",
        type=int,
        default=0,
        help="Pagination offset (default: 0)",
    )

    # Subcommand: atlas task inspect
    inspect_parser_cmd = task_subparsers.add_parser(
        "inspect",
        help="Inspect task details and event history",
    )
    inspect_parser_cmd.add_argument(
        "task_id",
        type=str,
        help="Unique task identifier to inspect",
    )

    # Subcommand: atlas task pause
    pause_cmd = task_subparsers.add_parser("pause", help="Pause an active task")
    pause_cmd.add_argument("task_id", type=str, help="Task ID to pause")
    pause_cmd.add_argument("--reason", "-r", type=str, default=None, help="Pause reason")

    # Subcommand: atlas task resume
    resume_cmd = task_subparsers.add_parser("resume", help="Resume a paused task")
    resume_cmd.add_argument("task_id", type=str, help="Task ID to resume")

    # Subcommand: atlas task cancel
    cancel_cmd = task_subparsers.add_parser("cancel", help="Cancel a pending or running task")
    cancel_cmd.add_argument("task_id", type=str, help="Task ID to cancel")
    cancel_cmd.add_argument("--reason", "-r", type=str, default=None, help="Cancellation reason")

    # Command: atlas worker
    worker_parser = subparsers.add_parser(
        "worker",
        help="Worker lifecycle operations and daemon launcher",
    )
    worker_subparsers = worker_parser.add_subparsers(
        dest="worker_command",
        help="Worker subcommands",
    )
    worker_run_cmd = worker_subparsers.add_parser(
        "run",
        help="Launch a standalone background worker daemon",
    )
    worker_run_cmd.add_argument("--worker-id", type=str, default=None, help="Unique worker node ID")
    worker_run_cmd.add_argument(
        "--capabilities",
        "-c",
        type=str,
        default="desktop,browser",
        help="Comma-separated capabilities",
    )
    worker_run_cmd.add_argument(
        "--heartbeat-interval", type=float, default=5.0, help="Heartbeat interval in seconds"
    )
    worker_run_cmd.add_argument(
        "--poll-interval", type=float, default=1.0, help="Task poll interval in seconds"
    )
    worker_run_cmd.add_argument(
        "--max-tasks", type=int, default=0, help="Exit after processing N tasks (0=unlimited)"
    )
    worker_run_cmd.add_argument(
        "--once", action="store_true", help="Process at most one task then exit"
    )

    # Command: atlas approval
    approval_parser = subparsers.add_parser(
        "approval",
        help="Human-in-the-loop authorization operations",
    )
    approval_subparsers = approval_parser.add_subparsers(
        dest="approval_command",
        help="Approval subcommands",
    )
    appr_list_cmd = approval_subparsers.add_parser("list", help="List approval requests")
    appr_list_cmd.add_argument("--status", "-s", type=str, default=None, help="Filter by status")

    appr_grant_cmd = approval_subparsers.add_parser("grant", help="Grant an approval request")
    appr_grant_cmd.add_argument("request_id", type=str, help="Request ID to grant")
    appr_grant_cmd.add_argument(
        "--reason", "-r", type=str, default=None, help="Grant justification"
    )

    appr_deny_cmd = approval_subparsers.add_parser("deny", help="Deny an approval request")
    appr_deny_cmd.add_argument("request_id", type=str, help="Request ID to deny")
    appr_deny_cmd.add_argument(
        "--reason", "-r", type=str, default=None, help="Denial justification"
    )

    return parser


def _setup_signal_handlers() -> None:
    """Register graceful shutdown handlers for interrupt signals."""

    def _handle_sigint(sig, frame):
        sys.stderr.write("\n[ATLAS CLI] Interrupt received. Shutting down gracefully...\n")
        sys.exit(130)

    try:
        signal.signal(signal.SIGINT, _handle_sigint)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_sigint)
    except (ValueError, AttributeError):
        pass


def main(argv: list[str] | None = None) -> int:
    """CLI execution entrypoint."""
    _setup_signal_handlers()
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Check for direct prompt execution: e.g. atlas "Build a FastAPI backend"
    known_commands = {
        "run",
        "doctor",
        "environment",
        "init",
        "task",
        "worker",
        "approval",
        "plan",
        "review",
        "debug",
        "test",
        "models",
        "agents",
        "sessions",
        "tools",
        "plugins",
        "mcp",
        "skills",
        "profiles",
        "edition",
        "config",
        "permissions",
        "approvals",
        "status",
        "server",
        "workers",
        "logs",
    }

    # Support piped input when no arguments are provided
    if not args_list:
        try:
            if hasattr(sys.stdin, "isatty") and not sys.stdin.isatty():
                piped = sys.stdin.read().strip()
                if piped:
                    return run_coding_task(piped)
        except (OSError, ValueError, AttributeError):
            pass

    if args_list:
        first = args_list[0]
        if first == "--tui":
            return run_conversation_app()
        if first == "--inspector":
            from atlas_cli.conversation.inspector import AdvancedInspector

            inspector = AdvancedInspector()
            inspector.show()
            return 0
        if first == "--minimal":
            obj = " ".join(args_list[1:]) if len(args_list) > 1 else None
            return run_minimal(objective=obj)
        if first in ("--version", "-v"):
            print("ATLAS v0.16.8 (Autonomous Task & Lifecycle Automation System)")
            return 0
        if not first.startswith("-") and first not in known_commands:
            # Direct prompt execution only for natural language sentences (contains spaces)
            # or multi-token prompts (len(args_list) > 1 without leading flags).
            # Single-token non-commands (e.g. typos, invalid subcommands) must fall through
            # to parser.parse_args so argparse rejects them with non-zero exit code.
            if " " in first or len(args_list) > 1:
                prompt = " ".join(args_list)
                return run_coding_task(prompt)

    parser = create_parser()
    args = parser.parse_args(args_list)

    if getattr(args, "prompt", None):
        return run_coding_task(args.prompt)

    if args.version:
        print("ATLAS v0.16.8")
        return 0

    if args.tui:
        return run_conversation_app()

    if getattr(args, "inspector", False):
        from atlas_cli.conversation.inspector import AdvancedInspector

        inspector = AdvancedInspector()
        inspector.show()
        return 0

    if args.minimal:
        return run_minimal()

    if args.command == "run":
        return run_coding_task(args.objective)

    if args.command is None:
        if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            return run_conversation_app()
        print(render_banner())
        parser.print_help()
        return 0

    # Coding & Development
    if args.command == "plan":
        return run_plan(goal=args.goal)
    if args.command == "review":
        return run_review(diff=args.diff)
    if args.command == "debug":
        return run_debug()
    if args.command == "test":
        return run_test()

    # Models
    if args.command == "models":
        if getattr(args, "models_command", None) == "list":
            return run_models_list()
        if getattr(args, "models_command", None) == "use":
            return run_models_use(args.model_name)
        if getattr(args, "models_command", None) == "configure":
            return run_models_configure()
        parser.parse_args(["models", "--help"])
        return 0

    # Agents
    if args.command == "agents":
        if getattr(args, "agents_command", None) == "list":
            return run_agents_list()
        if getattr(args, "agents_command", None) == "inspect":
            return run_agents_inspect(args.agent)
        if getattr(args, "agents_command", None) == "run":
            return run_agents_run(args.agent, args.objective)
        parser.parse_args(["agents", "--help"])
        return 0

    # Sessions
    if args.command == "sessions":
        if getattr(args, "sessions_command", None) == "list":
            return run_sessions_list(limit=args.limit)
        if getattr(args, "sessions_command", None) == "resume":
            return run_sessions_resume(args.session_id)
        if getattr(args, "sessions_command", None) == "export":
            return run_sessions_export(args.session_id, output=args.output)
        parser.parse_args(["sessions", "--help"])
        return 0

    # Tools, Plugins, MCP
    if args.command == "tools":
        if getattr(args, "tools_command", None) == "list":
            return run_tools_list()
        parser.parse_args(["tools", "--help"])
        return 0
    if args.command == "plugins":
        if getattr(args, "plugins_command", None) == "list":
            return run_plugins_list()
        if getattr(args, "plugins_command", None) == "install":
            return run_plugins_install(args.name)
        parser.parse_args(["plugins", "--help"])
        return 0
    if args.command == "mcp":
        if getattr(args, "mcp_command", None) == "list":
            return run_mcp_list()
        parser.parse_args(["mcp", "--help"])
        return 0
    if args.command == "skills":
        if getattr(args, "skills_command", None) == "list":
            return run_skills_list()
        parser.parse_args(["skills", "--help"])
        return 0
    if args.command == "profiles":
        if getattr(args, "profiles_command", None) == "list":
            return run_profiles_list()
        parser.parse_args(["profiles", "--help"])
        return 0
    if args.command == "edition":
        return run_edition_info()

    # Governance & Configuration
    if args.command == "config":
        return run_config_cmd(key=args.key, value=args.val)
    if args.command == "permissions":
        return run_permissions()
    if args.command == "approvals":
        from atlas_cli.approvals.interactive import run_interactive_approvals

        return run_interactive_approvals()
    if args.command == "status":
        return run_status()
    if args.command == "doctor":
        return run_doctor()

    # Runtime
    if args.command == "server":
        if getattr(args, "server_command", None) == "status":
            return run_server_status()
        parser.parse_args(["server", "--help"])
        return 0
    if args.command == "workers":
        if getattr(args, "workers_command", None) == "list":
            return run_workers_list()
        parser.parse_args(["workers", "--help"])
        return 0
    if args.command == "logs":
        return run_logs(limit=args.limit)

    # Existing commands: environment, init, task, worker, approval
    if args.command == "environment":
        if (
            getattr(args, "env_command", None) == "test"
            and getattr(args, "runtime_target", None) == "browser"
        ):
            return run_environment_test_browser()
        parser.parse_args(["environment", "--help"])
        return 0

    if args.command == "init":
        return run_init()

    if args.command == "task":
        if args.task_command is None:
            parser.parse_args(["task", "--help"])
            return 0
        if args.task_command == "create":
            return run_task_create(
                objective=args.objective,
                priority=args.priority,
                metadata_json=args.metadata,
            )
        if args.task_command == "list":
            return run_task_list(
                status_filter=args.status,
                limit=args.limit,
                offset=args.offset,
            )
        if args.task_command == "inspect":
            return run_task_inspect(task_id=args.task_id)
        if args.task_command == "pause":
            return run_task_pause(task_id=args.task_id, reason=args.reason)
        if args.task_command == "resume":
            return run_task_resume(task_id=args.task_id)
        if args.task_command == "cancel":
            return run_task_cancel(task_id=args.task_id, reason=args.reason)

    if args.command == "worker":
        if getattr(args, "worker_command", None) == "run":
            caps = [c.strip() for c in args.capabilities.split(",") if c.strip()]
            return run_worker_daemon(
                worker_id=args.worker_id,
                capabilities=caps,
                heartbeat_interval=args.heartbeat_interval,
                poll_interval=args.poll_interval,
                max_tasks=args.max_tasks,
                once=args.once,
            )
        parser.parse_args(["worker", "--help"])
        return 0

    if args.command == "approval":
        if args.approval_command is None:
            parser.parse_args(["approval", "--help"])
            return 0
        if args.approval_command == "list":
            return run_approval_list(status_filter=args.status)
        if args.approval_command == "grant":
            return run_approval_grant(request_id=args.request_id, reason=args.reason)
        if args.approval_command == "deny":
            return run_approval_deny(request_id=args.request_id, reason=args.reason)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

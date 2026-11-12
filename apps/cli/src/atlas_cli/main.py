"""Main entrypoint for ATLAS Developer CLI."""

import argparse
import sys

from atlas_cli.commands.approval import (
    run_approval_deny,
    run_approval_grant,
    run_approval_list,
)
from atlas_cli.commands.doctor import run_doctor
from atlas_cli.commands.environment import run_environment_test_browser
from atlas_cli.commands.init import run_init
from atlas_cli.commands.task import (
    run_task_cancel,
    run_task_create,
    run_task_inspect,
    run_task_list,
    run_task_pause,
    run_task_resume,
)
from atlas_cli.commands.worker import run_worker_daemon


def create_parser() -> argparse.ArgumentParser:
    """Construct top-level CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="ATLAS - Autonomous Task & Lifecycle Automation System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: atlas doctor
    subparsers.add_parser(
        "doctor",
        help="Run environment diagnostics and verify system health",
        description="Verify Python version, OS platform, and SQLite WAL capability.",
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
    cancel_cmd = task_subparsers.add_parser("cancel", help="Cancel a task")
    cancel_cmd.add_argument("task_id", type=str, help="Task ID to cancel")
    cancel_cmd.add_argument("--reason", "-r", type=str, default=None, help="Cancellation reason")

    # Command: atlas worker
    worker_parser = subparsers.add_parser(
        "worker",
        help="Worker daemon fleet management and execution",
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


def main(argv: list[str] | None = None) -> int:
    """CLI execution entrypoint."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "doctor":
        return run_doctor()

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

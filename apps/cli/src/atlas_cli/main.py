"""Main entrypoint for ATLAS Developer CLI."""

import argparse
import sys

from atlas_cli.commands.doctor import run_doctor
from atlas_cli.commands.environment import run_environment_test_browser
from atlas_cli.commands.init import run_init
from atlas_cli.commands.task import run_task_create, run_task_inspect, run_task_list


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
        help="Task lifecycle operations (create, list, inspect)",
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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

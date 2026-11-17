"""Minimal headless runner for scriptable and CI/CD pipelines."""

import json
import sys

from atlas_cli.adapters.client import AtlasClient


def run_minimal(objective: str | None = None, json_output: bool = True) -> int:
    """Execute task in minimal headless mode with structured output."""
    client = AtlasClient()

    # Read objective from argument or standard input
    if not objective:
        try:
            if hasattr(sys.stdin, "isatty") and not sys.stdin.isatty():
                objective = sys.stdin.read().strip()
        except (OSError, ValueError, AttributeError):
            objective = None

        if not objective:
            print("Error: Objective required for minimal execution.", file=sys.stderr)
            return 1

    # Check if objective requires multi-agent DAG or single task
    is_complex = any(
        k in objective.lower() for k in ["dag", "multi-agent", "specialist", "decompose"]
    )

    if is_complex:
        result = client.submit_multi_agent_dag(objective, execute_async=False)
    else:
        result = client.submit_task(objective, wait=True)

    if "error" in result:
        if json_output:
            print(json.dumps({"status": "FAILED", "error": result["error"]}))
        else:
            print(f"FAILED: {result['error']}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        status = result.get("status", "COMPLETED")
        task_id = result.get("task_id", "")
        output = result.get("metadata", {}).get("output") or result.get("message") or "Completed"
        print(f"[{status}] {task_id}: {output}")

    return 0

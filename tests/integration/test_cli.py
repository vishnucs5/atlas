"""Integration test suite for the ATLAS Developer CLI (apps/cli)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_SRC = str(REPO_ROOT / "apps" / "cli" / "src")
CORE_SRC = str(REPO_ROOT / "packages" / "atlas-core" / "src")
STORAGE_SRC = str(REPO_ROOT / "packages" / "atlas-storage" / "src")
POLICY_SRC = str(REPO_ROOT / "packages" / "atlas-policy" / "src")
OBS_SRC = str(REPO_ROOT / "packages" / "atlas-observability" / "src")
BROWSER_SRC = str(REPO_ROOT / "packages" / "atlas-browser" / "src")
OBSERVATION_SRC = str(REPO_ROOT / "packages" / "atlas-observation" / "src")
VERIFICATION_SRC = str(REPO_ROOT / "packages" / "atlas-verification" / "src")


def get_cli_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess execution environment with source paths in PYTHONPATH."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    src_paths = [
        CLI_SRC,
        CORE_SRC,
        STORAGE_SRC,
        POLICY_SRC,
        OBS_SRC,
        BROWSER_SRC,
        OBSERVATION_SRC,
        VERIFICATION_SRC,
    ]
    if existing:
        src_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(src_paths)
    if extra_env:
        env.update(extra_env)
    return env


def test_cli_help() -> None:
    """Verify top-level CLI help command displays banner and returns 0."""
    cmd = [sys.executable, "-m", "atlas_cli.main", "--help"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=get_cli_env(),
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "ATLAS - Autonomous Task & Lifecycle Automation System" in result.stdout
    assert "doctor" in result.stdout
    assert "init" in result.stdout
    assert "task" in result.stdout


def test_cli_doctor() -> None:
    """Verify 'atlas doctor' runs diagnostics and reports HEALTHY system status."""
    cmd = [sys.executable, "-m", "atlas_cli.main", "doctor"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=get_cli_env(),
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "Python:" in result.stdout
    assert "SQLite:" in result.stdout
    assert "Platform:" in result.stdout
    assert "Playwright Chromium:" in result.stdout
    assert "System status: HEALTHY" in result.stdout


def test_cli_environment_test_browser() -> None:
    """Verify 'atlas environment test browser' validates browser driver connectivity."""
    cmd = [sys.executable, "-m", "atlas_cli.main", "environment", "test", "browser"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=get_cli_env(),
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "Testing ATLAS Browser Runtime..." in result.stdout
    assert "browser.playwright.chromium" in result.stdout
    assert "Browser test: SUCCESS" in result.stdout


def test_cli_init_and_task_lifecycle(tmp_path: Path) -> None:
    """Verify 'atlas init' and the complete 'atlas task' lifecycle."""
    env = get_cli_env({"ATLAS_HOME": str(tmp_path)})

    # Step 1: Initialize workspace
    init_cmd = [sys.executable, "-m", "atlas_cli.main", "init"]
    res_init = subprocess.run(init_cmd, capture_output=True, text=True, env=env)
    assert res_init.returncode == 0
    assert "Initialized ATLAS workspace" in res_init.stdout

    # Verify storage database was initialized
    atlas_dir = tmp_path / ".atlas" if (tmp_path / ".atlas").exists() else tmp_path
    db_file = atlas_dir / "atlas.db"
    assert db_file.exists(), f"Expected database at {db_file}"

    # Step 2: Create a task
    create_cmd = [
        sys.executable,
        "-m",
        "atlas_cli.main",
        "task",
        "create",
        "Deploy v1.0 release",
        "--priority",
        "HIGH",
    ]
    res_create = subprocess.run(create_cmd, capture_output=True, text=True, env=env)
    assert res_create.returncode == 0
    assert "Created task:" in res_create.stdout
    assert "Deploy v1.0 release" in res_create.stdout
    assert "HIGH" in res_create.stdout

    # Extract task_id from create output
    match = re.search(r"Created task:\s*([a-zA-Z0-9_-]+)", res_create.stdout)
    assert match is not None, f"Could not find task ID in output: {res_create.stdout}"
    task_id = match.group(1).strip()

    # Step 3: List tasks
    list_cmd = [sys.executable, "-m", "atlas_cli.main", "task", "list"]
    res_list = subprocess.run(list_cmd, capture_output=True, text=True, env=env)
    assert res_list.returncode == 0
    assert task_id in res_list.stdout
    assert "Deploy v1.0 release" in res_list.stdout

    # Step 4: Inspect task
    inspect_cmd = [sys.executable, "-m", "atlas_cli.main", "task", "inspect", task_id]
    res_inspect = subprocess.run(inspect_cmd, capture_output=True, text=True, env=env)
    assert res_inspect.returncode == 0
    assert task_id in res_inspect.stdout
    assert "Deploy v1.0 release" in res_inspect.stdout
    assert "CREATED" in res_inspect.stdout
    assert "TASK_CREATED" in res_inspect.stdout


def test_cli_task_inspect_not_found(tmp_path: Path) -> None:
    """Verify inspecting a non-existent task returns non-zero error."""
    env = get_cli_env({"ATLAS_HOME": str(tmp_path)})

    # Initialize first
    subprocess.run([sys.executable, "-m", "atlas_cli.main", "init"], capture_output=True, env=env)

    # Inspect non-existent task
    cmd = [sys.executable, "-m", "atlas_cli.main", "task", "inspect", "task-does-not-exist"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert "not found" in (result.stderr + result.stdout).lower()


def test_cli_task_metadata_and_secret_redaction(tmp_path: Path) -> None:
    """Verify metadata secrets are masked and not printed in cleartext (Constitution Rule 6)."""
    env = get_cli_env({"ATLAS_HOME": str(tmp_path)})
    subprocess.run([sys.executable, "-m", "atlas_cli.main", "init"], capture_output=True, env=env)

    raw_secret = "sk-live-atlas1234567890abcdef"
    metadata_json = json.dumps({"api_key": raw_secret, "env": "prod"})

    create_cmd = [
        sys.executable,
        "-m",
        "atlas_cli.main",
        "task",
        "create",
        "Secure cloud provisioning",
        "--metadata",
        metadata_json,
    ]
    res_create = subprocess.run(create_cmd, capture_output=True, text=True, env=env)
    assert res_create.returncode == 0
    assert raw_secret not in res_create.stdout
    assert raw_secret not in res_create.stderr

    match = re.search(r"Created task:\s*([a-zA-Z0-9_-]+)", res_create.stdout)
    assert match is not None
    task_id = match.group(1).strip()

    inspect_cmd = [sys.executable, "-m", "atlas_cli.main", "task", "inspect", task_id]
    res_inspect = subprocess.run(inspect_cmd, capture_output=True, text=True, env=env)
    assert res_inspect.returncode == 0
    assert raw_secret not in res_inspect.stdout
    assert raw_secret not in res_inspect.stderr
    assert (
        "[REDACTED]" in res_inspect.stdout
        or "***" in res_inspect.stdout
        or "..." in res_inspect.stdout
    )


def test_cli_invalid_command() -> None:
    """Verify unrecognized CLI command produces non-zero exit code."""
    cmd = [sys.executable, "-m", "atlas_cli.main", "invalid-subcommand-xyz"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=get_cli_env())
    assert result.returncode != 0

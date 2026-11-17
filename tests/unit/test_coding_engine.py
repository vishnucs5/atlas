"""Comprehensive unit, integration, and adversarial tests for ATLAS Coding Engine."""

import tempfile
from pathlib import Path

import pytest
from atlas_coding.engine import CodingEngine
from atlas_coding.explorer import RepositoryExplorer
from atlas_coding.file_ops import (
    AuthorizedFileOperations,
    ConcurrentModificationError,
    PolicyAuthorizationError,
)
from atlas_coding.git import GitPorcelain
from atlas_coding.patch import PatchConflictError, PatchEngine
from atlas_coding.planner import CodingPlanner
from atlas_coding.terminal import AuthorizedTerminalDriver, redact_secrets
from atlas_core.contracts.coding import FileChangeType
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_core.contracts.task import TaskStatus
from atlas_policy.firewall import ActionFirewall, PolicyRule


@pytest.fixture
def temp_repo():
    """Create a temporary sandbox repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir).resolve()
        # Create standard layout
        (repo_path / "src").mkdir()
        (repo_path / "src" / "main.py").write_text(
            "def hello():\n    return 'world'\n", encoding="utf-8"
        )
        (repo_path / "pyproject.toml").write_text(
            "[project]\nname = 'temp-app'\nversion = '0.1.0'\n", encoding="utf-8"
        )
        (repo_path / ".env").write_text("SECRET_KEY=supersecret123\n", encoding="utf-8")
        (repo_path / "binary.bin").write_bytes(b"\x00\x01\x02\x03\x04")
        yield repo_path


def test_explorer_workspace_containment(temp_repo):
    """Verify path traversal outside repo root is strictly blocked."""
    explorer = RepositoryExplorer(repo_root=temp_repo)

    # Valid relative path inside repo
    safe = explorer.resolve_safe_path("src/main.py")
    assert safe == temp_repo / "src" / "main.py"

    # Traversal attempt outside repo
    with pytest.raises(ValueError, match="Path traversal violation"):
        explorer.resolve_safe_path("../../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal violation"):
        explorer.resolve_safe_path("..")


def test_explorer_sensitive_and_binary_exclusion(temp_repo):
    """Verify secrets and binary files are handled securely."""
    explorer = RepositoryExplorer(repo_root=temp_repo)

    assert explorer.is_sensitive(".env")
    assert explorer.is_sensitive("sub/id_rsa")
    assert not explorer.is_sensitive("src/main.py")

    discovered = explorer.discover_files(include_binary=False, include_sensitive=False)
    discovered_rel = [d.rel_path for d in discovered]

    assert "src/main.py" in discovered_rel
    assert "pyproject.toml" in discovered_rel
    assert ".env" not in discovered_rel
    assert "binary.bin" not in discovered_rel


def test_file_ops_read_and_bounded_lines(temp_repo):
    """Verify bounded reading and 1-based line slicing."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    file_ops = AuthorizedFileOperations(explorer=explorer)

    content = file_ops.read_file("src/main.py")
    assert "def hello():" in content

    lines = file_ops.read_lines("src/main.py", start_line=1, end_line=1)
    assert len(lines) == 1
    assert "def hello():" in lines[0]

    # Sensitive read blocked
    with pytest.raises(PermissionError, match="sensitive secret file"):
        file_ops.read_file(".env")


def test_file_ops_optimistic_concurrency_and_atomic_write(temp_repo):
    """Verify file modification with optimistic hash checks and diff recording."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    file_ops = AuthorizedFileOperations(explorer=explorer)

    # Read current hash
    meta = explorer.get_metadata("src/main.py")
    initial_hash = meta.sha256
    assert initial_hash

    # Modify with correct expected hash
    new_code = "def hello():\n    return 'atlas'\n"
    change = file_ops.write_file("src/main.py", new_code, expected_hash=initial_hash)

    assert change.change_type == FileChangeType.MODIFY
    assert change.before_hash == initial_hash
    assert change.after_hash != initial_hash
    assert change.lines_added == 1
    assert change.lines_removed == 1
    assert change.verified is True

    # Attempt modification with stale expected hash should fail
    with pytest.raises(ConcurrentModificationError, match="Optimistic concurrency failure"):
        file_ops.write_file("src/main.py", "def fail(): pass\n", expected_hash=initial_hash)


def test_file_ops_firewall_policy_enforcement(temp_repo):
    """Verify ActionFirewall gates file operations according to rules."""
    explorer = RepositoryExplorer(repo_root=temp_repo)

    # Custom rule that denies all file creation
    deny_rule = PolicyRule(
        rule_id="deny_file_create",
        name="Block All File Creations",
        exact_action_type="file.create",
        decision=PolicyDecisionType.DENY,
        risk_level=RiskLevel.CRITICAL,
        priority=150,
    )
    firewall = ActionFirewall(rules=[deny_rule])
    file_ops = AuthorizedFileOperations(explorer=explorer, firewall=firewall)

    with pytest.raises(PolicyAuthorizationError, match="Action blocked by policy"):
        file_ops.create_file("src/new_file.py", "x = 1\n")


def test_patch_engine_dry_run_and_application(temp_repo):
    """Verify unified diff parsing, dry run validation, and atomic application."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    file_ops = AuthorizedFileOperations(explorer=explorer)
    patch_engine = PatchEngine(file_ops=file_ops)

    raw_diff = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def hello():\n"
        "-    return 'world'\n"
        "+    return 'universe'\n"
        "+    # added line\n"
    )

    parsed = patch_engine.parse_unified_diff(raw_diff)
    assert parsed.files_changed == 1
    assert parsed.insertions == 2
    assert parsed.deletions == 1

    # Dry run
    dry_results = patch_engine.apply_patch(parsed, dry_run=True)
    assert len(dry_results) == 1
    # Ensure disk is untouched after dry run
    assert "universe" not in file_ops.read_file("src/main.py")

    # Real application
    applied = patch_engine.apply_patch(parsed, dry_run=False)
    assert len(applied) == 1
    content_after = file_ops.read_file("src/main.py")
    assert "return 'universe'" in content_after
    assert "# added line" in content_after


def test_patch_engine_conflict_and_rollback(temp_repo):
    """Verify conflicting hunk raises PatchConflictError without corrupting files."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    file_ops = AuthorizedFileOperations(explorer=explorer)
    patch_engine = PatchEngine(file_ops=file_ops)

    # Create file2
    file_ops.create_file("src/file2.py", "alpha = 100\n")

    # Multi-file patch where file2 hunk conflicts
    conflict_diff = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def hello():\n"
        "-    return 'world'\n"
        "+    return 'patched'\n"
        "--- a/src/file2.py\n"
        "+++ b/src/file2.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-nonexistent line that fails\n"
        "+beta = 200\n"
    )

    with pytest.raises(PatchConflictError, match="Target content does not match hunk context"):
        patch_engine.apply_patch(conflict_diff)

    # Invariant: Neither file should be modified (transactional rollback)
    assert "return 'world'" in file_ops.read_file("src/main.py")
    assert "alpha = 100" in file_ops.read_file("src/file2.py")


def test_terminal_safe_execution_and_secret_redaction(temp_repo):
    """Verify terminal driver execution, timeout handling, and credential masking."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    terminal = AuthorizedTerminalDriver(explorer=explorer)

    # Safe command
    cmd = ["python", "-c", "print('hello from python')"]
    res = terminal.execute(cmd)
    assert res.exit_code == 0
    assert "hello from python" in res.stdout
    assert res.timed_out is False

    # Secret redaction check
    text_with_secret = "Authentication header: Bearer my_super_secret_token_12345"
    redacted = redact_secrets(text_with_secret)
    assert "[REDACTED_SECRET]" in redacted
    assert "my_super_secret_token_12345" not in redacted


def test_terminal_destructive_command_blocking(temp_repo):
    """Verify ActionFirewall blocks destructive system alteration commands."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    firewall = ActionFirewall()
    terminal = AuthorizedTerminalDriver(
        explorer=explorer, firewall=firewall, auto_approve_safe_commands=False
    )

    destructive_cmds = [
        "rm -rf /",
        "del /s /q C:\\",
        "format C:",
    ]

    for d_cmd in destructive_cmds:
        with pytest.raises(
            PolicyAuthorizationError, match="requires explicit human approval|denied"
        ):
            terminal.execute(d_cmd)


def test_git_porcelain_inspection(temp_repo):
    """Verify GitPorcelain functions on a repository."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    terminal = AuthorizedTerminalDriver(explorer=explorer)
    git = GitPorcelain(explorer=explorer, terminal=terminal)

    # Initialize git repo in temporary directory
    terminal.execute(["git", "init"])
    assert git.is_git_repo()

    status = git.status()
    assert isinstance(status.untracked, list)
    assert len(status.untracked) > 0


def test_coding_planner_generation(temp_repo):
    """Verify CodingPlanner creates structured plans with risk levels."""
    explorer = RepositoryExplorer(repo_root=temp_repo)
    planner = CodingPlanner(explorer=explorer)
    engine = CodingEngine(repo_root=temp_repo)

    task = engine.create_task(user_request="Refactor main.py to support async hello")
    plan = planner.create_plan(task)

    assert plan["objective"] == task.objective
    assert "src/main.py" in plan["relevant_files"]
    assert len(plan["steps"]) >= 4
    assert plan["estimated_risk"] == RiskLevel.HIGH.value


def test_coding_engine_lifecycle_and_verification_invariant(temp_repo):
    """Verify end-to-end execution loop and deterministic post-condition verification."""
    engine = CodingEngine(repo_root=temp_repo, auto_approve=True)

    task = engine.execute_lifecycle(
        user_request="Add helper utility module",
        files_to_create={"src/utils.py": "def add(a, b):\n    return a + b\n"},
        run_tests=False,
    )

    assert task.status == TaskStatus.COMPLETED
    assert len(task.file_changes) == 1
    assert task.verification_evidence["all_passed"] is True
    assert (temp_repo / "src" / "utils.py").is_file()

    # Verify tampering causes deterministic verification failure
    tampered_task = engine.create_task(user_request="Test verification failure invariant")
    fake_change = task.file_changes[0].model_copy()
    fake_change.after_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    tampered_task.file_changes = [fake_change]

    evidence = engine.verify_task(tampered_task)
    assert evidence["all_passed"] is False
    assert tampered_task.status == TaskStatus.FAILED

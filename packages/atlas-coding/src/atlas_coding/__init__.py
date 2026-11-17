"""ATLAS Autonomous Coding Engine package."""

from atlas_coding.engine import CodingEngine
from atlas_coding.explorer import RepositoryExplorer
from atlas_coding.file_ops import (
    AuthorizedFileOperations,
    ConcurrentModificationError,
    PolicyAuthorizationError,
)
from atlas_coding.git import GitCommitSummary, GitPorcelain, GitStatusReport
from atlas_coding.patch import PatchConflictError, PatchEngine
from atlas_coding.planner import CodingPlanner
from atlas_coding.terminal import AuthorizedTerminalDriver, TerminalResult, redact_secrets
from atlas_coding.test_runner import TestRunner

__all__ = [
    "AuthorizedFileOperations",
    "AuthorizedTerminalDriver",
    "CodingEngine",
    "CodingPlanner",
    "ConcurrentModificationError",
    "GitCommitSummary",
    "GitPorcelain",
    "GitStatusReport",
    "PatchConflictError",
    "PatchEngine",
    "PolicyAuthorizationError",
    "RepositoryExplorer",
    "TerminalResult",
    "TestRunner",
    "redact_secrets",
]

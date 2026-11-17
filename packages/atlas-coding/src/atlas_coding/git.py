"""Safe Git porcelain inspection and status querying for ATLAS."""

from pathlib import Path

from pydantic import BaseModel, Field

from atlas_coding.explorer import RepositoryExplorer
from atlas_coding.terminal import AuthorizedTerminalDriver


class GitStatusReport(BaseModel):
    """Structured git repository status."""

    branch: str = ""
    is_clean: bool = True
    staged: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    raw_status: str = ""


class GitCommitSummary(BaseModel):
    """Summary of a git commit."""

    commit_hash: str
    author: str
    message: str
    timestamp: str = ""


class GitPorcelain:
    """Read-only Git porcelain inspection conforming to ATLAS security invariants."""

    def __init__(
        self,
        explorer: RepositoryExplorer,
        terminal: AuthorizedTerminalDriver | None = None,
    ) -> None:
        self.explorer = explorer
        self.terminal = terminal or AuthorizedTerminalDriver(explorer=explorer)

    def is_git_repo(self) -> bool:
        """Check if repository root is a git repository."""
        git_dir = self.explorer.repo_root / ".git"
        return git_dir.exists()

    def get_current_branch(self) -> str:
        """Query currently checked-out git branch."""
        res = self.terminal.execute(["git", "branch", "--show-current"])
        if res.exit_code == 0:
            return res.stdout.strip()
        return ""

    def status(self) -> GitStatusReport:
        """Retrieve and parse git status in porcelain v1 format."""
        branch = self.get_current_branch()
        res = self.terminal.execute(["git", "status", "--porcelain=v1"])
        if res.exit_code != 0:
            return GitStatusReport(branch=branch, is_clean=True, raw_status=res.stderr)

        staged: list[str] = []
        modified: list[str] = []
        untracked: list[str] = []
        deleted: list[str] = []

        raw = res.stdout
        for line in raw.splitlines():
            if len(line) < 3:
                continue
            x = line[0]
            y = line[1]
            file_path = line[3:].strip()

            if x == "?" and y == "?":
                untracked.append(file_path)
            else:
                if x in ("M", "A", "R"):
                    staged.append(file_path)
                elif x == "D":
                    deleted.append(file_path)

                if y == "M":
                    modified.append(file_path)
                elif y == "D":
                    deleted.append(file_path)

        is_clean = not (staged or modified or untracked or deleted)

        return GitStatusReport(
            branch=branch,
            is_clean=is_clean,
            staged=staged,
            modified=modified,
            untracked=untracked,
            deleted=deleted,
            raw_status=raw,
        )

    def diff(self, cached: bool = False, file_path: str | Path | None = None) -> str:
        """Obtain unified git diff of working directory or staged index."""
        cmd = ["git", "diff"]
        if cached:
            cmd.append("--cached")
        if file_path:
            safe_p = self.explorer.resolve_safe_path(file_path)
            rel_p = str(safe_p.relative_to(self.explorer.repo_root)).replace("\\", "/")
            cmd.extend(["--", rel_p])

        res = self.terminal.execute(cmd)
        return res.stdout

    def log(self, max_count: int = 10) -> list[GitCommitSummary]:
        """Fetch recent commit history with author and message."""
        fmt = "%h|%an|%s|%ci"
        cmd = ["git", "log", f"-n{max_count}", f"--pretty=format:{fmt}"]
        res = self.terminal.execute(cmd)
        if res.exit_code != 0:
            return []

        commits: list[GitCommitSummary] = []
        for line in res.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append(
                    GitCommitSummary(
                        commit_hash=parts[0],
                        author=parts[1],
                        message=parts[2],
                        timestamp=parts[3],
                    )
                )
        return commits

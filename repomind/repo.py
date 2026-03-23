"""Git metadata layer: branch, HEAD SHA, recent commits."""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from repomind.models import Commit

# Maximum time (seconds) to wait for any single git subprocess.
_GIT_TIMEOUT = 10


def _run_git(root: str, *args: str) -> tuple[int, str]:
    """Run a git command in *root* and return (returncode, stdout).

    Returns (1, "") on any exception (git not found, timeout, etc.) so callers
    can treat all failure modes uniformly without try/except at every call site.
    """
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        return result.returncode, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 1, ""


def resolve_repo_root(path: str = "") -> str:
    """Resolve and validate a repo root path.

    Args:
        path: directory path to resolve. If empty, defaults to cwd.

    Returns:
        Absolute, canonicalised path string.

    Raises:
        ValueError: if the resolved path is not an existing directory.
    """
    if not path:
        path = os.getcwd()

    resolved = Path(path).resolve()

    if not resolved.exists():
        raise ValueError(f"Path does not exist: {path!r} (resolved: {resolved})")

    if not resolved.is_dir():
        raise ValueError(f"Path is not a directory: {path!r} (resolved: {resolved})")

    return str(resolved)


# ---------------------------------------------------------------------------
# Git detection
# ---------------------------------------------------------------------------


def is_git_repo(root: str) -> bool:
    """Return True if *root* is inside a Git working tree."""
    rc, _ = _run_git(root, "rev-parse", "--git-dir")
    return rc == 0


# ---------------------------------------------------------------------------
# Current state
# ---------------------------------------------------------------------------


def get_head_sha(root: str) -> str | None:
    """Return the full SHA of HEAD, or None if unavailable."""
    rc, out = _run_git(root, "rev-parse", "HEAD")
    return out if rc == 0 and out else None


def get_branch(root: str) -> str | None:
    """Return the current branch name, or None if HEAD is detached or unavailable."""
    rc, out = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or not out:
        return None
    # Detached HEAD: git outputs the literal string "HEAD"
    return out if out != "HEAD" else None


# ---------------------------------------------------------------------------
# Commit history
# ---------------------------------------------------------------------------


def get_changed_files_for_commit(root: str, sha: str) -> list[str]:
    """Return the list of files changed in *sha* (relative paths).

    Uses diff-tree which works for both regular commits and merge commits.
    Returns an empty list if the command fails or the commit has no parent
    (initial commit is handled via the --root flag).
    """
    rc, out = _run_git(
        root, "diff-tree", "--no-commit-id", "-r", "--name-only", "--root", sha
    )
    if rc != 0 or not out:
        return []
    return [line for line in out.splitlines() if line.strip()]


def get_recent_commits(root: str, days: int = 14) -> list[Commit]:
    """Return commits from the last *days* days, excluding merges.

    Each commit includes its list of changed files. Returns an empty list
    if the repo has no commits, git is unavailable, or an error occurs.

    Format string uses ||| as delimiter — chosen because it cannot appear
    in a commit hash, and is unlikely in subject/author fields.
    """
    rc, out = _run_git(
        root,
        "log",
        f"--since={days} days ago",
        "--no-merges",
        "--format=%H|||%s|||%an|||%at",
    )
    if rc != 0 or not out:
        return []

    commits: list[Commit] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|||", 3)
        if len(parts) != 4:
            continue
        sha, subject, author, ts_raw = parts

        try:
            authored_at = datetime.fromtimestamp(
                int(ts_raw), tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError):
            authored_at = ts_raw

        files = get_changed_files_for_commit(root, sha.strip())
        commits.append(
            Commit(
                hash=sha.strip(),
                subject=subject.strip(),
                author_name=author.strip() or None,
                authored_at=authored_at,
                files_changed=files,
            )
        )

    return commits

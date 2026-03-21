"""Tests for Git metadata detection (T04).

Uses a real temporary Git repository to avoid subprocess mocking fragility.
All git config (user name/email) is set locally to the temp repo so these
tests work in CI environments with no global git identity configured.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from repomind.repo import (
    get_branch,
    get_changed_files_for_commit,
    get_head_sha,
    get_recent_commits,
    is_git_repo,
)


# ---------------------------------------------------------------------------
# Fixture: minimal real git repo
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path):
    """Create a minimal git repo with two commits in a temp directory."""
    run = lambda *args: subprocess.run(  # noqa: E731
        list(args), cwd=tmp_path, capture_output=True, text=True, check=False
    )
    run("git", "init")
    run("git", "config", "user.email", "test@repomind.test")
    run("git", "config", "user.name", "Repomind Test")

    # First commit
    (tmp_path / "README.md").write_text("# Test repo
")
    (tmp_path / "main.py").write_text("print('hello')
")
    run("git", "add", ".")
    run("git", "commit", "-m", "initial: add README and main")

    # Second commit
    (tmp_path / "utils.py").write_text("def helper(): pass
")
    run("git", "add", ".")
    run("git", "commit", "-m", "feat: add utils")

    return tmp_path


@pytest.fixture()
def empty_git_repo(tmp_path: Path):
    """A git repo with no commits."""
    subprocess.run(
        ["git", "init"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    return tmp_path


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------


def test_is_git_repo_true(git_repo):
    assert is_git_repo(str(git_repo)) is True


def test_is_git_repo_false_for_plain_dir(tmp_path):
    assert is_git_repo(str(tmp_path)) is False


def test_is_git_repo_false_for_nonexistent(tmp_path):
    assert is_git_repo(str(tmp_path / "nope")) is False


# ---------------------------------------------------------------------------
# get_head_sha
# ---------------------------------------------------------------------------


def test_get_head_sha_returns_40_char_hex(git_repo):
    sha = get_head_sha(str(git_repo))
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_get_head_sha_none_for_non_git(tmp_path):
    assert get_head_sha(str(tmp_path)) is None


def test_get_head_sha_none_for_empty_repo(empty_git_repo):
    # No commits yet — HEAD is unresolvable
    assert get_head_sha(str(empty_git_repo)) is None


# ---------------------------------------------------------------------------
# get_branch
# ---------------------------------------------------------------------------


def test_get_branch_returns_string(git_repo):
    branch = get_branch(str(git_repo))
    assert isinstance(branch, str)
    assert len(branch) > 0


def test_get_branch_none_for_non_git(tmp_path):
    assert get_branch(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# get_changed_files_for_commit
# ---------------------------------------------------------------------------


def test_get_changed_files_for_commit_initial(git_repo):
    # Get the first commit SHA
    result = subprocess.run(
        ["git", "log", "--format=%H", "--reverse"],
        cwd=git_repo,
        capture_output=True,
        text=True,
    )
    first_sha = result.stdout.strip().splitlines()[0]
    files = get_changed_files_for_commit(str(git_repo), first_sha)
    assert "README.md" in files
    assert "main.py" in files


def test_get_changed_files_for_commit_second(git_repo):
    result = subprocess.run(
        ["git", "log", "--format=%H"],
        cwd=git_repo,
        capture_output=True,
        text=True,
    )
    latest_sha = result.stdout.strip().splitlines()[0]
    files = get_changed_files_for_commit(str(git_repo), latest_sha)
    assert "utils.py" in files
    assert "README.md" not in files  # not changed in second commit


def test_get_changed_files_invalid_sha_returns_empty(git_repo):
    files = get_changed_files_for_commit(str(git_repo), "0" * 40)
    assert files == []


# ---------------------------------------------------------------------------
# get_recent_commits
# ---------------------------------------------------------------------------


def test_get_recent_commits_returns_commits(git_repo):
    commits = get_recent_commits(str(git_repo), days=30)
    assert len(commits) == 2


def test_get_recent_commits_fields_populated(git_repo):
    commits = get_recent_commits(str(git_repo), days=30)
    for c in commits:
        assert len(c.hash) == 40
        assert c.subject
        assert c.authored_at  # ISO timestamp
        assert c.author_name == "Repomind Test"


def test_get_recent_commits_files_populated(git_repo):
    commits = get_recent_commits(str(git_repo), days=30)
    all_files = [f for c in commits for f in c.files_changed]
    assert "README.md" in all_files
    assert "utils.py" in all_files


def test_get_recent_commits_empty_for_non_git(tmp_path):
    assert get_recent_commits(str(tmp_path)) == []


def test_get_recent_commits_empty_for_no_commits(empty_git_repo):
    assert get_recent_commits(str(empty_git_repo)) == []


def test_get_recent_commits_days_zero_returns_empty(git_repo):
    # days=0 means --since=0 days ago which should return nothing
    # (all commits are older than "now")
    commits = get_recent_commits(str(git_repo), days=0)
    assert commits == []

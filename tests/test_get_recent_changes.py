"""Tests for queries.get_recent_changes (T14)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import RecentChanges, get_recent_changes, run_refresh_index

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)


def _init_git(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "t@t.com")
    _git(path, "config", "user.name", "T")


def _commit(path: Path, message: str, files: list[Path]) -> str:
    """Stage *files* and create a commit; return the short SHA."""
    for f in files:
        _git(path, "add", str(f.relative_to(path)))
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(path),
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    return sha


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def git_repo(tmp_path: Path, storage: Path) -> Path:
    """Git repo with two commits touching different files."""
    r = tmp_path / "repo"
    r.mkdir()
    _init_git(r)

    # commit 1
    f1 = r / "main.py"
    f1.write_text("def main(): pass\n")
    f2 = r / "utils.py"
    f2.write_text("def helper(): pass\n")
    _commit(r, "feat: initial commit", [f1, f2])

    # commit 2 — touches a different file
    f3 = r / "README.md"
    f3.write_text("# Repo\n")
    _commit(r, "docs: add readme", [f3])

    run_refresh_index(str(r))
    return r


@pytest.fixture()
def single_commit_repo(tmp_path: Path, storage: Path) -> Path:
    """Git repo with exactly one commit."""
    r = tmp_path / "single"
    r.mkdir()
    _init_git(r)
    f = r / "app.py"
    f.write_text("x = 1\n")
    _commit(r, "init", [f])
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
    """Non-git repo."""
    r = tmp_path / "plain"
    r.mkdir()
    (r / "util.py").write_text("x = 1\n")
    run_refresh_index(str(r))
    return r


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_no_index_raises_value_error(tmp_path: Path, storage: Path) -> None:
    r = tmp_path / "empty"
    r.mkdir()
    with pytest.raises(ValueError, match="refresh_index"):
        get_recent_changes(str(r))


def test_invalid_path_raises_value_error(storage: Path) -> None:
    with pytest.raises(ValueError):
        get_recent_changes("/nonexistent/totally/fake/path")


# ---------------------------------------------------------------------------
# Return type and basic shape
# ---------------------------------------------------------------------------


def test_returns_recent_changes_instance(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    assert isinstance(result, RecentChanges)


def test_commits_is_list(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    assert isinstance(result.commits, list)


def test_is_git_repo_true_for_git(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    assert result.is_git_repo is True


def test_each_commit_has_required_keys(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    assert len(result.commits) > 0
    for c in result.commits:
        assert "commit_sha" in c
        assert "subject" in c
        assert "author_name" in c
        assert "authored_at" in c
        assert "files" in c


def test_commit_sha_is_string(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    for c in result.commits:
        assert isinstance(c["commit_sha"], str)
        assert len(c["commit_sha"]) > 0


def test_subject_is_string(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    for c in result.commits:
        assert isinstance(c["subject"], str)


def test_files_per_commit_is_list(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    for c in result.commits:
        assert isinstance(c["files"], list)


def test_files_per_commit_are_strings(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    for c in result.commits:
        for f in c["files"]:
            assert isinstance(f, str)


# ---------------------------------------------------------------------------
# Content correctness
# ---------------------------------------------------------------------------


def test_commit_count_matches_indexed(git_repo: Path) -> None:
    """Two commits were created — both should appear."""
    result = get_recent_changes(str(git_repo))
    assert len(result.commits) == 2


def test_commits_ordered_most_recent_first(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    subjects = [c["subject"] for c in result.commits]
    # Most recent commit was "docs: add readme"
    assert subjects[0] == "docs: add readme"
    assert subjects[1] == "feat: initial commit"


def test_commit_subjects_present(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    subjects = {c["subject"] for c in result.commits}
    assert "feat: initial commit" in subjects
    assert "docs: add readme" in subjects


def test_changed_files_associated_with_correct_commit(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    readme_commit = next(c for c in result.commits if c["subject"] == "docs: add readme")
    assert any("README.md" in f for f in readme_commit["files"])


def test_initial_commit_files(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    init_commit = next(c for c in result.commits if c["subject"] == "feat: initial commit")
    file_names = {f.split("/")[-1] for f in init_commit["files"]}
    assert "main.py" in file_names
    assert "utils.py" in file_names


def test_single_commit_repo(single_commit_repo: Path) -> None:
    result = get_recent_changes(str(single_commit_repo))
    assert len(result.commits) == 1
    assert result.commits[0]["subject"] == "init"


# ---------------------------------------------------------------------------
# Non-git degradation
# ---------------------------------------------------------------------------


def test_non_git_repo_returns_instance(plain_repo: Path) -> None:
    result = get_recent_changes(str(plain_repo))
    assert isinstance(result, RecentChanges)


def test_non_git_is_git_repo_false(plain_repo: Path) -> None:
    result = get_recent_changes(str(plain_repo))
    assert result.is_git_repo is False


def test_non_git_commits_empty(plain_repo: Path) -> None:
    result = get_recent_changes(str(plain_repo))
    assert result.commits == []


def test_non_git_provenance_present(plain_repo: Path) -> None:
    result = get_recent_changes(str(plain_repo))
    assert isinstance(result.provenance, dict)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_is_dict(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    assert isinstance(result.provenance, dict)


def test_provenance_has_required_keys(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    for key in (
        "repo_root",
        "indexed_branch",
        "indexed_head_sha",
        "indexed_at",
        "current_branch",
        "current_head_sha",
        "stale",
        "partial",
    ):
        assert key in result.provenance


def test_provenance_stale_false_for_fresh_index(git_repo: Path) -> None:
    result = get_recent_changes(str(git_repo))
    assert result.provenance["stale"] is False


def test_provenance_stale_true_after_new_commit(git_repo: Path, storage: Path) -> None:
    (git_repo / "extra.py").write_text("y = 2\n")
    _git(git_repo, "add", "extra.py")
    _git(git_repo, "commit", "-m", "add extra")
    result = get_recent_changes(str(git_repo))
    assert result.provenance["stale"] is True

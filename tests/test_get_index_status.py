"""Tests for queries.get_index_status: all three freshness states."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.db import open_db
from repomind.queries import IndexStatus, get_index_status
from repomind.refresh import refresh_index

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _init_git(path: Path) -> None:
    """Initialise a minimal git repo and make an initial commit."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    (path / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
    """Non-git repo with isolated storage."""
    r = tmp_path / "plain"
    r.mkdir()
    (r / "main.py").write_text("x = 1\n")
    return r


@pytest.fixture()
def git_repo(tmp_path: Path, storage: Path) -> Path:
    """Git repo with isolated storage."""
    r = tmp_path / "git"
    r.mkdir()
    _init_git(r)
    return r


# ---------------------------------------------------------------------------
# Case 1: missing index
# ---------------------------------------------------------------------------


def test_missing_index_returns_refresh_recommendation(plain_repo: Path) -> None:
    status = get_index_status(str(plain_repo))
    assert status.has_index is False
    assert status.refresh_recommended is True
    assert status.recommended_first_call == "refresh_index"


def test_missing_index_stale_is_false(plain_repo: Path) -> None:
    status = get_index_status(str(plain_repo))
    assert status.stale is False


def test_missing_index_for_git_repo(git_repo: Path) -> None:
    status = get_index_status(str(git_repo))
    assert status.has_index is False
    assert status.recommended_first_call == "refresh_index"
    assert status.is_git_repo is True
    assert status.current_branch is not None
    assert status.current_head_sha is not None


def test_missing_index_provenance_has_no_indexed_fields(plain_repo: Path) -> None:
    status = get_index_status(str(plain_repo))
    prov = status.provenance
    assert prov["indexed_branch"] is None
    assert prov["indexed_head_sha"] is None
    assert prov["indexed_at"] is None


# ---------------------------------------------------------------------------
# Case 2: current index (not stale)
# ---------------------------------------------------------------------------


def test_current_non_git_index_recommends_overview(plain_repo: Path) -> None:
    refresh_index(str(plain_repo))
    status = get_index_status(str(plain_repo))
    assert status.has_index is True
    assert status.stale is False
    assert status.refresh_recommended is False
    assert status.recommended_first_call == "get_repo_overview"


def test_current_git_index_recommends_overview(git_repo: Path) -> None:
    refresh_index(str(git_repo))
    status = get_index_status(str(git_repo))
    assert status.has_index is True
    assert status.stale is False
    assert status.recommended_first_call == "get_repo_overview"


def test_current_index_has_branch_and_head(git_repo: Path) -> None:
    refresh_index(str(git_repo))
    status = get_index_status(str(git_repo))
    assert status.indexed_branch is not None
    assert status.indexed_head_sha is not None
    assert status.current_branch == status.indexed_branch
    assert status.current_head_sha == status.indexed_head_sha


def test_current_index_partial_flag_false(plain_repo: Path) -> None:
    refresh_index(str(plain_repo))
    status = get_index_status(str(plain_repo))
    assert status.partial is False


def test_current_index_provenance_stale_false(git_repo: Path) -> None:
    refresh_index(str(git_repo))
    status = get_index_status(str(git_repo))
    assert status.provenance["stale"] is False


def test_current_non_git_is_git_repo_false(plain_repo: Path) -> None:
    refresh_index(str(plain_repo))
    status = get_index_status(str(plain_repo))
    assert status.is_git_repo is False
    assert status.current_branch is None
    assert status.current_head_sha is None


# ---------------------------------------------------------------------------
# Case 3: stale index (branch or HEAD differs)
# ---------------------------------------------------------------------------


def test_stale_head_sha_returns_refresh(git_repo: Path) -> None:
    refresh_index(str(git_repo))

    # Simulate HEAD moving by overwriting the stored head_sha.
    conn = open_db(str(git_repo))
    conn.execute("UPDATE repo_index SET head_sha = 'deadbeef'")
    conn.commit()
    conn.close()

    status = get_index_status(str(git_repo))
    assert status.stale is True
    assert status.refresh_recommended is True
    assert status.recommended_first_call == "refresh_index"


def test_stale_branch_returns_refresh(git_repo: Path) -> None:
    refresh_index(str(git_repo))

    conn = open_db(str(git_repo))
    conn.execute("UPDATE repo_index SET branch_name = 'other-branch'")
    conn.commit()
    conn.close()

    status = get_index_status(str(git_repo))
    assert status.stale is True
    assert status.recommended_first_call == "refresh_index"


def test_stale_provenance_reflects_both_states(git_repo: Path) -> None:
    refresh_index(str(git_repo))
    real_head = get_index_status(str(git_repo)).current_head_sha

    conn = open_db(str(git_repo))
    conn.execute("UPDATE repo_index SET head_sha = 'aaa111'")
    conn.commit()
    conn.close()

    status = get_index_status(str(git_repo))
    prov = status.provenance
    assert prov["indexed_head_sha"] == "aaa111"
    assert prov["current_head_sha"] == real_head
    assert prov["stale"] is True


def test_non_git_repo_never_stale_even_after_refresh(plain_repo: Path) -> None:
    refresh_index(str(plain_repo))
    # Corrupt the stored head_sha (there is none for non-git, but set it anyway).
    conn = open_db(str(plain_repo))
    conn.execute("UPDATE repo_index SET head_sha = 'fake'")
    conn.commit()
    conn.close()

    status = get_index_status(str(plain_repo))
    # Non-git repos cannot be stale — no branch/HEAD to compare.
    assert status.stale is False
    assert status.recommended_first_call == "get_repo_overview"


# ---------------------------------------------------------------------------
# Return type and provenance shape
# ---------------------------------------------------------------------------


def test_returns_index_status_instance(plain_repo: Path) -> None:
    status = get_index_status(str(plain_repo))
    assert isinstance(status, IndexStatus)


def test_provenance_has_all_required_keys(plain_repo: Path) -> None:
    refresh_index(str(plain_repo))
    prov = get_index_status(str(plain_repo)).provenance
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
        assert key in prov, f"Missing provenance key: {key}"


def test_provenance_repo_root_is_absolute(plain_repo: Path) -> None:
    refresh_index(str(plain_repo))
    prov = get_index_status(str(plain_repo)).provenance
    import os

    assert os.path.isabs(prov["repo_root"])


def test_invalid_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        get_index_status(str(tmp_path / "does_not_exist"))


# ---------------------------------------------------------------------------
# Partial index flag round-trips
# ---------------------------------------------------------------------------


def test_partial_flag_round_trips(plain_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import repomind.refresh as rm

    monkeypatch.setattr(rm, "_PARTIAL_FILE_THRESHOLD", 0)
    monkeypatch.setattr(rm, "_PARTIAL_MAX_DEPTH", 0)

    refresh_index(str(plain_repo))
    status = get_index_status(str(plain_repo))
    assert status.partial is True
    assert status.provenance["partial"] is True

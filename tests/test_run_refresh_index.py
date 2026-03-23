"""Tests for queries.run_refresh_index: structured result and provenance."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.db import open_db
from repomind.queries import RefreshIndexResult, run_refresh_index

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _init_git(path: Path) -> None:
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
    r = tmp_path / "plain"
    r.mkdir()
    (r / "main.py").write_text("x = 1\n")
    (r / "README.md").write_text("# Readme\n")
    return r


@pytest.fixture()
def git_repo(tmp_path: Path, storage: Path) -> Path:
    r = tmp_path / "git"
    r.mkdir()
    _init_git(r)
    return r


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_success_status_ok(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.status == "ok"
    assert result.refreshed is True


def test_success_returns_refresh_index_result(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert isinstance(result, RefreshIndexResult)


def test_success_files_indexed_positive(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.files_indexed > 0


def test_success_directories_indexed_positive(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.directories_indexed > 0


def test_success_no_error_message(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.error_message is None


def test_success_partial_false_for_small_repo(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.partial is False
    assert result.partial_reason is None


def test_success_creates_queryable_db(plain_repo: Path) -> None:
    run_refresh_index(str(plain_repo))
    conn = open_db(str(plain_repo))
    count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    assert count > 0


# ---------------------------------------------------------------------------
# Provenance: success path
# ---------------------------------------------------------------------------


def test_success_provenance_stale_false(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.provenance["stale"] is False


def test_success_provenance_partial_false(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.provenance["partial"] is False


def test_success_provenance_has_indexed_at(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.provenance["indexed_at"] is not None


def test_success_provenance_repo_root_correct(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.provenance["repo_root"] == str(plain_repo)


def test_success_provenance_has_all_keys(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
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
        assert key in result.provenance, f"Missing provenance key: {key}"


# ---------------------------------------------------------------------------
# Git repo: branch and HEAD in provenance
# ---------------------------------------------------------------------------


def test_git_refresh_provenance_branch_populated(git_repo: Path) -> None:
    result = run_refresh_index(str(git_repo))
    assert result.provenance["indexed_branch"] is not None
    assert result.provenance["current_branch"] is not None
    assert result.provenance["indexed_branch"] == result.provenance["current_branch"]


def test_git_refresh_provenance_head_sha_populated(git_repo: Path) -> None:
    result = run_refresh_index(str(git_repo))
    assert result.provenance["indexed_head_sha"] is not None
    assert result.provenance["current_head_sha"] is not None
    assert result.provenance["indexed_head_sha"] == result.provenance["current_head_sha"]


def test_git_refresh_provenance_stale_false_after_fresh_index(git_repo: Path) -> None:
    result = run_refresh_index(str(git_repo))
    assert result.provenance["stale"] is False


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


def test_failure_status_error(
    plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repomind.refresh as rm

    monkeypatch.setattr(
        rm,
        "_validate_temp_db",
        lambda *_: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )
    result = run_refresh_index(str(plain_repo))
    assert result.status == "error"
    assert result.refreshed is False


def test_failure_error_message_populated(
    plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repomind.refresh as rm

    monkeypatch.setattr(
        rm,
        "_validate_temp_db",
        lambda *_: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )
    result = run_refresh_index(str(plain_repo))
    assert result.error_message is not None
    assert "injected failure" in result.error_message


def test_failure_files_indexed_zero(
    plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repomind.refresh as rm

    monkeypatch.setattr(
        rm,
        "_validate_temp_db",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = run_refresh_index(str(plain_repo))
    assert result.files_indexed == 0


def test_failure_after_good_index_provenance_reflects_existing(
    plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a good refresh followed by a failed refresh, provenance shows
    the existing (still-good) index — not empty."""
    run_refresh_index(str(plain_repo))

    import repomind.refresh as rm

    monkeypatch.setattr(
        rm,
        "_validate_temp_db",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = run_refresh_index(str(plain_repo))
    assert result.status == "error"
    # The good index from the first refresh is still in place.
    assert result.provenance["indexed_at"] is not None


def test_failure_no_existing_index_provenance_empty(
    plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure with no prior index → provenance shows no indexed metadata."""
    import repomind.refresh as rm

    monkeypatch.setattr(
        rm,
        "_validate_temp_db",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = run_refresh_index(str(plain_repo))
    assert result.status == "error"
    assert result.provenance["indexed_at"] is None
    assert result.provenance["indexed_branch"] is None


# ---------------------------------------------------------------------------
# Partial indexing
# ---------------------------------------------------------------------------


def test_partial_flag_surfaces_in_result(
    plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "0")
    result = run_refresh_index(str(plain_repo))
    assert result.partial is True
    assert result.provenance["partial"] is True


# ---------------------------------------------------------------------------
# Invalid path
# ---------------------------------------------------------------------------


def test_invalid_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_refresh_index(str(tmp_path / "no_such_dir"))

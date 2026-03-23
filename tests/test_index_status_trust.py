"""Tests for I2-T6 trust signals in get_index_status.

Covers: age_seconds, indexed_file_count, quality_signal ("full" | "partial" |
"degraded"), and their presence in the provenance dict.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import get_index_status, run_refresh_index

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_git(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, msg: str = "init") -> None:
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg, "--allow-empty"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def indexed_repo(tmp_path: Path, storage: Path) -> Path:
    """3-file Git repo that has been indexed."""
    r = tmp_path / "repo"
    r.mkdir()
    _init_git(r)
    for i in range(3):
        (r / f"file{i}.py").write_text(f"x = {i}\n")
    _commit_all(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def partial_indexed_repo(
    tmp_path: Path, storage: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """6-file repo indexed with REPOMIND_FILE_LIMIT=3 so it becomes partial."""
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    r = tmp_path / "partial_repo"
    r.mkdir()
    _init_git(r)
    for i in range(6):
        (r / f"file{i}.py").write_text(f"x = {i}\n")
    _commit_all(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def empty_dir(tmp_path: Path, storage: Path) -> Path:
    """Directory with no index."""
    r = tmp_path / "no_index"
    r.mkdir()
    return r


# ---------------------------------------------------------------------------
# quality_signal
# ---------------------------------------------------------------------------


def test_quality_signal_full_for_complete_index(indexed_repo: Path) -> None:
    status = get_index_status(str(indexed_repo))
    assert status.quality_signal == "full"


def test_quality_signal_partial_for_partial_index(partial_indexed_repo: Path) -> None:
    status = get_index_status(str(partial_indexed_repo))
    assert status.quality_signal == "partial"


def test_quality_signal_degraded_when_no_index(empty_dir: Path) -> None:
    status = get_index_status(str(empty_dir))
    assert status.quality_signal == "degraded"


def test_quality_signal_in_provenance_full(indexed_repo: Path) -> None:
    status = get_index_status(str(indexed_repo))
    assert status.provenance["quality_signal"] == "full"


def test_quality_signal_in_provenance_partial(partial_indexed_repo: Path) -> None:
    status = get_index_status(str(partial_indexed_repo))
    assert status.provenance["quality_signal"] == "partial"


def test_quality_signal_in_provenance_degraded(empty_dir: Path) -> None:
    status = get_index_status(str(empty_dir))
    assert status.provenance["quality_signal"] == "degraded"


# ---------------------------------------------------------------------------
# age_seconds
# ---------------------------------------------------------------------------


def test_age_seconds_none_when_no_index(empty_dir: Path) -> None:
    status = get_index_status(str(empty_dir))
    assert status.age_seconds is None


def test_age_seconds_non_negative_after_index(indexed_repo: Path) -> None:
    status = get_index_status(str(indexed_repo))
    assert status.age_seconds is not None
    assert status.age_seconds >= 0


def test_age_seconds_small_for_fresh_index(indexed_repo: Path) -> None:
    """Index was just created; age should be under 60 seconds."""
    status = get_index_status(str(indexed_repo))
    assert status.age_seconds is not None
    assert status.age_seconds < 60


# ---------------------------------------------------------------------------
# indexed_file_count
# ---------------------------------------------------------------------------


def test_indexed_file_count_none_when_no_index(empty_dir: Path) -> None:
    status = get_index_status(str(empty_dir))
    assert status.indexed_file_count is None


def test_indexed_file_count_matches_files_indexed(indexed_repo: Path) -> None:
    result = run_refresh_index(str(indexed_repo))
    status = get_index_status(str(indexed_repo))
    assert status.indexed_file_count == result.files_indexed


def test_indexed_file_count_positive_for_non_empty_repo(indexed_repo: Path) -> None:
    status = get_index_status(str(indexed_repo))
    assert status.indexed_file_count is not None
    assert status.indexed_file_count > 0


def test_indexed_file_count_capped_for_partial_index(
    partial_indexed_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partial index file count should be at most the cap value."""
    status = get_index_status(str(partial_indexed_repo))
    assert status.indexed_file_count is not None
    assert status.indexed_file_count <= 3


# ---------------------------------------------------------------------------
# Propagation: quality_signal appears in all query-function provenances
# ---------------------------------------------------------------------------


def test_quality_signal_propagates_through_all_query_provenances(
    indexed_repo: Path,
) -> None:
    """quality_signal must appear in provenance for every query tool, not just status."""
    from repomind.queries import (
        get_critical_files,
        get_directory_map,
        get_edit_suggestions,
        get_recent_changes,
        get_repo_overview,
    )

    for prov in [
        get_repo_overview(str(indexed_repo)).provenance,
        get_directory_map(str(indexed_repo)).provenance,
        get_critical_files(str(indexed_repo)).provenance,
        get_recent_changes(str(indexed_repo)).provenance,
        get_edit_suggestions(str(indexed_repo), task="file").provenance,
    ]:
        assert "quality_signal" in prov
        assert prov["quality_signal"] == "full"

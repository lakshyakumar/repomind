"""Tests for configurable file/depth caps and structured partial reporting (I2-T5).

Acceptance criteria:
- REPOMIND_FILE_LIMIT=3 triggers partial indexing on a 6-file repo
- REPOMIND_MAX_DEPTH=0 independently triggers partial when files exist below root
- partial_reason is a structured dict: {"cap_type": ..., "cap_value": ...}
- partial_reason appears in provenance for all query responses when partial=True
- partial_reason cap_type distinguishes "file_count" from "depth"
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import (
    get_critical_files,
    get_directory_map,
    get_edit_suggestions,
    get_index_status,
    get_recent_changes,
    get_repo_overview,
    run_refresh_index,
)
from repomind.refresh import refresh_index

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def flat_repo(tmp_path: Path, storage: Path) -> Path:
    """6-file Git repo with no subdirectories."""
    r = tmp_path / "flat"
    r.mkdir()
    _init_git(r)
    for i in range(6):
        (r / f"module_{i}.py").write_text(f"# Module {i}\nx = {i}\n")
    _commit_all(r, "init")
    return r


@pytest.fixture()
def nested_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with files at root (depth 0) and in a subdirectory (depth 1)."""
    r = tmp_path / "nested"
    r.mkdir()
    _init_git(r)
    (r / "root.py").write_text("# root\n")
    sub = r / "sub"
    sub.mkdir()
    (sub / "nested.py").write_text("# nested\n")
    _commit_all(r, "init")
    return r


# ---------------------------------------------------------------------------
# file_count cap
# ---------------------------------------------------------------------------


def test_file_limit_triggers_partial(
    flat_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    result = refresh_index(str(flat_repo))
    assert result.partial is True


def test_file_limit_partial_reason_cap_type(
    flat_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    result = refresh_index(str(flat_repo))
    assert isinstance(result.partial_reason, dict)
    assert result.partial_reason["cap_type"] == "file_count"
    assert result.partial_reason["cap_value"] == 3


def test_file_limit_partial_reason_in_provenance(
    flat_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    result = run_refresh_index(str(flat_repo))
    assert result.provenance["partial"] is True
    assert result.provenance["partial_reason"]["cap_type"] == "file_count"


def test_file_limit_partial_reason_in_all_queries(
    flat_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    run_refresh_index(str(flat_repo))
    for prov in [
        get_repo_overview(str(flat_repo)).provenance,
        get_directory_map(str(flat_repo)).provenance,
        get_critical_files(str(flat_repo)).provenance,
        get_recent_changes(str(flat_repo)).provenance,
        get_edit_suggestions(str(flat_repo), task="module").provenance,
    ]:
        assert prov["partial"] is True
        assert prov["partial_reason"]["cap_type"] == "file_count"


# ---------------------------------------------------------------------------
# depth cap
# ---------------------------------------------------------------------------


def test_depth_cap_triggers_partial_independently(
    nested_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REPOMIND_MAX_DEPTH=0 excludes depth-1 files even without a file-count cap."""
    monkeypatch.setenv("REPOMIND_MAX_DEPTH", "0")
    result = refresh_index(str(nested_repo))
    assert result.partial is True


def test_depth_cap_partial_reason_cap_type(
    nested_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_MAX_DEPTH", "0")
    result = refresh_index(str(nested_repo))
    assert isinstance(result.partial_reason, dict)
    assert result.partial_reason["cap_type"] == "depth"
    assert result.partial_reason["cap_value"] == 0


def test_depth_cap_excludes_deep_files(
    nested_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With max_depth=0 only root-level files should be indexed."""
    monkeypatch.setenv("REPOMIND_MAX_DEPTH", "0")
    result = refresh_index(str(nested_repo))
    assert result.files_indexed == 1  # only root.py


def test_depth_cap_partial_reason_in_provenance(
    nested_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_MAX_DEPTH", "0")
    result = run_refresh_index(str(nested_repo))
    assert result.provenance["partial"] is True
    assert result.provenance["partial_reason"]["cap_type"] == "depth"


# ---------------------------------------------------------------------------
# No cap — partial_reason absent
# ---------------------------------------------------------------------------


def test_no_cap_partial_reason_absent_from_provenance(
    flat_repo: Path,
) -> None:
    """When no cap fires, partial_reason must not appear in provenance."""
    result = run_refresh_index(str(flat_repo))
    assert result.partial is False
    assert "partial_reason" not in result.provenance


def test_no_cap_partial_reason_none(flat_repo: Path) -> None:
    result = refresh_index(str(flat_repo))
    assert result.partial_reason is None


# ---------------------------------------------------------------------------
# partial_reason persists in index_status
# ---------------------------------------------------------------------------


def test_partial_reason_survives_round_trip(
    flat_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """partial_reason written during refresh must be readable via get_index_status."""
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    run_refresh_index(str(flat_repo))
    status = get_index_status(str(flat_repo))
    assert status.partial is True
    assert status.provenance["partial_reason"]["cap_type"] == "file_count"

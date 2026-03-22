"""Tests for queries.get_critical_files (T13)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import CriticalFiles, get_critical_files, run_refresh_index

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
    (path / ".keep").write_text("")
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
def rich_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with manifest, config, entrypoint, source, and test files."""
    r = tmp_path / "repo"
    r.mkdir()

    # manifest — should rank high
    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    # entrypoint
    (r / "main.py").write_text("def main():\n    pass\n" * 30)

    # config
    (r / "Makefile").write_text("test:\n\tpytest\n")

    # source files
    src = r / "src"
    src.mkdir()
    (src / "core.py").write_text("class Core:\n    pass\n" * 25)
    (src / "utils.py").write_text("def helper(): pass\n" * 10)

    # tests
    tests = r / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text("def test_x(): pass\n" * 5)

    _init_git(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
    """Minimal non-git repo."""
    r = tmp_path / "plain"
    r.mkdir()
    sub = r / "lib"
    sub.mkdir()
    (sub / "util.py").write_text("x = 1\n")
    run_refresh_index(str(r))
    return r


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_no_index_raises_value_error(tmp_path: Path, storage: Path) -> None:
    r = tmp_path / "empty"
    r.mkdir()
    with pytest.raises(ValueError, match="refresh_index"):
        get_critical_files(str(r))


def test_invalid_path_raises_value_error(storage: Path) -> None:
    with pytest.raises(ValueError):
        get_critical_files("/nonexistent/totally/fake/path")


# ---------------------------------------------------------------------------
# Return type and basic shape
# ---------------------------------------------------------------------------


def test_returns_critical_files_instance(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    assert isinstance(result, CriticalFiles)


def test_files_is_list(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    assert isinstance(result.files, list)


def test_each_file_has_required_keys(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    assert len(result.files) > 0
    for f in result.files:
        assert "path" in f
        assert "file_type" in f
        assert "importance_score" in f
        assert "reason" in f


def test_path_is_string(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    for f in result.files:
        assert isinstance(f["path"], str)


def test_importance_score_is_float(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    for f in result.files:
        assert isinstance(f["importance_score"], float)


def test_reason_is_string(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    for f in result.files:
        assert isinstance(f["reason"], str)
        assert len(f["reason"]) > 0


# ---------------------------------------------------------------------------
# Filtering: generated files excluded
# ---------------------------------------------------------------------------


def test_generated_files_excluded(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    for f in result.files:
        assert f["file_type"] != "generated"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_files_ordered_by_importance_score_descending(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    scores = [f["importance_score"] for f in result.files]
    assert scores == sorted(scores, reverse=True)


def test_manifest_ranks_near_top(rich_repo: Path) -> None:
    """pyproject.toml (manifest) should appear in the top 3."""
    result = get_critical_files(str(rich_repo))
    top_paths = [f["path"] for f in result.files[:3]]
    assert any("pyproject.toml" in p for p in top_paths)


# ---------------------------------------------------------------------------
# Reason derivation
# ---------------------------------------------------------------------------


def test_manifest_reason(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    manifest = next(f for f in result.files if f["file_type"] == "manifest")
    assert manifest["reason"] == "Project manifest"


def test_entrypoint_reason(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    entrypoints = [f for f in result.files if f["file_type"] == "entrypoint"]
    if entrypoints:
        assert entrypoints[0]["reason"] == "Application entrypoint"


def test_source_reason(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    sources = [f for f in result.files if f["file_type"] == "source"]
    if sources:
        assert sources[0]["reason"] == "Source file"


def test_test_reason(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    tests = [f for f in result.files if f["file_type"] == "test"]
    if tests:
        assert tests[0]["reason"] == "Test file"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_is_dict(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    assert isinstance(result.provenance, dict)


def test_provenance_has_required_keys(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
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


def test_provenance_stale_false_for_fresh_index(rich_repo: Path) -> None:
    result = get_critical_files(str(rich_repo))
    assert result.provenance["stale"] is False


def test_provenance_stale_true_after_new_commit(
    rich_repo: Path, storage: Path
) -> None:
    (rich_repo / "extra.py").write_text("y = 2\n")
    subprocess.run(
        ["git", "add", "extra.py"],
        cwd=str(rich_repo),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add extra"],
        cwd=str(rich_repo),
        capture_output=True,
        check=True,
    )
    result = get_critical_files(str(rich_repo))
    assert result.provenance["stale"] is True


def test_non_git_repo_works(plain_repo: Path) -> None:
    result = get_critical_files(str(plain_repo))
    assert isinstance(result, CriticalFiles)
    assert result.provenance["stale"] is False

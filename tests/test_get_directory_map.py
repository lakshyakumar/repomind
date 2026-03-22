"""Tests for queries.get_directory_map (T12)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import DirectoryMap, get_directory_map, run_refresh_index

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
def multi_dir_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with a nested directory tree for ordering/filtering tests."""
    r = tmp_path / "repo"
    r.mkdir()

    # src/ — application code (higher scoring)
    src = r / "src"
    src.mkdir()
    (src / "main.py").write_text("def main():\n    pass\n" * 40)
    (src / "utils.py").write_text("def helper():\n    pass\n" * 20)

    # src/handlers/ — nested
    handlers = src / "handlers"
    handlers.mkdir()
    (handlers / "api.py").write_text("def handle():\n    pass\n" * 15)

    # tests/
    tests = r / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_x(): pass\n" * 10)

    # docs/
    docs = r / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n" * 10)

    _init_git(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
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
        get_directory_map(str(r))


def test_invalid_path_raises_value_error(storage: Path) -> None:
    with pytest.raises(ValueError):
        get_directory_map("/nonexistent/totally/fake/path")


# ---------------------------------------------------------------------------
# Return type and basic shape
# ---------------------------------------------------------------------------


def test_returns_directory_map_instance(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    assert isinstance(result, DirectoryMap)


def test_directories_is_list(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    assert isinstance(result.directories, list)


def test_each_directory_has_required_keys(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    assert len(result.directories) > 0
    for d in result.directories:
        assert "path" in d
        assert "role" in d
        assert "summary" in d
        assert "representative_files" in d
        assert "importance_score" in d


def test_representative_files_is_list(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    for d in result.directories:
        assert isinstance(d["representative_files"], list)


def test_summary_is_none_in_v1(multi_dir_repo: Path) -> None:
    """v1 does not compute directory summaries; summary must be None."""
    result = get_directory_map(str(multi_dir_repo))
    for d in result.directories:
        assert d["summary"] is None


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_directories_ordered_by_importance_score_descending(
    multi_dir_repo: Path,
) -> None:
    result = get_directory_map(str(multi_dir_repo))
    scores = [d["importance_score"] for d in result.directories]
    assert scores == sorted(scores, reverse=True)


def test_src_directory_present(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    paths = [d["path"] for d in result.directories]
    assert "src" in paths


def test_all_indexed_directories_returned_without_filter(
    multi_dir_repo: Path,
) -> None:
    """Without path_filter, all indexed directories are returned."""
    result = get_directory_map(str(multi_dir_repo))
    paths = {d["path"] for d in result.directories}
    # Expect at least src, src/handlers, tests, docs.
    assert {"src", "src/handlers", "tests", "docs"}.issubset(paths)


# ---------------------------------------------------------------------------
# path_filter
# ---------------------------------------------------------------------------


def test_path_filter_restricts_to_prefix(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo), path_filter="src")
    paths = [d["path"] for d in result.directories]
    for p in paths:
        assert p == "src" or p.startswith("src/")


def test_path_filter_includes_exact_match(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo), path_filter="src")
    paths = [d["path"] for d in result.directories]
    assert "src" in paths


def test_path_filter_includes_children(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo), path_filter="src")
    paths = [d["path"] for d in result.directories]
    assert "src/handlers" in paths


def test_path_filter_excludes_non_matching(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo), path_filter="src")
    paths = [d["path"] for d in result.directories]
    assert "tests" not in paths
    assert "docs" not in paths


def test_path_filter_trailing_slash_normalized(multi_dir_repo: Path) -> None:
    """'src/' and 'src' should produce identical results."""
    with_slash = get_directory_map(str(multi_dir_repo), path_filter="src/")
    without_slash = get_directory_map(str(multi_dir_repo), path_filter="src")
    assert [d["path"] for d in with_slash.directories] == [
        d["path"] for d in without_slash.directories
    ]


def test_path_filter_no_match_returns_empty_list(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo), path_filter="nonexistent")
    assert result.directories == []


def test_path_filter_none_returns_all(multi_dir_repo: Path) -> None:
    all_dirs = get_directory_map(str(multi_dir_repo), path_filter=None)
    unfiltered = get_directory_map(str(multi_dir_repo))
    assert len(all_dirs.directories) == len(unfiltered.directories)


# ---------------------------------------------------------------------------
# representative_files content
# ---------------------------------------------------------------------------


def test_representative_files_are_strings(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    for d in result.directories:
        for f in d["representative_files"]:
            assert isinstance(f, str)


def test_representative_files_belong_to_directory(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    for d in result.directories:
        dir_path = d["path"]
        for f in d["representative_files"]:
            # Root directory (path == "") contains top-level files; any relative
            # path without a leading slash is valid.
            if dir_path == "":
                assert not f.startswith("/"), f"Expected relative path, got {f!r}"
            else:
                assert f.startswith(dir_path + "/") or f == dir_path


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_is_dict(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    assert isinstance(result.provenance, dict)


def test_provenance_has_required_keys(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
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


def test_provenance_stale_false_for_fresh_index(multi_dir_repo: Path) -> None:
    result = get_directory_map(str(multi_dir_repo))
    assert result.provenance["stale"] is False


def test_provenance_stale_true_after_new_commit(
    multi_dir_repo: Path, storage: Path
) -> None:
    (multi_dir_repo / "extra.py").write_text("y = 2\n")
    subprocess.run(
        ["git", "add", "extra.py"],
        cwd=str(multi_dir_repo),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add extra"],
        cwd=str(multi_dir_repo),
        capture_output=True,
        check=True,
    )
    result = get_directory_map(str(multi_dir_repo))
    assert result.provenance["stale"] is True


def test_non_git_repo_works(plain_repo: Path) -> None:
    result = get_directory_map(str(plain_repo))
    assert isinstance(result, DirectoryMap)
    assert result.provenance["stale"] is False

"""Tests for queries.get_repo_overview (T11)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import RepoOverview, get_repo_overview, run_refresh_index

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
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
def git_repo(tmp_path: Path, storage: Path) -> Path:
    """Minimal git repo with a few indexed files."""
    r = tmp_path / "git"
    r.mkdir()
    # manifest
    (r / "pyproject.toml").write_text("[project]\nname='myrepo'\n")
    # source files
    src = r / "src"
    src.mkdir()
    (src / "main.py").write_text("# mcp server\ndef main():\n    pass\n" * 30)
    (src / "utils.py").write_text("def helper():\n    pass\n" * 10)
    # docs
    (r / "README.md").write_text("# myrepo\n" * 5)
    _init_git(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
    """Non-git repo with Python files."""
    r = tmp_path / "plain"
    r.mkdir()
    (r / "pyproject.toml").write_text("[project]\nname='plain'\n")
    (r / "app.py").write_text("x = 1\n")
    run_refresh_index(str(r))
    return r


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_no_index_raises_value_error(tmp_path: Path, storage: Path) -> None:
    r = tmp_path / "empty"
    r.mkdir()
    with pytest.raises(ValueError, match="refresh_index"):
        get_repo_overview(str(r))


def test_invalid_path_raises_value_error(storage: Path) -> None:
    with pytest.raises(ValueError):
        get_repo_overview("/nonexistent/totally/fake/path")


# ---------------------------------------------------------------------------
# Return type and basic shape
# ---------------------------------------------------------------------------


def test_returns_repo_overview_instance(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert isinstance(result, RepoOverview)


def test_repo_name_matches_directory_name(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert result.repo_name == "git"


def test_repo_root_is_resolved_absolute(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert result.repo_root == str(git_repo.resolve())


def test_is_git_repo_true_for_git_repo(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert result.is_git_repo is True


def test_is_git_repo_false_for_plain_repo(plain_repo: Path) -> None:
    result = get_repo_overview(str(plain_repo))
    assert result.is_git_repo is False


# ---------------------------------------------------------------------------
# top_directories
# ---------------------------------------------------------------------------


def test_top_directories_is_list(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert isinstance(result.top_directories, list)


def test_top_directories_have_required_keys(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    for d in result.top_directories:
        assert "path" in d
        assert "role" in d
        assert "importance_score" in d


def test_top_directories_ordered_by_score_descending(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    scores = [d["importance_score"] for d in result.top_directories]
    assert scores == sorted(scores, reverse=True)


def test_top_directories_limited_to_ten(tmp_path: Path, storage: Path) -> None:
    """Repos with >10 directories return at most 10 in the overview."""
    r = tmp_path / "big"
    r.mkdir()
    for i in range(15):
        d = r / f"pkg{i}"
        d.mkdir()
        (d / "mod.py").write_text(f"# module {i}\n" * 5)
    run_refresh_index(str(r))
    result = get_repo_overview(str(r))
    assert len(result.top_directories) <= 10


# ---------------------------------------------------------------------------
# critical_files
# ---------------------------------------------------------------------------


def test_critical_files_is_list(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert isinstance(result.critical_files, list)


def test_critical_files_have_required_keys(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    for f in result.critical_files:
        assert "path" in f
        assert "file_type" in f
        assert "importance_score" in f


def test_critical_files_ordered_by_score_descending(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    scores = [f["importance_score"] for f in result.critical_files]
    assert scores == sorted(scores, reverse=True)


def test_critical_files_excludes_generated(tmp_path: Path, storage: Path) -> None:
    """Generated files must not appear in critical_files."""
    r = tmp_path / "gen"
    r.mkdir()
    (r / "main.py").write_text("x = 1\n")
    # A minified JS file is classified as generated.
    (r / "bundle.min.js").write_text("!function(){}" * 20)
    run_refresh_index(str(r))
    result = get_repo_overview(str(r))
    types = [f["file_type"] for f in result.critical_files]
    assert "generated" not in types


def test_critical_files_manifest_appears_near_top(git_repo: Path) -> None:
    """pyproject.toml should be in the top files (high base score)."""
    result = get_repo_overview(str(git_repo))
    paths = [f["path"] for f in result.critical_files]
    assert "pyproject.toml" in paths
    # Manifest should rank first or second given its high base score.
    assert paths.index("pyproject.toml") <= 1


def test_critical_files_limited_to_ten(tmp_path: Path, storage: Path) -> None:
    r = tmp_path / "many"
    r.mkdir()
    for i in range(20):
        (r / f"file{i}.py").write_text(f"# f{i}\n" * 5)
    run_refresh_index(str(r))
    result = get_repo_overview(str(r))
    assert len(result.critical_files) <= 10


# ---------------------------------------------------------------------------
# stack_hints
# ---------------------------------------------------------------------------


def test_stack_hints_is_list(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert isinstance(result.stack_hints, list)


def test_stack_hints_detects_python(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert "python" in result.stack_hints


def test_stack_hints_detects_mcp_from_tokens(git_repo: Path) -> None:
    """src/main.py has '# mcp server' which should produce an 'mcp' header token."""
    result = get_repo_overview(str(git_repo))
    assert "mcp" in result.stack_hints


def test_stack_hints_deduplicates_languages(tmp_path: Path, storage: Path) -> None:
    """Both .ts and .tsx files should produce a single 'typescript' hint."""
    r = tmp_path / "ts"
    r.mkdir()
    (r / "app.ts").write_text("const x = 1;\n" * 5)
    (r / "comp.tsx").write_text("export default () => null;\n" * 5)
    run_refresh_index(str(r))
    result = get_repo_overview(str(r))
    assert result.stack_hints.count("typescript") == 1


def test_stack_hints_caps_languages_at_three(tmp_path: Path, storage: Path) -> None:
    r = tmp_path / "poly"
    r.mkdir()
    for ext, content in [
        ("main.py", "x=1\n"),
        ("app.ts", "const x=1;\n"),
        ("main.go", "package main\n"),
        ("Lib.java", "class Lib {}\n"),
    ]:
        (r / ext).write_text(content * 10)
    run_refresh_index(str(r))
    result = get_repo_overview(str(r))
    lang_map = {"python", "typescript", "go", "java"}
    lang_hints = [h for h in result.stack_hints if h in lang_map]
    assert len(lang_hints) <= 3


def test_stack_hints_no_recognizable_extensions(tmp_path: Path, storage: Path) -> None:
    """Repos with only unknown extensions return an empty hints list."""
    r = tmp_path / "unknown"
    r.mkdir()
    (r / "data.xyz").write_text("some data\n")
    run_refresh_index(str(r))
    result = get_repo_overview(str(r))
    assert result.stack_hints == []


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_is_dict(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
    assert isinstance(result.provenance, dict)


def test_provenance_has_required_keys(git_repo: Path) -> None:
    result = get_repo_overview(str(git_repo))
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
    result = get_repo_overview(str(git_repo))
    assert result.provenance["stale"] is False


def test_provenance_stale_true_when_head_advanced(
    git_repo: Path, storage: Path
) -> None:
    """After adding a new commit, provenance.stale should be True."""
    (git_repo / "extra.py").write_text("y = 2\n")
    subprocess.run(
        ["git", "add", "extra.py"], cwd=str(git_repo), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "add extra"],
        cwd=str(git_repo),
        capture_output=True,
        check=True,
    )
    # Index still reflects old HEAD → stale.
    result = get_repo_overview(str(git_repo))
    assert result.provenance["stale"] is True


def test_provenance_partial_reflected(tmp_path: Path, storage: Path) -> None:
    import repomind.refresh as rm

    r = tmp_path / "partial"
    r.mkdir()
    (r / "main.py").write_text("x=1\n")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rm, "_PARTIAL_FILE_THRESHOLD", 0)
    try:
        run_refresh_index(str(r))
    finally:
        monkeypatch.undo()

    result = get_repo_overview(str(r))
    assert result.provenance["partial"] is True

"""Tests for repomind.refresh: refresh pipeline, atomic swap, partial indexing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from repomind.db import get_db_path, get_tmp_db_path, open_db
from repomind.refresh import refresh_index

# ---------------------------------------------------------------------------
# Fixture repo builder
# ---------------------------------------------------------------------------


def _make_repo(base: Path, git: bool = False) -> Path:
    """Create a small deterministic fixture repo under *base*."""
    base.mkdir(parents=True, exist_ok=True)
    # Root-level files
    (base / "README.md").write_text("# My Project\nA sample repo.\n")
    (base / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nversion = '0.1.0'\n"
    )
    (base / ".gitignore").write_text("__pycache__/\n*.pyc\n")

    # Source
    src = base / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "# Entry point\n" + "x = 1\n" * 50
    )
    (src / "utils.py").write_text(
        "# Utility helpers\n" + "def helper(): pass\n" * 40
    )

    # Tests
    tests = base / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_x(): assert True\n" * 30)

    # Noisy files that should be classified as generated
    (base / "package-lock.json").write_text("{}")

    # Skipped directory — must not appear in index
    nm = base / "node_modules"
    nm.mkdir()
    (nm / "lodash.js").write_text("module.exports = {}")

    if git:
        import subprocess

        subprocess.run(["git", "init"], cwd=str(base), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(base),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(base),
            capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=str(base), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=str(base),
            capture_output=True,
        )

    return base


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Small non-git fixture repo with REPOMIND_STORAGE_ROOT isolated."""
    storage = tmp_path / "repomind_storage"
    storage.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(storage))
    return _make_repo(tmp_path / "repo")


@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Small git fixture repo with isolated storage."""
    storage = tmp_path / "repomind_storage"
    storage.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(storage))
    return _make_repo(tmp_path / "git_repo", git=True)


# ---------------------------------------------------------------------------
# Basic refresh success
# ---------------------------------------------------------------------------


def test_refresh_returns_ok(repo: Path) -> None:
    result = refresh_index(str(repo))
    assert result.status == "ok"
    assert result.refreshed is True


def test_refresh_files_indexed_count(repo: Path) -> None:
    result = refresh_index(str(repo))
    # README.md, pyproject.toml, .gitignore, src/main.py, src/utils.py,
    # tests/test_main.py, package-lock.json (noisy but still indexed) = 7 files
    # node_modules is skipped entirely
    assert result.files_indexed == 7


def test_refresh_directories_indexed(repo: Path) -> None:
    result = refresh_index(str(repo))
    # Directories: "" (root), "src", "tests"
    assert result.directories_indexed == 3


def test_refresh_creates_live_db(repo: Path) -> None:
    refresh_index(str(repo))
    live = get_db_path(str(repo))
    assert live.exists()


def test_refresh_temp_db_cleaned_up(repo: Path) -> None:
    refresh_index(str(repo))
    tmp = get_tmp_db_path(str(repo))
    assert not tmp.exists()


def test_refresh_not_partial_for_small_repo(repo: Path) -> None:
    result = refresh_index(str(repo))
    assert result.partial is False
    assert result.partial_reason is None


# ---------------------------------------------------------------------------
# DB content correctness
# ---------------------------------------------------------------------------


def test_repo_index_row_written(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    row = conn.execute("SELECT * FROM repo_index").fetchone()
    conn.close()
    assert row is not None
    assert row["repo_root"] == str(repo)
    assert row["repo_name"] == repo.name
    assert row["is_git_repo"] == 0
    assert row["partial_index"] == 0


def test_node_modules_not_in_files(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    paths = [r["path"] for r in conn.execute("SELECT path FROM files").fetchall()]
    conn.close()
    assert not any("node_modules" in p for p in paths)


def test_pyproject_classified_manifest(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT file_type FROM files WHERE path = 'pyproject.toml'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["file_type"] == "manifest"


def test_readme_classified_docs(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT file_type FROM files WHERE path = 'README.md'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["file_type"] == "docs"


def test_lockfile_classified_generated(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT file_type FROM files WHERE path = 'package-lock.json'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["file_type"] == "generated"


def test_test_file_classified_test(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT file_type FROM files WHERE path = 'tests/test_main.py'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["file_type"] == "test"


def test_importance_scores_stored(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    rows = conn.execute("SELECT importance_score FROM files").fetchall()
    conn.close()
    for row in rows:
        assert 0.0 <= row["importance_score"] <= 1.50


def test_path_tokens_json_valid(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    rows = conn.execute("SELECT path_tokens_json FROM files").fetchall()
    conn.close()
    for row in rows:
        tokens = json.loads(row["path_tokens_json"])
        assert isinstance(tokens, list)


def test_directories_have_scores(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    rows = conn.execute("SELECT importance_score FROM directories").fetchall()
    conn.close()
    assert len(rows) > 0
    for row in rows:
        assert 0.0 <= row["importance_score"] <= 1.50


def test_representative_files_json_valid(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    rows = conn.execute("SELECT representative_files_json FROM directories").fetchall()
    conn.close()
    for row in rows:
        files = json.loads(row["representative_files_json"])
        assert isinstance(files, list)


def test_index_run_completed(repo: Path) -> None:
    refresh_index(str(repo))
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT status, files_indexed, directories_indexed FROM index_runs"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["status"] == "completed"
    assert row["files_indexed"] == 7
    assert row["directories_indexed"] == 3


# ---------------------------------------------------------------------------
# Git repo
# ---------------------------------------------------------------------------


def test_refresh_git_repo_detects_metadata(git_repo: Path) -> None:
    result = refresh_index(str(git_repo))
    assert result.status == "ok"
    conn = open_db(str(git_repo))
    row = conn.execute("SELECT * FROM repo_index").fetchone()
    conn.close()
    assert row["is_git_repo"] == 1
    assert row["branch_name"] is not None
    assert row["head_sha"] is not None


def test_refresh_git_repo_branch_in_result(git_repo: Path) -> None:
    result = refresh_index(str(git_repo))
    assert result.branch_name is not None
    assert result.head_sha is not None


# ---------------------------------------------------------------------------
# Atomic swap: failed refresh must not corrupt live DB
# ---------------------------------------------------------------------------


def test_failed_refresh_does_not_corrupt_live_db(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Run a successful refresh first to establish a live DB.
    result = refresh_index(str(repo))
    assert result.status == "ok"
    live = get_db_path(str(repo))
    assert live.exists()

    # Record the original live DB mtime.
    original_mtime = live.stat().st_mtime

    # Patch _validate_temp_db to raise, simulating a write failure before swap.
    import repomind.refresh as refresh_mod

    def _bad_validate(conn: sqlite3.Connection, repo_id: str) -> None:
        raise RuntimeError("simulated validation failure")

    monkeypatch.setattr(refresh_mod, "_validate_temp_db", _bad_validate)

    result2 = refresh_index(str(repo))
    assert result2.status == "error"
    assert "simulated validation failure" in (result2.error_message or "")

    # Live DB must still exist and be unchanged.
    assert live.exists()
    assert live.stat().st_mtime == original_mtime

    # Temp file must be cleaned up.
    tmp = get_tmp_db_path(str(repo))
    assert not tmp.exists()


def test_failed_refresh_live_db_still_queryable(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh_index(str(repo))

    import repomind.refresh as refresh_mod

    monkeypatch.setattr(
        refresh_mod,
        "_validate_temp_db",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    refresh_index(str(repo))

    # Live DB must still be readable.
    conn = open_db(str(repo))
    row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
    conn.close()
    assert row[0] == 7


# ---------------------------------------------------------------------------
# Error handling: bad path
# ---------------------------------------------------------------------------


def test_refresh_invalid_path_returns_error() -> None:
    result = refresh_index("/nonexistent/path/that/does/not/exist")
    assert result.status == "error"
    assert result.refreshed is False
    assert result.error_message is not None


# ---------------------------------------------------------------------------
# Second refresh replaces first (idempotent)
# ---------------------------------------------------------------------------


def test_double_refresh_is_idempotent(repo: Path) -> None:
    r1 = refresh_index(str(repo))
    r2 = refresh_index(str(repo))
    assert r1.status == "ok"
    assert r2.status == "ok"
    assert r1.files_indexed == r2.files_indexed

    conn = open_db(str(repo))
    count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    assert count == r2.files_indexed


# ---------------------------------------------------------------------------
# Partial indexing
# ---------------------------------------------------------------------------


def test_partial_index_flagged_when_threshold_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(storage))

    repo = tmp_path / "big_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Big repo\n")

    # Use REPOMIND_FILE_LIMIT=3 so our tiny repo triggers partial mode.
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    monkeypatch.setenv("REPOMIND_MAX_DEPTH", "0")

    # Create 5 root-level files and 2 nested files (depth 1).
    for i in range(5):
        (repo / f"file{i}.py").write_text(f"x = {i}\n")
    nested = repo / "sub"
    nested.mkdir()
    for i in range(2):
        (nested / f"nested{i}.py").write_text(f"y = {i}\n")

    result = refresh_index(str(repo))
    assert result.status == "ok"
    assert result.partial is True
    assert isinstance(result.partial_reason, dict)
    assert result.partial_reason["cap_type"] in {"file_count", "depth"}

    # With max_depth=0, only root-level files indexed (depth 0).
    conn = open_db(str(repo))
    row = conn.execute("SELECT partial_index FROM repo_index").fetchone()
    conn.close()
    assert row["partial_index"] == 1

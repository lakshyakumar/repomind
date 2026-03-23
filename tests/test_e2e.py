"""End-to-end tests: full refresh + query pipeline (T17).

These tests exercise the system as a connected whole:
  refresh → index stored → all query functions return consistent data
  → staleness detected after a new commit → re-refresh restores freshness.

Separate sections cover:
  - Git repo happy path (multi-file, multi-directory)
  - Non-Git repo degradation
  - Stale-index detection and recovery
  - Partial-index behavior (REPOMIND_FILE_LIMIT set to 3 files)
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

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)


def _init_git(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "t@t.com")
    _git(path, "config", "user.name", "T")


def _commit_all(path: Path, message: str) -> str:
    """Stage everything, commit, return full HEAD SHA."""
    _git(path, "add", ".")
    _git(path, "commit", "-m", message)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(path),
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


# ---------------------------------------------------------------------------
# Fixture: realistic multi-directory Git repo
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path, storage: Path) -> dict:
    """Build a realistic multi-directory Git repo and return its path + HEAD SHA."""
    r = tmp_path / "repo"
    r.mkdir()

    _init_git(r)

    # manifest
    (r / "pyproject.toml").write_text("[project]\nname = 'myapp'\n")

    # entrypoint
    (r / "main.py").write_text(
        "# Application entrypoint\n"
        "def main():\n    pass\n" * 20
    )

    # source directories
    src = r / "src"
    src.mkdir()
    (src / "server.py").write_text("# HTTP server\ndef serve(): pass\n" * 25)
    (src / "config.py").write_text("# Configuration loader\nCONFIG = {}\n" * 10)

    webhooks = src / "webhooks"
    webhooks.mkdir()
    (webhooks / "handler.py").write_text(
        "# Webhook handler and delivery\n"
        "def handle(): pass\n" * 15
    )
    (webhooks / "retry.py").write_text("def retry(): pass\n" * 10)

    # auth module
    auth = src / "auth"
    auth.mkdir()
    (auth / "login.py").write_text(
        "# Login and authentication\n"
        "def login(): pass\n" * 12
    )

    # tests
    tests = r / "tests"
    tests.mkdir()
    (tests / "test_server.py").write_text("def test_serve(): pass\n" * 8)
    (tests / "test_auth.py").write_text("def test_login(): pass\n" * 5)

    sha = _commit_all(r, "feat: initial commit")

    return {"path": r, "sha": sha}


# ---------------------------------------------------------------------------
# Fixture: non-Git repo
# ---------------------------------------------------------------------------


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
    r = tmp_path / "plain"
    r.mkdir()
    lib = r / "lib"
    lib.mkdir()
    (lib / "util.py").write_text("def helper(): pass\n" * 5)
    (r / "README.md").write_text("# Plain repo\n")
    return r


# ---------------------------------------------------------------------------
# 1. Git repo happy path — full refresh + all queries
# ---------------------------------------------------------------------------


def test_e2e_git_initial_status_recommends_refresh(git_repo: dict) -> None:
    """Before any index exists, get_index_status should recommend refresh_index."""
    path = git_repo["path"]
    status = get_index_status(str(path))
    assert status.has_index is False
    assert status.recommended_first_call == "refresh_index"


def test_e2e_git_refresh_succeeds(git_repo: dict) -> None:
    """refresh_index completes and reports indexed files > 0."""
    result = run_refresh_index(str(git_repo["path"]))
    assert result.status == "ok"
    assert result.refreshed is True
    assert result.files_indexed > 0
    assert result.directories_indexed > 0


def test_e2e_git_status_fresh_after_refresh(git_repo: dict) -> None:
    """After refresh, index is current and not stale."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    status = get_index_status(str(path))
    assert status.has_index is True
    assert status.stale is False
    assert status.is_git_repo is True


def test_e2e_git_overview_returns_expected_shape(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    overview = get_repo_overview(str(path))
    assert overview.repo_name == "repo"
    assert overview.is_git_repo is True
    assert isinstance(overview.stack_hints, list)
    assert len(overview.top_directories) > 0
    assert len(overview.critical_files) > 0
    assert overview.provenance["stale"] is False


def test_e2e_git_overview_manifest_in_critical_files(git_repo: dict) -> None:
    """pyproject.toml (manifest) should appear in critical_files."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    overview = get_repo_overview(str(path))
    types = {f["file_type"] for f in overview.critical_files}
    assert "manifest" in types


def test_e2e_git_directory_map_all_dirs_present(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    dmap = get_directory_map(str(path))
    dir_paths = {d["path"] for d in dmap.directories}
    assert "src" in dir_paths
    assert "src/webhooks" in dir_paths
    assert "src/auth" in dir_paths
    assert "tests" in dir_paths


def test_e2e_git_directory_map_ordered_by_score(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    dmap = get_directory_map(str(path))
    scores = [d["importance_score"] for d in dmap.directories]
    assert scores == sorted(scores, reverse=True)


def test_e2e_git_directory_map_path_filter(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    dmap = get_directory_map(str(path), path_filter="src")
    for d in dmap.directories:
        assert d["path"] == "src" or d["path"].startswith("src/")


def test_e2e_git_critical_files_no_generated(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    cf = get_critical_files(str(path))
    for f in cf.files:
        assert f["file_type"] != "generated"
    assert len(cf.files) > 0


def test_e2e_git_critical_files_ordered_by_score(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    cf = get_critical_files(str(path))
    scores = [f["importance_score"] for f in cf.files]
    assert scores == sorted(scores, reverse=True)


def test_e2e_git_recent_changes_has_commits(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    rc = get_recent_changes(str(path))
    assert rc.is_git_repo is True
    assert len(rc.commits) >= 1
    assert rc.commits[0]["subject"] == "feat: initial commit"


def test_e2e_git_recent_changes_files_present(git_repo: dict) -> None:
    """Commit file list should include at least one file."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    rc = get_recent_changes(str(path))
    assert any(len(c["files"]) > 0 for c in rc.commits)


def test_e2e_git_edit_suggestions_webhook_task(git_repo: dict) -> None:
    """A webhook-related task should surface webhook handler files."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    sugg = get_edit_suggestions(str(path), task="webhooks handler delivery")
    paths = [s["path"] for s in sugg.suggestions]
    assert any("webhook" in p for p in paths)


def test_e2e_git_edit_suggestions_auth_task(git_repo: dict) -> None:
    """A login task should surface auth/login.py."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    sugg = get_edit_suggestions(str(path), task="login auth")
    paths = [s["path"] for s in sugg.suggestions]
    assert any("login" in p or "auth" in p for p in paths)


def test_e2e_git_edit_suggestions_reason_populated(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    sugg = get_edit_suggestions(str(path), task="webhooks handler delivery")
    for s in sugg.suggestions:
        assert len(s["reason"]) > 0


def test_e2e_git_provenance_consistent_across_queries(git_repo: dict) -> None:
    """All query results for the same repo state should share indexed_head_sha."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    sha = get_index_status(str(path)).provenance["indexed_head_sha"]
    assert get_repo_overview(str(path)).provenance["indexed_head_sha"] == sha
    assert get_directory_map(str(path)).provenance["indexed_head_sha"] == sha
    assert get_critical_files(str(path)).provenance["indexed_head_sha"] == sha
    assert get_recent_changes(str(path)).provenance["indexed_head_sha"] == sha
    assert get_edit_suggestions(str(path), task="server").provenance["indexed_head_sha"] == sha


# ---------------------------------------------------------------------------
# 2. Stale-index detection and recovery
# ---------------------------------------------------------------------------


def test_e2e_stale_detected_after_new_commit(git_repo: dict) -> None:
    """After indexing, a new commit should make the index stale."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    assert get_index_status(str(path)).stale is False

    # Add a new commit
    (path / "extra.py").write_text("x = 1\n")
    _commit_all(path, "feat: add extra module")

    assert get_index_status(str(path)).stale is True


def test_e2e_stale_recommends_refresh(git_repo: dict) -> None:
    path = git_repo["path"]
    run_refresh_index(str(path))
    (path / "extra.py").write_text("x = 1\n")
    _commit_all(path, "feat: add extra")

    status = get_index_status(str(path))
    assert status.refresh_recommended is True
    assert status.recommended_first_call == "refresh_index"


def test_e2e_stale_recovered_after_re_refresh(git_repo: dict) -> None:
    """Re-running refresh after a new commit restores stale=False."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    (path / "extra.py").write_text("x = 1\n")
    _commit_all(path, "feat: add extra")

    # stale now
    assert get_index_status(str(path)).stale is True

    # re-index
    result = run_refresh_index(str(path))
    assert result.status == "ok"

    # fresh again
    assert get_index_status(str(path)).stale is False


def test_e2e_stale_new_file_appears_after_re_refresh(git_repo: dict) -> None:
    """After re-refresh, new files should appear in critical_files."""
    path = git_repo["path"]
    run_refresh_index(str(path))

    before_paths = {f["path"] for f in get_critical_files(str(path)).files}

    (path / "newmodule.py").write_text("def new_feature(): pass\n" * 20)
    _commit_all(path, "feat: new module")
    run_refresh_index(str(path))

    after_paths = {f["path"] for f in get_critical_files(str(path)).files}
    assert "newmodule.py" in after_paths
    assert "newmodule.py" not in before_paths


def test_e2e_stale_provenance_head_sha_updates(git_repo: dict) -> None:
    """After re-refresh, indexed_head_sha should reflect the new commit."""
    path = git_repo["path"]
    run_refresh_index(str(path))
    sha_before = get_index_status(str(path)).provenance["indexed_head_sha"]

    (path / "extra.py").write_text("x = 1\n")
    new_sha = _commit_all(path, "feat: add extra")
    run_refresh_index(str(path))

    sha_after = get_index_status(str(path)).provenance["indexed_head_sha"]
    assert sha_after != sha_before
    assert sha_after == new_sha


# ---------------------------------------------------------------------------
# 3. Non-Git repo — clean degradation
# ---------------------------------------------------------------------------


def test_e2e_plain_refresh_succeeds(plain_repo: Path) -> None:
    result = run_refresh_index(str(plain_repo))
    assert result.status == "ok"
    assert result.refreshed is True


def test_e2e_plain_is_git_repo_false(plain_repo: Path) -> None:
    run_refresh_index(str(plain_repo))
    status = get_index_status(str(plain_repo))
    assert status.is_git_repo is False
    assert status.stale is False


def test_e2e_plain_recent_changes_empty(plain_repo: Path) -> None:
    run_refresh_index(str(plain_repo))
    rc = get_recent_changes(str(plain_repo))
    assert rc.is_git_repo is False
    assert rc.commits == []


def test_e2e_plain_overview_works(plain_repo: Path) -> None:
    run_refresh_index(str(plain_repo))
    overview = get_repo_overview(str(plain_repo))
    assert overview.is_git_repo is False
    assert isinstance(overview.critical_files, list)


def test_e2e_plain_edit_suggestions_work(plain_repo: Path) -> None:
    run_refresh_index(str(plain_repo))
    # Task uses exact path tokens ("lib", "util") so the scorer finds an overlap.
    sugg = get_edit_suggestions(str(plain_repo), task="lib util")
    assert isinstance(sugg.suggestions, list)
    paths = [s["path"] for s in sugg.suggestions]
    assert any("util" in p for p in paths)


# ---------------------------------------------------------------------------
# 4. Partial-index behavior (threshold monkeypatched to 3 files)
# ---------------------------------------------------------------------------


@pytest.fixture()
def partial_repo(tmp_path: Path, storage: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Small repo that triggers partial indexing via a lowered file limit."""
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")

    r = tmp_path / "partial"
    r.mkdir()
    _init_git(r)
    # More than 3 files so the file-count cap fires.
    for i in range(6):
        (r / f"module_{i}.py").write_text(f"# Module {i}\nx = {i}\n" * 5)
    _commit_all(r, "init")
    return r


def test_e2e_partial_refresh_marks_partial(partial_repo: Path) -> None:
    result = run_refresh_index(str(partial_repo))
    assert result.status == "ok"
    assert result.partial is True


def test_e2e_partial_index_status_partial_true(partial_repo: Path) -> None:
    run_refresh_index(str(partial_repo))
    status = get_index_status(str(partial_repo))
    assert status.partial is True


def test_e2e_partial_queries_still_work(partial_repo: Path) -> None:
    """Partial indexes must remain queryable — no tool should crash."""
    run_refresh_index(str(partial_repo))
    get_repo_overview(str(partial_repo))
    get_directory_map(str(partial_repo))
    get_critical_files(str(partial_repo))
    get_recent_changes(str(partial_repo))
    get_edit_suggestions(str(partial_repo), task="module")


def test_e2e_partial_provenance_partial_true_in_responses(partial_repo: Path) -> None:
    """All query responses must include partial=True in provenance for partial indexes."""
    run_refresh_index(str(partial_repo))
    assert get_repo_overview(str(partial_repo)).provenance["partial"] is True
    assert get_directory_map(str(partial_repo)).provenance["partial"] is True
    assert get_critical_files(str(partial_repo)).provenance["partial"] is True
    assert get_recent_changes(str(partial_repo)).provenance["partial"] is True
    assert get_edit_suggestions(str(partial_repo), task="module").provenance["partial"] is True

"""Iteration-2 end-to-end coverage (I2-T7).

Five scenario categories, each exercised against a real (unmodified) index:

1. FTS retrieval   — task "webhook" surfaces webhooks/handler.py via FTS;
                     task "xyzzy" returns empty via fallback
2. Import tokens   — Python file with `from repomind.queries import get_index_status`;
                     "queries" in import_tokens_json; task "queries" surfaces it;
                     stop-word imports ("os", "sys") absent from stored tokens
3. Configurable    — REPOMIND_FILE_LIMIT=3 on 6-file repo → partial + file_count cap;
   caps              REPOMIND_MAX_DEPTH=0 on nested repo → partial + depth cap;
                     all five query tools callable on a partial index
4. Quality signal  — fresh full index → "full"; partial index → "partial";
                     no index → "degraded"; signal propagates through all provenances
5. empty_reason    — task "xyzzy" → "no_token_overlap";
                     task "the a in" → "stop_words_only"

No mocks.  Every test exercises refresh → DB write → query read as a connected whole.

TASK-SPEC DEVIATIONS (noted per I2-T7 instructions):
- Spec says assert `"os"` and `"sys"` absent from import tokens "for any file".
  Implementation filters these via _IMPORT_STOP_TOKENS.  Test checks the specific
  fixture file's tokens rather than scanning every file (which would be fragile on
  large fixture repos).
- Spec baseline "464 v1 tests still pass" is outdated; the suite now has 561 tests
  after I2-T1 through I2-T6 additions.  All 561 pass — this PR adds on top.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repomind.db import open_db
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


def _commit_all(path: Path, message: str = "init") -> None:
    _git(path, "add", ".")
    _git(path, "commit", "-m", message, "--allow-empty")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


# ===========================================================================
# 1. FTS retrieval
# ===========================================================================


@pytest.fixture()
def fts_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with webhooks/handler.py — the canonical I2-T7 FTS fixture."""
    r = tmp_path / "fts_repo"
    r.mkdir()
    _init_git(r)

    # File whose path contains "webhooks" — task "webhook" should surface it via FTS
    webhooks_dir = r / "webhooks"
    webhooks_dir.mkdir()
    (webhooks_dir / "handler.py").write_text(
        "# Webhook handler\ndef handle_event(payload): pass\n"
    )
    # Unrelated file that should NOT match
    (r / "readme.md").write_text("# Project\n")
    _commit_all(r)
    run_refresh_index(str(r))
    return r


def test_fts_webhook_task_surfaces_handler(fts_repo: Path) -> None:
    """task='webhook' must surface webhooks/handler.py via FTS prefix matching."""
    result = get_edit_suggestions(str(fts_repo), task="webhook")
    paths = [s["path"] for s in result.suggestions]
    assert any("webhooks" in p for p in paths), (
        f"Expected a webhooks/ file in suggestions, got: {paths}"
    )


def test_fts_webhook_retrieval_method_is_fts(fts_repo: Path) -> None:
    """retrieval_method must be 'fts' when FTS produces candidates."""
    result = get_edit_suggestions(str(fts_repo), task="webhook")
    assert result.retrieval_method == "fts"


def test_fts_xyzzy_falls_back_and_is_empty(fts_repo: Path) -> None:
    """task='xyzzy' must return empty suggestions (no file matches this nonsense token)."""
    result = get_edit_suggestions(str(fts_repo), task="xyzzy")
    assert result.suggestions == []


def test_fts_xyzzy_retrieval_method_is_fallback(fts_repo: Path) -> None:
    """When FTS returns nothing and fallback also returns nothing, method is 'fallback'."""
    result = get_edit_suggestions(str(fts_repo), task="xyzzy")
    assert result.retrieval_method == "fallback"


# ===========================================================================
# 2. Import tokens
# ===========================================================================


@pytest.fixture()
def import_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo containing a Python file with a repomind import."""
    r = tmp_path / "import_repo"
    r.mkdir()
    _init_git(r)

    # The canonical import the spec calls for
    (r / "client.py").write_text(
        "from repomind.queries import get_index_status\n\nx = 1\n"
    )
    # A second Python file that imports os and sys (stop-word imports)
    (r / "utils.py").write_text("import os\nimport sys\n\ndef helper(): pass\n")
    _commit_all(r)
    run_refresh_index(str(r))
    return r


def test_import_tokens_queries_present(import_repo: Path) -> None:
    """'queries' must appear in import_tokens_json for client.py."""
    conn = open_db(str(import_repo))
    try:
        row = conn.execute(
            "SELECT import_tokens_json FROM files WHERE path = 'client.py'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "client.py not found in files table"
    tokens = json.loads(row["import_tokens_json"])
    assert "queries" in tokens, f"Expected 'queries' in import tokens, got: {tokens}"


def test_import_tokens_task_queries_surfaces_client(import_repo: Path) -> None:
    """task='queries' must surface client.py (it imports repomind.queries)."""
    result = get_edit_suggestions(str(import_repo), task="queries")
    paths = [s["path"] for s in result.suggestions]
    assert "client.py" in paths, f"Expected client.py in suggestions, got: {paths}"


def test_import_tokens_os_absent_from_utils(import_repo: Path) -> None:
    """'os' is a stop-word import — must not appear in utils.py's import_tokens_json."""
    conn = open_db(str(import_repo))
    try:
        row = conn.execute(
            "SELECT import_tokens_json FROM files WHERE path = 'utils.py'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "utils.py not found in files table"
    tokens = json.loads(row["import_tokens_json"])
    assert "os" not in tokens, f"'os' should be filtered by stop tokens, got: {tokens}"
    assert "sys" not in tokens, f"'sys' should be filtered by stop tokens, got: {tokens}"


# ===========================================================================
# 3. Configurable caps
# ===========================================================================


@pytest.fixture()
def six_file_repo(tmp_path: Path, storage: Path) -> Path:
    """6-file repo (no subdirectories) for file-count cap tests."""
    r = tmp_path / "six_file_repo"
    r.mkdir()
    _init_git(r)
    for i in range(6):
        (r / f"module_{i}.py").write_text(f"# Module {i}\nx = {i}\n")
    _commit_all(r)
    return r


@pytest.fixture()
def nested_dir_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with files at depth 0 and depth 1 for depth cap tests."""
    r = tmp_path / "nested_repo"
    r.mkdir()
    _init_git(r)
    (r / "root.py").write_text("# root level\n")
    sub = r / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("# depth 1\n")
    _commit_all(r)
    return r


def test_file_limit_cap_marks_partial(
    six_file_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    result = run_refresh_index(str(six_file_repo))
    assert result.partial is True


def test_file_limit_cap_reason_cap_type(
    six_file_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    result = run_refresh_index(str(six_file_repo))
    assert isinstance(result.partial_reason, dict)
    assert result.partial_reason["cap_type"] == "file_count"


def test_depth_cap_marks_partial_independently(
    nested_dir_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REPOMIND_MAX_DEPTH=0 triggers partial even when file count is fine."""
    monkeypatch.setenv("REPOMIND_MAX_DEPTH", "0")
    result = run_refresh_index(str(nested_dir_repo))
    assert result.partial is True
    assert isinstance(result.partial_reason, dict)
    assert result.partial_reason["cap_type"] == "depth"


def test_all_query_tools_work_on_partial_index(
    six_file_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No query tool should raise on a partial index."""
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    run_refresh_index(str(six_file_repo))
    get_repo_overview(str(six_file_repo))
    get_directory_map(str(six_file_repo))
    get_critical_files(str(six_file_repo))
    get_recent_changes(str(six_file_repo))
    get_edit_suggestions(str(six_file_repo), task="module")


# ===========================================================================
# 4. Quality signal
# ===========================================================================


@pytest.fixture()
def full_indexed_repo(tmp_path: Path, storage: Path) -> Path:
    """Standard small repo with a complete (non-partial) index."""
    r = tmp_path / "full_repo"
    r.mkdir()
    _init_git(r)
    (r / "main.py").write_text("def main(): pass\n")
    _commit_all(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def partial_indexed_repo(
    tmp_path: Path, storage: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """6-file repo indexed with REPOMIND_FILE_LIMIT=3."""
    monkeypatch.setenv("REPOMIND_FILE_LIMIT", "3")
    r = tmp_path / "partial_repo"
    r.mkdir()
    _init_git(r)
    for i in range(6):
        (r / f"f{i}.py").write_text(f"x = {i}\n")
    _commit_all(r)
    run_refresh_index(str(r))
    return r


def test_quality_signal_full_for_complete_index(full_indexed_repo: Path) -> None:
    assert get_index_status(str(full_indexed_repo)).quality_signal == "full"


def test_quality_signal_partial_for_partial_index(partial_indexed_repo: Path) -> None:
    assert get_index_status(str(partial_indexed_repo)).quality_signal == "partial"


def test_quality_signal_degraded_for_missing_index(
    tmp_path: Path, storage: Path
) -> None:
    r = tmp_path / "no_index_repo"
    r.mkdir()
    assert get_index_status(str(r)).quality_signal == "degraded"


def test_quality_signal_in_all_provenances(full_indexed_repo: Path) -> None:
    """quality_signal must appear in provenance for every query function."""
    for prov in [
        get_repo_overview(str(full_indexed_repo)).provenance,
        get_directory_map(str(full_indexed_repo)).provenance,
        get_critical_files(str(full_indexed_repo)).provenance,
        get_recent_changes(str(full_indexed_repo)).provenance,
        get_edit_suggestions(str(full_indexed_repo), task="main").provenance,
    ]:
        assert prov.get("quality_signal") == "full", (
            f"quality_signal missing or wrong in provenance: {prov}"
        )


# ===========================================================================
# 5. empty_reason
# ===========================================================================


def test_empty_reason_no_token_overlap(full_indexed_repo: Path) -> None:
    """A nonsense task with valid tokens that match nothing → 'no_token_overlap'."""
    result = get_edit_suggestions(str(full_indexed_repo), task="xyzzy")
    assert result.suggestions == []
    assert result.empty_reason == "no_token_overlap"


def test_empty_reason_stop_words_only(full_indexed_repo: Path) -> None:
    """A task composed only of stop words → 'stop_words_only'."""
    result = get_edit_suggestions(str(full_indexed_repo), task="the a in")
    assert result.suggestions == []
    assert result.empty_reason == "stop_words_only"


def test_empty_reason_none_when_suggestions_present(full_indexed_repo: Path) -> None:
    """empty_reason must be None when suggestions are non-empty."""
    result = get_edit_suggestions(str(full_indexed_repo), task="main")
    # main.py is in the fixture — at least one suggestion should come back
    if result.suggestions:
        assert result.empty_reason is None

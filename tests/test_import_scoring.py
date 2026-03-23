"""Tests for I2-T4a: import-token signal in get_edit_suggestions scoring.

Acceptance criteria:
- import-only match: a file that matches the task ONLY via import tokens
  (zero path, dir, header overlap) surfaces in suggestions
- no-overlap case: a file with no overlap on any signal does not surface
- formula weight constants are named (not inline magic numbers)
- full test suite passes
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import (
    _W_DIR,
    _W_HEADER,
    _W_IMPORT,
    _W_IMPORTANCE,
    _W_PATH,
    _W_RELEVANCE,
    get_edit_suggestions,
)
from repomind.refresh import refresh_index

# ---------------------------------------------------------------------------
# Named constant sanity
# ---------------------------------------------------------------------------


def test_relevance_weights_sum_to_one():
    """The four relevance components must sum to exactly 1.0."""
    total = _W_PATH + _W_DIR + _W_HEADER + _W_IMPORT
    assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, not 1.0"


def test_final_score_weights_sum_to_one():
    """Relevance and importance weights must sum to exactly 1.0."""
    assert abs(_W_RELEVANCE + _W_IMPORTANCE - 1.0) < 1e-9


def test_formula_weights_have_expected_values():
    """Formula constants match the I2-T4a spec."""
    assert _W_PATH == pytest.approx(0.45)
    assert _W_DIR == pytest.approx(0.25)
    assert _W_HEADER == pytest.approx(0.15)
    assert _W_IMPORT == pytest.approx(0.15)
    assert _W_RELEVANCE == pytest.approx(0.70)
    assert _W_IMPORTANCE == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)


def _init_git(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "t@t.com")
    _git(path, "config", "user.name", "T")
    (path / ".keep").write_text("")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def import_signal_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo designed to isolate the import-token signal.

    Structure:
      infra/cache.py   — path/dir tokens: 'infra', 'cache'
                       — import:  from repomind.queries import get_edit_suggestions
                                  → import tokens: 'repomind', 'queries', 'edit', 'suggestions'
      utils/helper.py  — path tokens: 'utils', 'helper'
                       — no imports, no path/dir/header overlap with 'queries'
    """
    r = tmp_path / "repo"
    r.mkdir()

    infra = r / "infra"
    infra.mkdir()
    (infra / "cache.py").write_text(
        "from repomind.queries import get_edit_suggestions\n"
        "class Cache: pass\n" * 10
    )

    utils = r / "utils"
    utils.mkdir()
    (utils / "helper.py").write_text(
        "# Generic helper utilities\n"
        "def helper(): pass\n" * 10
    )

    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    _init_git(r)
    result = refresh_index(str(r))
    assert result.status == "ok"
    return r


@pytest.fixture()
def ranked_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with files at different overlap levels for ranking sanity checks.

    For task 'queries edit suggestions':
      queries/handler.py  — path: 'queries', 'handler'
                          — import: 'suggestions', 'edit' (from get_edit_suggestions)
      queries/viewer.py   — path: 'queries', 'viewer' (path overlap only)
      unrelated/loader.py — no overlap on any signal
    """
    r = tmp_path / "repo"
    r.mkdir()

    qdir = r / "queries"
    qdir.mkdir()
    (qdir / "handler.py").write_text(
        "# Query handler\n"
        "from repomind.queries import get_edit_suggestions\n"
        "def handle(): pass\n" * 15
    )
    (qdir / "viewer.py").write_text(
        "# Query viewer\n"
        "def view(): pass\n" * 10
    )

    unrelated = r / "unrelated"
    unrelated.mkdir()
    (unrelated / "loader.py").write_text(
        "# Loader module\n"
        "def load(): pass\n" * 10
    )

    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    _init_git(r)
    result = refresh_index(str(r))
    assert result.status == "ok"
    return r


# ---------------------------------------------------------------------------
# Acceptance criterion: import-only match surfaces in results
# ---------------------------------------------------------------------------


def test_import_only_match_surfaces(import_signal_repo: Path):
    """infra/cache.py has zero path/dir/header overlap with 'queries edit suggestions'
    but matches via import tokens — it must appear in suggestions."""
    result = get_edit_suggestions(str(import_signal_repo), "queries edit suggestions")
    paths = [s["path"] for s in result.suggestions]
    assert any("cache" in p for p in paths), (
        f"infra/cache.py (import-only match) missing from suggestions: {paths}"
    )


def test_no_overlap_file_absent(import_signal_repo: Path):
    """utils/helper.py has no overlap on any signal for task 'queries' — must not appear."""
    result = get_edit_suggestions(str(import_signal_repo), "queries")
    paths = [s["path"] for s in result.suggestions]
    assert not any("helper" in p for p in paths), (
        f"utils/helper.py (no overlap) incorrectly surfaced: {paths}"
    )


# ---------------------------------------------------------------------------
# Ranking sanity: combined path + import signal ranks higher
# ---------------------------------------------------------------------------


def test_combined_signal_ranks_above_path_only(ranked_repo: Path):
    """queries/handler.py (path + import overlap) should rank above
    queries/viewer.py (path overlap only) for task 'queries edit suggestions'."""
    result = get_edit_suggestions(str(ranked_repo), "queries edit suggestions")
    paths = [s["path"] for s in result.suggestions]

    handler_idx = next((i for i, p in enumerate(paths) if "handler" in p), None)
    viewer_idx = next((i for i, p in enumerate(paths) if "viewer" in p), None)

    assert handler_idx is not None, "queries/handler.py missing from suggestions"
    assert viewer_idx is not None, "queries/viewer.py missing from suggestions"
    assert handler_idx < viewer_idx, (
        f"handler ({handler_idx}) should rank above viewer ({viewer_idx})"
    )


def test_unrelated_file_absent_from_ranked_repo(ranked_repo: Path):
    """unrelated/loader.py has no token overlap for 'queries' — must not appear."""
    result = get_edit_suggestions(str(ranked_repo), "queries")
    paths = [s["path"] for s in result.suggestions]
    assert not any("loader" in p for p in paths), (
        f"unrelated/loader.py incorrectly surfaced: {paths}"
    )


# ---------------------------------------------------------------------------
# General scorer integrity
# ---------------------------------------------------------------------------


def test_scores_still_between_zero_and_one(import_signal_repo: Path):
    result = get_edit_suggestions(str(import_signal_repo), "queries edit suggestions")
    for s in result.suggestions:
        assert 0.0 < s["score"] <= 1.0, f"score {s['score']} out of range"


def test_suggestions_still_ordered_descending(import_signal_repo: Path):
    result = get_edit_suggestions(str(import_signal_repo), "queries edit suggestions")
    scores = [s["score"] for s in result.suggestions]
    assert scores == sorted(scores, reverse=True)


def test_import_match_reason_present_when_import_signal_fires(import_signal_repo: Path):
    """I2-T4b: import-matching files include an 'Import match' reason entry."""
    result = get_edit_suggestions(str(import_signal_repo), "queries edit suggestions")
    cache_suggestions = [s for s in result.suggestions if "cache" in s["path"]]
    assert cache_suggestions, "infra/cache.py must appear for this task"
    cache = cache_suggestions[0]
    assert any("Import match" in r for r in cache["reason"]), (
        f"Expected 'Import match' reason for cache.py, got: {cache['reason']}"
    )

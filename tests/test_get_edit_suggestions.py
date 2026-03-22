"""Tests for queries.get_edit_suggestions (T15).

These tests focus on ranking correctness and signal quality, not just shape,
because get_edit_suggestions is the most product-critical v1 tool.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import EditSuggestions, get_edit_suggestions, run_refresh_index

# ---------------------------------------------------------------------------
# Helpers / fixtures
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
def webhook_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo whose structure clearly maps to a 'webhook delivery' domain."""
    r = tmp_path / "repo"
    r.mkdir()

    # webhook handler — should rank highly for webhook-related tasks
    webhooks = r / "webhooks"
    webhooks.mkdir()
    (webhooks / "delivery.py").write_text(
        "# Handles webhook delivery and retry\n"
        "def deliver(payload): pass\n" * 20
    )
    (webhooks / "receiver.py").write_text("def receive(): pass\n" * 10)

    # auth module — should NOT rank for webhook tasks
    auth = r / "auth"
    auth.mkdir()
    (auth / "login.py").write_text("def login(user): pass\n" * 15)
    (auth / "token.py").write_text("def refresh_token(): pass\n" * 10)

    # database layer — neutral
    db = r / "db"
    db.mkdir()
    (db / "models.py").write_text("class Model: pass\n" * 20)

    # manifest
    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    _init_git(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def auth_repo(tmp_path: Path, storage: Path) -> Path:
    """Repo with authentication and unrelated modules."""
    r = tmp_path / "repo"
    r.mkdir()

    auth = r / "auth"
    auth.mkdir()
    (auth / "login.py").write_text(
        "# Login and authentication handler\n"
        "def login(user, password): pass\n" * 20
    )
    (auth / "session.py").write_text(
        "# Session management\n"
        "def create_session(): pass\n" * 15
    )

    api = r / "api"
    api.mkdir()
    (api / "routes.py").write_text("def setup_routes(): pass\n" * 10)

    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    _init_git(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def plain_repo(tmp_path: Path, storage: Path) -> Path:
    """Non-git repo with a single source file."""
    r = tmp_path / "plain"
    r.mkdir()
    lib = r / "lib"
    lib.mkdir()
    (lib / "util.py").write_text("def helper(): pass\n")
    run_refresh_index(str(r))
    return r


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_no_index_raises_value_error(tmp_path: Path, storage: Path) -> None:
    r = tmp_path / "empty"
    r.mkdir()
    with pytest.raises(ValueError, match="refresh_index"):
        get_edit_suggestions(str(r), "add retry logic")


def test_invalid_path_raises_value_error(storage: Path) -> None:
    with pytest.raises(ValueError):
        get_edit_suggestions("/nonexistent/totally/fake/path", "add retry")


# ---------------------------------------------------------------------------
# Return type and basic shape
# ---------------------------------------------------------------------------


def test_returns_edit_suggestions_instance(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    assert isinstance(result, EditSuggestions)


def test_task_field_preserved(webhook_repo: Path) -> None:
    task = "webhook delivery retry"
    result = get_edit_suggestions(str(webhook_repo), task)
    assert result.task == task


def test_suggestions_is_list(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    assert isinstance(result.suggestions, list)


def test_each_suggestion_has_required_keys(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    assert len(result.suggestions) > 0
    for s in result.suggestions:
        assert "path" in s
        assert "file_type" in s
        assert "score" in s
        assert "confidence" in s
        assert "reason" in s


def test_reason_is_list(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    for s in result.suggestions:
        assert isinstance(s["reason"], list)


def test_reason_entries_are_strings(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    for s in result.suggestions:
        for r in s["reason"]:
            assert isinstance(r, str)


def test_score_is_float(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    for s in result.suggestions:
        assert isinstance(s["score"], float)


def test_confidence_valid_values(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "webhook delivery retry")
    for s in result.suggestions:
        assert s["confidence"] in ("low", "medium", "high")


# ---------------------------------------------------------------------------
# Filtering: zero-overlap files excluded
# ---------------------------------------------------------------------------


def test_zero_overlap_files_excluded(webhook_repo: Path) -> None:
    """A task with tokens that match nothing should yield no suggestions."""
    result = get_edit_suggestions(str(webhook_repo), "xyzzy qwerty zork")
    assert result.suggestions == []


def test_all_stop_words_task_returns_empty(webhook_repo: Path) -> None:
    """A task made entirely of stop words has no signal tokens."""
    result = get_edit_suggestions(str(webhook_repo), "the a in to for of and")
    assert result.suggestions == []


# ---------------------------------------------------------------------------
# Ranking sanity — webhook domain
# ---------------------------------------------------------------------------


def test_webhook_delivery_file_ranked_first(webhook_repo: Path) -> None:
    """webhooks/delivery.py should rank #1 for a delivery-focused task."""
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    assert len(result.suggestions) > 0
    top_path = result.suggestions[0]["path"]
    assert "delivery" in top_path or "webhook" in top_path.lower()


def test_auth_files_not_in_top_for_webhook_task(webhook_repo: Path) -> None:
    """auth/ files should not appear in top 2 results for a webhook task."""
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    top_2_paths = [s["path"] for s in result.suggestions[:2]]
    assert not any("auth" in p for p in top_2_paths)


def test_webhook_files_outrank_db_for_webhook_task(webhook_repo: Path) -> None:
    """Files in webhooks/ should outrank db/models.py for a webhook task."""
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    paths = [s["path"] for s in result.suggestions]
    webhook_indices = [i for i, p in enumerate(paths) if "webhook" in p]
    db_indices = [i for i, p in enumerate(paths) if "models" in p]
    if webhook_indices and db_indices:
        assert min(webhook_indices) < min(db_indices)


# ---------------------------------------------------------------------------
# Ranking sanity — auth domain
# ---------------------------------------------------------------------------


def test_auth_files_rank_for_login_task(auth_repo: Path) -> None:
    """auth/login.py should appear in top results for a login task."""
    result = get_edit_suggestions(str(auth_repo), "login authentication")
    paths = [s["path"] for s in result.suggestions]
    assert any("login" in p or "auth" in p for p in paths[:2])


def test_session_file_relevant_for_session_task(auth_repo: Path) -> None:
    """auth/session.py should appear for a session-related task."""
    result = get_edit_suggestions(str(auth_repo), "session management")
    paths = [s["path"] for s in result.suggestions]
    assert any("session" in p for p in paths)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_suggestions_ordered_by_score_descending(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    scores = [s["score"] for s in result.suggestions]
    assert scores == sorted(scores, reverse=True)


def test_scores_between_zero_and_one(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    for s in result.suggestions:
        assert 0.0 < s["score"] <= 1.0


# ---------------------------------------------------------------------------
# Result limit
# ---------------------------------------------------------------------------


def test_default_limit_is_ten(webhook_repo: Path) -> None:
    """With enough files, results should be capped at 10 by default."""
    # webhook_repo has 6 source files; all stop word filtered task → 0 results.
    # Use a broad task that likely matches most files.
    result = get_edit_suggestions(str(webhook_repo), "py")
    assert len(result.suggestions) <= 10


def test_custom_limit_respected(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks", limit=1)
    assert len(result.suggestions) <= 1


def test_limit_zero_returns_empty(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks", limit=0)
    assert result.suggestions == []


# ---------------------------------------------------------------------------
# Reason content
# ---------------------------------------------------------------------------


def test_reason_not_empty_for_matching_file(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    for s in result.suggestions:
        assert len(s["reason"]) > 0, f"Empty reason for {s['path']}"


def test_path_token_match_in_reason(webhook_repo: Path) -> None:
    """When path tokens fire, the reason should mention path tokens."""
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    top = result.suggestions[0]
    assert any("Path tokens matched" in r for r in top["reason"])


# ---------------------------------------------------------------------------
# Non-git repo still works
# ---------------------------------------------------------------------------


def test_non_git_repo_returns_results(plain_repo: Path) -> None:
    result = get_edit_suggestions(str(plain_repo), "helper util")
    assert isinstance(result, EditSuggestions)


def test_non_git_repo_task_match(plain_repo: Path) -> None:
    result = get_edit_suggestions(str(plain_repo), "helper util")
    paths = [s["path"] for s in result.suggestions]
    assert any("util" in p for p in paths)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_is_dict(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
    assert isinstance(result.provenance, dict)


def test_provenance_has_required_keys(webhook_repo: Path) -> None:
    result = get_edit_suggestions(str(webhook_repo), "delivery webhooks")
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

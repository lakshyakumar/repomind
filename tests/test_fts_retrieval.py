"""Tests for I2-T3: FTS-backed candidate retrieval in get_edit_suggestions.

Acceptance criteria:
- task 'webhook' surfaces a file with 'webhooks' in its path,
  retrieval_method == 'fts'
- task 'xyzzy qwerty' triggers fallback (retrieval_method == 'fallback')
  and returns an empty suggestions list
- all 28 existing test_get_edit_suggestions.py tests pass without modification
  (checked by running the full suite — not re-asserted here)
- ranking order for exact-token-match tasks is not degraded vs v1
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomind.queries import EditSuggestions, _build_fts_match, get_edit_suggestions
from repomind.refresh import refresh_index

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
    """Repo with webhooks/ directory and unrelated auth/ module."""
    r = tmp_path / "repo"
    r.mkdir()

    webhooks = r / "webhooks"
    webhooks.mkdir()
    (webhooks / "handler.py").write_text(
        "# Webhook event handler\n"
        "def handle(event): pass\n" * 20
    )
    (webhooks / "delivery.py").write_text(
        "# Webhook delivery and retry logic\n"
        "def deliver(payload): pass\n" * 20
    )

    auth = r / "auth"
    auth.mkdir()
    (auth / "login.py").write_text("def login(user): pass\n" * 15)

    (r / "README.md").write_text("# Repo\n")
    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    _init_git(r)
    result = refresh_index(str(r))
    assert result.status == "ok"
    return r


# ---------------------------------------------------------------------------
# _build_fts_match unit tests
# ---------------------------------------------------------------------------


def test_build_fts_match_single_token():
    assert _build_fts_match({"webhook"}) == "webhook*"


def test_build_fts_match_multiple_tokens():
    expr = _build_fts_match({"webhook", "delivery"})
    assert "webhook*" in expr
    assert "delivery*" in expr
    assert " OR " in expr


def test_build_fts_match_is_deterministic():
    """Same token set always produces the same expression."""
    tokens = {"auth", "handler", "retry"}
    assert _build_fts_match(tokens) == _build_fts_match(tokens)


def test_build_fts_match_sorted():
    expr = _build_fts_match({"zz", "aa", "mm"})
    assert expr == "aa* OR mm* OR zz*"


# ---------------------------------------------------------------------------
# Acceptance criterion 1: 'webhook' → fts path → webhooks/handler.py
# ---------------------------------------------------------------------------


def test_webhook_task_uses_fts_retrieval(webhook_repo: Path):
    """task='webhook' must trigger FTS retrieval, not fallback."""
    result = get_edit_suggestions(str(webhook_repo), "webhook")
    assert result.retrieval_method == "fts"


def test_webhook_task_surfaces_webhooks_file(webhook_repo: Path):
    """task='webhook' surfaces at least one file with 'webhooks' in path."""
    result = get_edit_suggestions(str(webhook_repo), "webhook")
    paths = [s["path"] for s in result.suggestions]
    assert any("webhooks" in p for p in paths), f"no webhooks/* in {paths}"


def test_webhook_task_webhooks_files_ranked_above_auth(webhook_repo: Path):
    """Webhook-related files should rank above unrelated auth files."""
    result = get_edit_suggestions(str(webhook_repo), "webhook handler")
    paths = [s["path"] for s in result.suggestions]
    webhook_indices = [i for i, p in enumerate(paths) if "webhooks" in p]
    auth_indices = [i for i, p in enumerate(paths) if "auth" in p]
    if webhook_indices and auth_indices:
        assert min(webhook_indices) < max(auth_indices)


# ---------------------------------------------------------------------------
# Acceptance criterion 2: unknown task → fallback, empty suggestions
# ---------------------------------------------------------------------------


def test_xyzzy_task_uses_fallback(webhook_repo: Path):
    """task='xyzzy qwerty' must use fallback (FTS returns zero)."""
    result = get_edit_suggestions(str(webhook_repo), "xyzzy qwerty")
    assert result.retrieval_method == "fallback"


def test_xyzzy_task_returns_empty_suggestions(webhook_repo: Path):
    """task='xyzzy qwerty' returns no suggestions (nothing matches)."""
    result = get_edit_suggestions(str(webhook_repo), "xyzzy qwerty")
    assert result.suggestions == []


# ---------------------------------------------------------------------------
# retrieval_method field shape
# ---------------------------------------------------------------------------


def test_retrieval_method_is_string(webhook_repo: Path):
    result = get_edit_suggestions(str(webhook_repo), "webhook")
    assert isinstance(result.retrieval_method, str)


def test_retrieval_method_valid_values(webhook_repo: Path):
    """retrieval_method is always one of the two expected values."""
    r1 = get_edit_suggestions(str(webhook_repo), "webhook")
    r2 = get_edit_suggestions(str(webhook_repo), "xyzzy")
    for result in (r1, r2):
        assert result.retrieval_method in ("fts", "fallback")


def test_retrieval_method_present_on_edit_suggestions_dataclass():
    """EditSuggestions can be constructed with retrieval_method."""
    es = EditSuggestions(task="test", suggestions=[], retrieval_method="fts")
    assert es.retrieval_method == "fts"


def test_retrieval_method_defaults_to_fallback():
    """Default retrieval_method is 'fallback' for backward compatibility."""
    es = EditSuggestions(task="test", suggestions=[])
    assert es.retrieval_method == "fallback"


# ---------------------------------------------------------------------------
# Ranking preservation: exact-token-match tasks not degraded
# ---------------------------------------------------------------------------


def test_exact_token_match_still_surfaces_file(webhook_repo: Path):
    """A task with exact path tokens still surfaces the right files."""
    result = get_edit_suggestions(str(webhook_repo), "delivery")
    paths = [s["path"] for s in result.suggestions]
    assert any("delivery" in p for p in paths), f"delivery.py not found in {paths}"


def test_exact_token_match_fts_path_used(webhook_repo: Path):
    """Exact token matches go through FTS (prefix 'delivery*' matches 'delivery.py')."""
    result = get_edit_suggestions(str(webhook_repo), "delivery")
    assert result.retrieval_method == "fts"


def test_stop_word_only_task_returns_empty(webhook_repo: Path):
    """Task reduced to empty token set after filtering returns no suggestions."""
    result = get_edit_suggestions(str(webhook_repo), "the a in to for")
    assert result.suggestions == []


# ---------------------------------------------------------------------------
# Provenance field still present
# ---------------------------------------------------------------------------


def test_provenance_still_present(webhook_repo: Path):
    result = get_edit_suggestions(str(webhook_repo), "webhook")
    assert isinstance(result.provenance, dict)
    for key in ("indexed_branch", "indexed_head_sha", "stale", "partial"):
        assert key in result.provenance

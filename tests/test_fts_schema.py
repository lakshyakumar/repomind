"""Tests for I2-T1: FTS5 schema creation and refresh integration.

Acceptance criteria:
- files_fts table present and populated after refresh_index on a test repo
- FTS prefix query 'webhook*' returns rows for a repo with "webhooks" in paths
  (note: the spec acceptance criterion writes 'webhook' but FTS5 unicode61 uses
  exact token matching; 'webhook*' is the correct prefix form — I2-T3 wires this
  into get_edit_suggestions retrieval using prefix queries)
- FTS exact query 'webhooks' also returns rows (confirms direct token indexing)
- FTS query 'xyzzy' returns no rows
- rowid in files_fts matches files.id (join key is correct)
- files_fts is populated for all files in the repo
- header_tokens column is searchable via FTS
- existing schema tables are unaffected
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from repomind.db import open_db
from repomind.refresh import refresh_index

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_webhook_repo(base: Path) -> Path:
    """Repo with webhook-related files and an auth module."""
    r = base / "repo"
    r.mkdir()

    webhooks = r / "webhooks"
    webhooks.mkdir()
    (webhooks / "handler.py").write_text(
        "# Webhook event handler\n"
        "def handle(event): pass\n" * 20
    )
    (webhooks / "delivery.py").write_text(
        "# Handles delivery and retry\n"
        "def deliver(payload): pass\n" * 20
    )

    auth = r / "auth"
    auth.mkdir()
    (auth / "login.py").write_text("def login(user): pass\n" * 15)

    (r / "README.md").write_text("# Repo\n")
    return r


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def indexed_webhook_repo(tmp_path: Path, storage: Path) -> tuple[Path, sqlite3.Connection]:
    """Returns (repo_path, open db connection) after a successful refresh."""
    repo = _make_webhook_repo(tmp_path)
    result = refresh_index(str(repo))
    assert result.status == "ok", f"refresh failed: {result.error_message}"
    conn = open_db(str(repo))
    return repo, conn


# ---------------------------------------------------------------------------
# Table presence
# ---------------------------------------------------------------------------


def test_files_fts_table_exists_after_refresh(indexed_webhook_repo):
    _, conn = indexed_webhook_repo
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'files_fts'"
    ).fetchall()
    assert len(rows) == 1


def test_files_fts_is_populated_after_refresh(indexed_webhook_repo):
    _, conn = indexed_webhook_repo
    count = conn.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0]
    assert count > 0


def test_files_fts_row_count_matches_files_table(indexed_webhook_repo):
    _, conn = indexed_webhook_repo
    fts_count = conn.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0]
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert fts_count == file_count


# ---------------------------------------------------------------------------
# FTS query correctness
# ---------------------------------------------------------------------------


def test_fts_exact_token_match_webhooks(indexed_webhook_repo):
    """'webhooks' exact token matches files in the webhooks/ directory."""
    _, conn = indexed_webhook_repo
    rows = conn.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH 'webhooks'"
    ).fetchall()
    assert len(rows) >= 1


def test_fts_prefix_match_webhook_star(indexed_webhook_repo):
    """'webhook*' prefix matches files whose path or directory contains 'webhooks'."""
    _, conn = indexed_webhook_repo
    rows = conn.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH 'webhook*'"
    ).fetchall()
    assert len(rows) >= 1


def test_fts_no_match_for_unknown_token(indexed_webhook_repo):
    """'xyzzy' returns no rows for any real repo."""
    _, conn = indexed_webhook_repo
    rows = conn.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH 'xyzzy'"
    ).fetchall()
    assert len(rows) == 0


def test_fts_auth_path_is_searchable(indexed_webhook_repo):
    """'auth' token is indexed from the auth/ directory path."""
    _, conn = indexed_webhook_repo
    rows = conn.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH 'auth'"
    ).fetchall()
    assert len(rows) >= 1


def test_fts_header_tokens_are_indexed(indexed_webhook_repo):
    """Header comment tokens are searchable via the header_tokens FTS column."""
    _, conn = indexed_webhook_repo
    # webhooks/handler.py has "# Webhook event handler" → 'handler' token is indexed
    rows = conn.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH 'handler'"
    ).fetchall()
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# rowid join integrity
# ---------------------------------------------------------------------------


def test_fts_rowid_joins_to_files_id(indexed_webhook_repo):
    """Every rowid in files_fts maps to a valid files.id."""
    _, conn = indexed_webhook_repo
    fts_rows = conn.execute("SELECT rowid FROM files_fts").fetchall()
    fts_rowids = {row[0] for row in fts_rows}

    file_ids = {
        row[0]
        for row in conn.execute("SELECT id FROM files").fetchall()
    }
    assert fts_rowids == file_ids


def test_fts_rowid_path_matches_files_path(indexed_webhook_repo):
    """FTS rowid → path join returns the correct file path."""
    _, conn = indexed_webhook_repo
    rows = conn.execute(
        """
        SELECT f.path
        FROM files_fts fts
        JOIN files f ON f.id = fts.rowid
        WHERE fts.path MATCH 'handler'
        """
    ).fetchall()
    paths = [row[0] for row in rows]
    assert any("handler" in p for p in paths)


# ---------------------------------------------------------------------------
# Rebuild-on-refresh behaviour
# ---------------------------------------------------------------------------


def test_fts_rebuilt_on_second_refresh(tmp_path: Path, storage: Path):
    """A second refresh produces a fresh, correct FTS table (not a stale one)."""
    repo = _make_webhook_repo(tmp_path)
    r1 = refresh_index(str(repo))
    assert r1.status == "ok"

    # Add a new file with a unique token before the second refresh.
    (repo / "auth" / "oauth.py").write_text(
        "# OAuth2 token verification\n"
        "def verify(token): pass\n" * 10
    )
    r2 = refresh_index(str(repo))
    assert r2.status == "ok"

    conn = open_db(str(repo))
    rows = conn.execute(
        "SELECT rowid FROM files_fts WHERE files_fts MATCH 'oauth*'"
    ).fetchall()
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# No interference with existing tables
# ---------------------------------------------------------------------------


def test_open_db_without_refresh_has_no_files_fts(tmp_path: Path, storage: Path):
    """files_fts is only created by refresh, not by open_db schema init."""
    conn = open_db(str(tmp_path / "empty_repo"))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'files_fts'"
    ).fetchall()
    assert len(rows) == 0


def test_existing_tables_still_present_after_refresh(indexed_webhook_repo):
    """All v1 schema tables remain after a refresh that creates files_fts."""
    _, conn = indexed_webhook_repo
    table_names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'"
            " AND name NOT LIKE 'files_fts_%'"
        ).fetchall()
    }
    expected = {
        "repo_index", "files", "directories",
        "recent_commits", "commit_files", "index_runs",
    }
    assert expected.issubset(table_names)

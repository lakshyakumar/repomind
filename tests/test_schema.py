"""Tests for SQLite schema initialisation and version management."""

import sqlite3

from repomind.db import (
    CURRENT_SCHEMA_VERSION,
    _get_schema_version,
    _set_schema_version,
    get_db_path,
    open_db,
)

_EXPECTED_TABLES = {
    "repo_index",
    "files",
    "directories",
    "recent_commits",
    "commit_files",
    "index_runs",
}

_EXPECTED_INDEXES = {
    "idx_directories_repo_score",
    "idx_files_repo_score",
    "idx_files_repo_type",
    "idx_files_repo_directory",
    "idx_commits_repo_time",
    "idx_commit_files_repo_path",
}


def _list_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _list_indexes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


# --- schema creation --------------------------------------------------------


def test_open_db_creates_all_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn = open_db("/some/repo")
    assert _EXPECTED_TABLES == _list_tables(conn)


def test_open_db_creates_all_indexes(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn = open_db("/some/repo")
    assert _EXPECTED_INDEXES.issubset(_list_indexes(conn))


def test_schema_version_is_set_after_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn = open_db("/some/repo")
    assert _get_schema_version(conn) == CURRENT_SCHEMA_VERSION


def test_wal_mode_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn = open_db("/some/repo")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_row_factory_is_sqlite_row(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn = open_db("/some/repo")
    assert conn.row_factory is sqlite3.Row


# --- idempotency ------------------------------------------------------------


def test_second_open_preserves_existing_data(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn1 = open_db("/some/repo")
    conn1.execute(
        "INSERT INTO repo_index VALUES (?,?,?,NULL,NULL,?,1,1,0,NULL)",
        ("id1", "/some/repo", "repo", "2024-01-01T00:00:00Z"),
    )
    conn1.commit()
    conn1.close()

    conn2 = open_db("/some/repo")
    count = conn2.execute("SELECT COUNT(*) FROM repo_index").fetchone()[0]
    assert count == 1  # row is preserved when version matches


# --- version mismatch -------------------------------------------------------


def test_version_mismatch_drops_data_and_recreates_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))

    # Create DB with valid schema and insert a row.
    conn1 = open_db("/some/repo")
    conn1.execute(
        "INSERT INTO repo_index VALUES (?,?,?,NULL,NULL,?,1,1,0,NULL)",
        ("id1", "/some/repo", "repo", "2024-01-01T00:00:00Z"),
    )
    conn1.commit()
    conn1.close()

    # Tamper: set a mismatched schema version directly.
    db_path = get_db_path("/some/repo")
    conn_hack = sqlite3.connect(str(db_path))
    _set_schema_version(conn_hack, 999)
    conn_hack.commit()
    conn_hack.close()

    # Reopen: should recreate schema, losing the row.
    conn2 = open_db("/some/repo")
    assert _EXPECTED_TABLES == _list_tables(conn2)
    count = conn2.execute("SELECT COUNT(*) FROM repo_index").fetchone()[0]
    assert count == 0  # data was lost; caller must re-index


def test_version_mismatch_restores_all_indexes(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn1 = open_db("/some/repo")
    conn1.close()

    db_path = get_db_path("/some/repo")
    conn_hack = sqlite3.connect(str(db_path))
    _set_schema_version(conn_hack, 999)
    conn_hack.commit()
    conn_hack.close()

    conn2 = open_db("/some/repo")
    assert _EXPECTED_INDEXES.issubset(_list_indexes(conn2))


# --- isolation between repos ------------------------------------------------


def test_separate_repos_use_separate_dbs(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    conn_a = open_db("/repo/a")
    conn_b = open_db("/repo/b")

    conn_a.execute(
        "INSERT INTO repo_index VALUES (?,?,?,NULL,NULL,?,1,1,0,NULL)",
        ("id_a", "/repo/a", "repo_a", "2024-01-01T00:00:00Z"),
    )
    conn_a.commit()

    count = conn_b.execute("SELECT COUNT(*) FROM repo_index").fetchone()[0]
    assert count == 0  # repo_b is unaffected by repo_a writes
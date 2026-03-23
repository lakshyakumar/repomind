"""SQLite storage layer: schema init, connection management, path resolution."""

import os
import sqlite3
from hashlib import sha256
from pathlib import Path

# Bump this when the schema changes. open_db() will drop and recreate all
# tables when the stored version does not match.
CURRENT_SCHEMA_VERSION = 4

# ---------------------------------------------------------------------------
# Storage path helpers (T02)
# ---------------------------------------------------------------------------


def _storage_root() -> Path:
    """Return the Repomind local storage root.

    Override with REPOMIND_STORAGE_ROOT env var for testing or custom installs.
    """
    override = os.environ.get("REPOMIND_STORAGE_ROOT")
    if override:
        return Path(override).resolve()
    return Path.home() / ".repomind"


def _ensure_dirs(storage_root: Path) -> tuple[Path, Path]:
    """Create indexes/ and tmp/ under storage_root. Return (indexes_dir, tmp_dir)."""
    indexes_dir = storage_root / "indexes"
    tmp_dir = storage_root / "tmp"
    indexes_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return indexes_dir, tmp_dir


def repo_hash(repo_root: str) -> str:
    """Return a stable SHA-256 hex digest for the given repo root path.

    Normalises trailing slashes before hashing so /a/b and /a/b/ produce
    the same key.
    """
    normalized = str(Path(repo_root).resolve()).rstrip("/")
    return sha256(normalized.encode()).hexdigest()


def get_db_path(repo_root: str) -> Path:
    """Return the SQLite DB path for *repo_root*, creating storage dirs if needed."""
    storage_root = _storage_root()
    indexes_dir, _ = _ensure_dirs(storage_root)
    return indexes_dir / f"{repo_hash(repo_root)}.sqlite3"


def get_tmp_db_path(repo_root: str) -> Path:
    """Return the temp DB path used during atomic refresh for *repo_root*."""
    storage_root = _storage_root()
    _, tmp_dir = _ensure_dirs(storage_root)
    return tmp_dir / f"{repo_hash(repo_root)}.sqlite3.tmp"


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL_TABLES = """
CREATE TABLE IF NOT EXISTS repo_index (
  repo_id       TEXT PRIMARY KEY,
  repo_root     TEXT NOT NULL,
  repo_name     TEXT NOT NULL,
  branch_name   TEXT,
  head_sha      TEXT,
  indexed_at    TEXT NOT NULL,
  is_git_repo   INTEGER NOT NULL,
  index_version INTEGER NOT NULL,
  partial_index INTEGER NOT NULL DEFAULT 0,
  partial_reason TEXT
);

CREATE TABLE IF NOT EXISTS directories (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id                  TEXT NOT NULL,
  path                     TEXT NOT NULL,
  depth                    INTEGER NOT NULL,
  file_count               INTEGER NOT NULL,
  role                     TEXT,
  summary                  TEXT,
  representative_files_json TEXT NOT NULL,
  importance_score         REAL NOT NULL,
  UNIQUE(repo_id, path)
);

CREATE TABLE IF NOT EXISTS files (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id              TEXT NOT NULL,
  path                 TEXT NOT NULL,
  directory_path       TEXT NOT NULL,
  extension            TEXT,
  size_bytes           INTEGER NOT NULL,
  line_count           INTEGER,
  depth                INTEGER NOT NULL,
  file_type            TEXT NOT NULL,
  importance_score     REAL NOT NULL,
  inbound_ref_count    INTEGER NOT NULL DEFAULT 0,
  path_tokens_json     TEXT NOT NULL,
  header_tokens_json   TEXT NOT NULL,
  import_tokens_json   TEXT NOT NULL DEFAULT '[]',
  representative_reason TEXT,
  last_modified_ts     TEXT,
  UNIQUE(repo_id, path)
);

CREATE TABLE IF NOT EXISTS recent_commits (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id             TEXT NOT NULL,
  commit_sha          TEXT NOT NULL,
  author_name         TEXT,
  authored_at         TEXT,
  subject             TEXT NOT NULL,
  files_changed_count INTEGER,
  UNIQUE(repo_id, commit_sha)
);

CREATE TABLE IF NOT EXISTS commit_files (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id     TEXT NOT NULL,
  commit_sha  TEXT NOT NULL,
  path        TEXT NOT NULL,
  change_type TEXT,
  UNIQUE(repo_id, commit_sha, path)
);

CREATE TABLE IF NOT EXISTS index_runs (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id             TEXT NOT NULL,
  started_at          TEXT NOT NULL,
  completed_at        TEXT,
  status              TEXT NOT NULL,
  branch_name         TEXT,
  head_sha            TEXT,
  files_indexed       INTEGER,
  directories_indexed INTEGER,
  partial_index       INTEGER NOT NULL DEFAULT 0,
  error_message       TEXT
);
"""

_DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_directories_repo_score
  ON directories(repo_id, importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_files_repo_score
  ON files(repo_id, importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_files_repo_type
  ON files(repo_id, file_type);
CREATE INDEX IF NOT EXISTS idx_files_repo_directory
  ON files(repo_id, directory_path);
CREATE INDEX IF NOT EXISTS idx_commits_repo_time
  ON recent_commits(repo_id, authored_at DESC);
CREATE INDEX IF NOT EXISTS idx_commit_files_repo_path
  ON commit_files(repo_id, path);
"""

# Ordered for safe DROP (children before parents, though SQLite doesn't
# enforce FK by default; kept explicit for clarity).
# files_fts is a virtual table created during refresh; include it here so
# open_db()'s schema-version-mismatch path drops it cleanly.
_TABLE_NAMES = [
    "files_fts",
    "index_runs",
    "commit_files",
    "recent_commits",
    "files",
    "directories",
    "repo_index",
]

# ---------------------------------------------------------------------------
# Internal schema helpers
# ---------------------------------------------------------------------------


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Read PRAGMA user_version (0 = fresh / uninitialised)."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA does not support bound parameters; version is always an int literal.
    conn.execute(f"PRAGMA user_version = {version}")


def _drop_all_tables(conn: sqlite3.Connection) -> None:
    for name in _TABLE_NAMES:
        conn.execute(f"DROP TABLE IF EXISTS {name}")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL_TABLES)
    conn.executescript(_DDL_INDEXES)
    _set_schema_version(conn, CURRENT_SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Public connection factory
# ---------------------------------------------------------------------------


def open_fresh_db_at(path: Path) -> sqlite3.Connection:
    """Create a fresh SQLite DB at *path* with the current schema.

    Any existing file at *path* is silently replaced. Intended for the
    temporary DB used in the atomic refresh flow — do not call for the
    live DB path.

    Returns a connection with WAL journal mode and row_factory = sqlite3.Row.
    """
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _create_schema(conn)
    conn.commit()
    return conn


def open_db(repo_root: str) -> sqlite3.Connection:
    """Open (and initialise if needed) the SQLite index for *repo_root*.

    Behaviour:
    - Fresh DB (user_version == 0): schema is created.
    - Version matches CURRENT_SCHEMA_VERSION: returned as-is.
    - Version mismatch: all tables are dropped, schema recreated.
      Callers must trigger a full re-index after a version mismatch.

    Returns a connection with WAL journal mode and row_factory = sqlite3.Row.
    """
    db_path = get_db_path(repo_root)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    existing_version = _get_schema_version(conn)

    if existing_version == 0:
        _create_schema(conn)
    elif existing_version != CURRENT_SCHEMA_VERSION:
        _drop_all_tables(conn)
        _create_schema(conn)
    # Version matches — schema is current; nothing to do.

    conn.commit()
    return conn

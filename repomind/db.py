"""SQLite storage layer: schema init, connection management, path resolution."""

import os
from hashlib import sha256
from pathlib import Path


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
    # Resolve to absolute, then strip trailing slash for stability
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

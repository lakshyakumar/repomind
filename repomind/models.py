"""Shared dataclasses and type definitions."""

from dataclasses import dataclass, field


@dataclass
class Commit:
    """A single Git commit with its changed file list."""

    hash: str
    subject: str
    author_name: str | None
    authored_at: str  # ISO 8601, UTC
    files_changed: list[str] = field(default_factory=list)


@dataclass
class FileRecord:
    """Raw file metadata collected during repository walking."""

    # Path relative to repo root, using forward slashes.
    path: str
    # Absolute path on the local filesystem.
    abs_path: str
    # Size in bytes.
    size_bytes: int
    # Directory depth from repo root (root-level files are depth 0).
    depth: int
    # Last-modified timestamp as ISO 8601 UTC string, or None if unavailable.
    last_modified_ts: str | None
    # True when this file matches a noisy/binary pattern and should be
    # excluded from deep content processing or scored with a noisy penalty.
    is_noisy: bool

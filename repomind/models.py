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


@dataclass
class ClassifiedFile(FileRecord):
    """A FileRecord enriched with classification and token metadata.

    Produced by ``extractor.classify_and_extract()``. All parent fields
    are preserved; the child fields are filled by the extractor.
    """

    # One of: manifest, config, entrypoint, docs, test, source, generated, other.
    file_type: str = "other"
    # Lowercase file extension including the leading dot, e.g. ".py". None for
    # files with no extension.
    extension: str | None = None
    # Total line count, or None for noisy/binary files or on read error.
    line_count: int | None = None
    # Relative directory path using forward slashes. Empty string for root-level.
    directory_path: str = ""
    # Unique lowercase tokens extracted from the file path (stem + dirs).
    # Stored as JSON in the DB column path_tokens_json.
    path_tokens: list[str] = field(default_factory=list)
    # Unique lowercase tokens extracted from leading comment/docstring lines.
    # Stored as JSON in the DB column header_tokens_json.
    header_tokens: list[str] = field(default_factory=list)

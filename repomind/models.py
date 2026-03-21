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

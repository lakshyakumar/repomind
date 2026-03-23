"""Repository walker: file tree traversal and skip rule enforcement."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterator

from repomind.models import FileRecord

# ---------------------------------------------------------------------------
# Definitive skip list (ARCHITECTURE.md §8)
# ---------------------------------------------------------------------------

# Directory *names* (not full paths) that are always skipped during traversal.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
        ".turbo",
        ".cache",
        "target",
        ".gradle",
        "coverage",
    }
)

# Directory *path segments* that require a two-part match.
# e.g. "vendor/bundle" means a directory named "bundle" whose parent is "vendor".
SKIP_DIR_PATHS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("vendor", "bundle"),
    }
)

# ---------------------------------------------------------------------------
# Noisy file patterns
# ---------------------------------------------------------------------------

# Exact filenames that are always treated as noisy.
NOISY_FILENAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "gemfile.lock",
        "poetry.lock",
        "composer.lock",
        "cargo.lock",
    }
)

# File extensions (lowercase, including the leading dot) that are noisy.
NOISY_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Minified / sourcemaps
        ".map",
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".svg",
        # Video / audio
        ".mp4",
        ".mov",
        ".mp3",
        ".wav",
        # Documents / compiled
        ".pdf",
        ".pyc",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        # Fonts
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
    }
)

# Extension suffixes indicating minified JavaScript/CSS.
_MINIFIED_SUFFIXES: tuple[str, ...] = (".min.js", ".min.css")

# Files larger than this are treated as noisy regardless of extension.
_MAX_CONTENT_BYTES: int = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_noisy_file(name: str, size_bytes: int) -> bool:
    """Return True if *name* or *size_bytes* matches a noisy pattern."""
    lower = name.lower()

    if lower in NOISY_FILENAMES:
        return True

    if any(lower.endswith(suffix) for suffix in _MINIFIED_SUFFIXES):
        return True

    ext = os.path.splitext(lower)[1]
    if ext in NOISY_EXTENSIONS:
        return True

    if size_bytes > _MAX_CONTENT_BYTES:
        return True

    return False


def _should_skip_dir(dir_name: str, rel_parts: tuple[str, ...]) -> bool:
    """Return True if a directory should be pruned from traversal.

    Args:
        dir_name: the bare directory name (last segment).
        rel_parts: path segments from repo root to this directory (inclusive).
    """
    if dir_name in SKIP_DIRS:
        return True

    # Check two-part patterns (e.g. vendor/bundle).
    if len(rel_parts) >= 2:
        tail = rel_parts[-2:]
        if tuple(tail) in SKIP_DIR_PATHS:
            return True

    return False


def _mtime_iso(path: str) -> str | None:
    """Return the last-modified time of *path* as an ISO 8601 UTC string."""
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def walk_repo(
    root: str,
    max_depth: int | None = None,
) -> Iterator[FileRecord]:
    """Yield :class:`FileRecord` objects for every non-skipped file under *root*.

    Traversal is top-down. Skipped directories are pruned in-place so their
    subtrees are never visited.  Noisy files are yielded but have
    ``is_noisy=True`` so callers can choose how to handle them.

    Args:
        root: absolute path to the repository root.
        max_depth: if set, only files at or above this depth are yielded.
                   Depth is 0-indexed (files directly in *root* are depth 0).

    Yields:
        :class:`FileRecord` for each file that passes the directory skip rules.
    """
    root = os.path.realpath(root)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Compute the relative path of the current directory from root.
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_parts: tuple[str, ...] = ()
            depth = 0
        else:
            rel_parts = tuple(rel_dir.split(os.sep))
            depth = len(rel_parts)

        # Enforce max_depth on directories: prune dirs that would exceed it.
        if max_depth is not None and depth >= max_depth:
            dirnames.clear()

        # Prune skipped directories in-place (modifying dirnames affects walk).
        dirnames[:] = [
            d
            for d in dirnames
            if not _should_skip_dir(d, rel_parts + (d,))
        ]

        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)

            try:
                size_bytes = os.path.getsize(abs_path)
            except OSError:
                continue  # skip unreadable files silently

            is_noisy = _is_noisy_file(filename, size_bytes)

            # Build the relative path with forward slashes.
            if rel_dir == ".":
                rel_file_path = filename
            else:
                rel_file_path = rel_dir.replace(os.sep, "/") + "/" + filename

            yield FileRecord(
                path=rel_file_path,
                abs_path=abs_path,
                size_bytes=size_bytes,
                depth=depth,
                last_modified_ts=_mtime_iso(abs_path),
                is_noisy=is_noisy,
            )

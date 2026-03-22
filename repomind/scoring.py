"""Importance scoring for files and directories."""

from __future__ import annotations

import re

from repomind.models import ClassifiedFile

# ---------------------------------------------------------------------------
# Base scores by file type (ARCHITECTURE.md §9)
# ---------------------------------------------------------------------------

_BASE_SCORES: dict[str, float] = {
    "manifest": 1.00,
    "entrypoint": 0.90,
    "config": 0.75,
    "docs": 0.55,
    "test": 0.45,
    "source": 0.40,
    "generated": 0.20,
    "other": 0.20,
}

# ---------------------------------------------------------------------------
# File importance scoring
# ---------------------------------------------------------------------------

# How many of the most-recently-modified files get the recent-modification bonus.
RECENT_MODIFIED_TOP_N: int = 30

# Content read cap per file for inbound-reference scanning (bytes).
_REF_SCAN_MAX_BYTES: int = 50_000

# Minimum stem length to consider for inbound reference matching.
_REF_MIN_STEM_LEN: int = 4


def score_file(
    file_type: str,
    depth: int,
    line_count: int | None,
    inbound_ref_count: int,
    is_recently_modified: bool,
) -> float:
    """Compute the importance score for a single file.

    Pure function — all inputs are pre-computed by the caller.

    Args:
        file_type: one of the eight v1 file types.
        depth: directory depth from repo root (0 = root level).
        line_count: total line count, or None if unavailable.
        inbound_ref_count: number of other indexed files that reference this one.
        is_recently_modified: True if this file is in the top
            ``RECENT_MODIFIED_TOP_N`` most recently modified files.

    Returns:
        Importance score clamped to [0.0, 1.50].
    """
    base = _BASE_SCORES.get(file_type, 0.20)

    depth_bonus = max(0.0, 0.20 - 0.03 * depth)
    line_bonus = 0.10 if line_count is not None and 80 <= line_count <= 800 else 0.0
    recent_bonus = 0.10 if is_recently_modified else 0.0
    inbound_ref_bonus = min(0.20, inbound_ref_count * 0.02)
    # Root-level documentation files get a small extra signal.
    root_docs_bonus = 0.10 if depth == 0 and file_type == "docs" else 0.0
    # Generated / noisy files incur a penalty on top of their lower base score.
    noisy_penalty = 0.30 if file_type == "generated" else 0.0

    raw = (
        base
        + depth_bonus
        + line_bonus
        + recent_bonus
        + inbound_ref_bonus
        + root_docs_bonus
        - noisy_penalty
    )
    return round(min(1.50, max(0.0, raw)), 4)


# ---------------------------------------------------------------------------
# Directory importance scoring
# ---------------------------------------------------------------------------


def score_directory(
    file_scores: list[float],
    dir_depth: int,
    manifest_count: int = 0,
    config_count: int = 0,
    entrypoint_count: int = 0,
) -> float:
    """Compute the importance score for a directory.

    Args:
        file_scores: importance scores of files directly contained in the dir.
        dir_depth: depth of this directory from the repo root (0 = root).
        manifest_count: number of manifest files directly in this directory.
        config_count: number of config files directly in this directory.
        entrypoint_count: number of entrypoint files directly in this directory.

    Returns:
        Directory importance score clamped to [0.0, 1.50].
    """
    avg_score = sum(file_scores) / len(file_scores) if file_scores else 0.0
    depth_bonus = max(0.0, 0.20 - 0.03 * dir_depth)

    raw = (
        avg_score * 0.6
        + manifest_count * 0.1
        + config_count * 0.1
        + entrypoint_count * 0.1
        + depth_bonus
    )
    return round(min(1.50, max(0.0, raw)), 4)


# ---------------------------------------------------------------------------
# Recently-modified helper
# ---------------------------------------------------------------------------


def get_recently_modified_paths(
    files: list[ClassifiedFile],
    top_n: int = RECENT_MODIFIED_TOP_N,
) -> frozenset[str]:
    """Return the paths of the *top_n* most recently modified files.

    Files without a ``last_modified_ts`` are excluded from consideration.
    The timestamp strings are ISO 8601 so lexicographic sort is correct.
    """
    dated = [f for f in files if f.last_modified_ts is not None]
    dated.sort(key=lambda f: f.last_modified_ts or "", reverse=True)
    return frozenset(f.path for f in dated[:top_n])


# ---------------------------------------------------------------------------
# Inbound reference counting
# ---------------------------------------------------------------------------


def compute_inbound_refs(files: list[ClassifiedFile]) -> dict[str, int]:
    """Estimate how many other indexed files reference each file.

    For each non-noisy file, this scans its content (up to
    ``_REF_SCAN_MAX_BYTES``) for whole-word occurrences of other files'
    stems.  A match increments the target file's reference count.

    This is a best-effort heuristic: it will have false positives for
    stems that are common English words and false negatives for dynamic or
    aliased imports.  It is intentionally kept simple for v1.

    Args:
        files: all ClassifiedFile records for the current index run.

    Returns:
        Mapping of ``file.path → inbound_ref_count`` for every input file.
    """
    ref_counts: dict[str, int] = {f.path: 0 for f in files}

    # Build a map of stem → path for files with stems long enough to be useful.
    # Stem = filename without extension, lowercased.
    stem_to_path: dict[str, str] = {}
    for f in files:
        basename = f.path.rsplit("/", 1)[-1]
        stem = basename.rsplit(".", 1)[0].lower() if "." in basename else basename.lower()
        if len(stem) >= _REF_MIN_STEM_LEN:
            # Last writer wins for duplicate stems; good enough for v1.
            stem_to_path[stem] = f.path

    # Pre-compile patterns for each stem.
    stem_patterns: dict[str, re.Pattern[str]] = {
        stem: re.compile(r"\b" + re.escape(stem) + r"\b")
        for stem in stem_to_path
    }

    # Scan each non-noisy file's content.
    for f in files:
        if f.file_type == "generated":
            continue
        try:
            with open(f.abs_path, encoding="utf-8", errors="replace") as fh:
                content = fh.read(_REF_SCAN_MAX_BYTES).lower()
        except OSError:
            continue

        for stem, pattern in stem_patterns.items():
            target_path = stem_to_path[stem]
            if target_path == f.path:
                continue  # skip self-references
            if pattern.search(content):
                ref_counts[target_path] += 1

    return ref_counts

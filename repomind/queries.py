"""Query service: reads from SQLite index to serve tool responses."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from repomind.db import get_db_path, open_db
from repomind.refresh import refresh_index as _core_refresh
from repomind.repo import (
    get_branch,
    get_head_sha,
    is_git_repo,
    resolve_repo_root,
)

# ---------------------------------------------------------------------------
# Shared provenance helper
# ---------------------------------------------------------------------------


def _build_provenance(
    repo_root: str,
    indexed_branch: str | None,
    indexed_head_sha: str | None,
    indexed_at: str | None,
    current_branch: str | None,
    current_head_sha: str | None,
    stale: bool,
    partial: bool,
) -> dict:
    return {
        "repo_root": repo_root,
        "indexed_branch": indexed_branch,
        "indexed_head_sha": indexed_head_sha,
        "indexed_at": indexed_at,
        "current_branch": current_branch,
        "current_head_sha": current_head_sha,
        "stale": stale,
        "partial": partial,
    }


# ---------------------------------------------------------------------------
# get_index_status
# ---------------------------------------------------------------------------


@dataclass
class IndexStatus:
    """Result of :func:`get_index_status`."""

    # Whether the repo is a Git repository right now.
    is_git_repo: bool
    # Whether the index DB file exists at all.
    has_index: bool
    # Values stored in the index (None if no index).
    indexed_branch: str | None
    indexed_head_sha: str | None
    indexed_at: str | None
    # Current Git state (None for non-Git repos or if Git is unavailable).
    current_branch: str | None
    current_head_sha: str | None
    # Staleness: True when the index was built on a different branch or HEAD.
    stale: bool
    # Whether a refresh is recommended before trusting other query results.
    refresh_recommended: bool
    # The tool the caller should invoke next.
    recommended_first_call: str  # "refresh_index" | "get_repo_overview"
    # Whether the stored index is a partial index (depth-capped).
    partial: bool
    # Provenance block attached to every tool response.
    provenance: dict = field(default_factory=dict)


def get_index_status(repo_root: str) -> IndexStatus:
    """Return the current index freshness state for *repo_root*.

    Three cases (per ARCHITECTURE.md §11 acceptance criteria):
    1. No index exists → recommend ``refresh_index``.
    2. Index exists and is current (branch + HEAD match) → recommend
       ``get_repo_overview``.
    3. Index exists but is stale (branch or HEAD differs) → recommend
       ``refresh_index``.

    For non-Git repositories, staleness cannot be detected; the index is
    treated as current if it exists.

    Args:
        repo_root: path to the repository root (resolved internally).

    Returns:
        :class:`IndexStatus` with all freshness fields populated.

    Raises:
        ValueError: if *repo_root* is not a valid directory path.
    """
    repo_root = resolve_repo_root(repo_root)

    # Current Git state.
    git = is_git_repo(repo_root)
    current_branch = get_branch(repo_root) if git else None
    current_head = get_head_sha(repo_root) if git else None

    # Does the index DB exist?
    db_path = get_db_path(repo_root)
    if not db_path.exists():
        prov = _build_provenance(
            repo_root=repo_root,
            indexed_branch=None,
            indexed_head_sha=None,
            indexed_at=None,
            current_branch=current_branch,
            current_head_sha=current_head,
            stale=False,
            partial=False,
        )
        return IndexStatus(
            is_git_repo=git,
            has_index=False,
            indexed_branch=None,
            indexed_head_sha=None,
            indexed_at=None,
            current_branch=current_branch,
            current_head_sha=current_head,
            stale=False,
            refresh_recommended=True,
            recommended_first_call="refresh_index",
            partial=False,
            provenance=prov,
        )

    # Index exists — load metadata.
    conn = open_db(repo_root)
    try:
        row = conn.execute("SELECT * FROM repo_index LIMIT 1").fetchone()
    finally:
        conn.close()

    if row is None:
        # DB file exists but repo_index table is empty (e.g. interrupted refresh).
        prov = _build_provenance(
            repo_root=repo_root,
            indexed_branch=None,
            indexed_head_sha=None,
            indexed_at=None,
            current_branch=current_branch,
            current_head_sha=current_head,
            stale=False,
            partial=False,
        )
        return IndexStatus(
            is_git_repo=git,
            has_index=False,
            indexed_branch=None,
            indexed_head_sha=None,
            indexed_at=None,
            current_branch=current_branch,
            current_head_sha=current_head,
            stale=False,
            refresh_recommended=True,
            recommended_first_call="refresh_index",
            partial=False,
            provenance=prov,
        )

    indexed_branch = row["branch_name"]
    indexed_head = row["head_sha"]
    indexed_at = row["indexed_at"]
    partial = bool(row["partial_index"])

    # Staleness is only meaningful for Git repos.
    if git:
        stale = (current_branch != indexed_branch) or (current_head != indexed_head)
    else:
        stale = False

    recommended_first_call = "refresh_index" if stale else "get_repo_overview"

    prov = _build_provenance(
        repo_root=repo_root,
        indexed_branch=indexed_branch,
        indexed_head_sha=indexed_head,
        indexed_at=indexed_at,
        current_branch=current_branch,
        current_head_sha=current_head,
        stale=stale,
        partial=partial,
    )

    return IndexStatus(
        is_git_repo=git,
        has_index=True,
        indexed_branch=indexed_branch,
        indexed_head_sha=indexed_head,
        indexed_at=indexed_at,
        current_branch=current_branch,
        current_head_sha=current_head,
        stale=stale,
        refresh_recommended=stale,
        recommended_first_call=recommended_first_call,
        partial=partial,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# run_refresh_index
# ---------------------------------------------------------------------------


@dataclass
class RefreshIndexResult:
    """Result of :func:`run_refresh_index` — matches ARCHITECTURE.md §11 contract."""

    status: str              # "ok" | "error"
    refreshed: bool
    files_indexed: int
    directories_indexed: int
    partial: bool
    partial_reason: str | None
    error_message: str | None
    provenance: dict = field(default_factory=dict)


def run_refresh_index(repo_root: str) -> RefreshIndexResult:
    """Run a full index refresh and return a structured result with provenance.

    Wraps the core :func:`repomind.refresh.refresh_index` pipeline and attaches
    a provenance block reflecting the index state after the refresh attempt.

    On success the provenance will show ``stale=False`` because the newly
    written index matches the current branch and HEAD.  On failure the
    provenance reflects whatever index exists (or empty if none).

    Args:
        repo_root: path to the repository root.

    Returns:
        :class:`RefreshIndexResult` — ``status="ok"`` on success,
        ``status="error"`` if the pipeline failed (live DB untouched).

    Raises:
        ValueError: if *repo_root* is not a valid directory path.
    """
    repo_root = resolve_repo_root(repo_root)
    core = _core_refresh(repo_root)

    # get_index_status gives us the correct provenance in both the success
    # case (index is now current) and the failure case (existing index or
    # missing index).  It handles all the branch/HEAD comparison internally.
    index_status = get_index_status(repo_root)

    return RefreshIndexResult(
        status=core.status,
        refreshed=core.refreshed,
        files_indexed=core.files_indexed,
        directories_indexed=core.directories_indexed,
        partial=core.partial,
        partial_reason=core.partial_reason,
        error_message=core.error_message,
        provenance=index_status.provenance,
    )


# ---------------------------------------------------------------------------
# get_repo_overview
# ---------------------------------------------------------------------------

# File extension → language name.  Used to derive stack_hints.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".scala": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
    ".clj": "clojure",
    ".hs": "haskell",
    ".dart": "dart",
    ".sh": "shell",
    ".bash": "shell",
}

# Token keyword → tool/framework label.  Checked against stored path and
# header token JSON columns (substring match on quoted token string).
_TOOL_KEYWORDS: dict[str, str] = {
    "mcp": "mcp",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "react": "react",
    "vue": "vue",
    "graphql": "graphql",
    "grpc": "grpc",
    "rails": "rails",
    "spring": "spring",
    "express": "express",
}

# Maximum items returned in overview lists.
_TOP_DIRS_LIMIT = 10
_CRITICAL_FILES_LIMIT = 10


def _derive_stack_hints(conn: sqlite3.Connection, repo_id: str) -> list[str]:
    """Derive tech-stack labels from indexed extension counts and token columns.

    Returns up to 3 language hints (ordered by file count) followed by any
    tool/framework hints found in path or header tokens (sorted).
    """
    # Language hints: group by extension, walk by count descending.
    ext_rows = conn.execute(
        """
        SELECT extension, COUNT(*) AS cnt
        FROM files
        WHERE repo_id = ? AND file_type != 'generated' AND extension IS NOT NULL
        GROUP BY extension
        ORDER BY cnt DESC
        """,
        (repo_id,),
    ).fetchall()

    seen_langs: set[str] = set()
    lang_hints: list[str] = []
    for row in ext_rows:
        lang = _EXT_TO_LANG.get(row["extension"])
        if lang and lang not in seen_langs:
            seen_langs.add(lang)
            lang_hints.append(lang)
            if len(lang_hints) == 3:
                break

    # Tool hints: substring scan on raw token JSON (quoted-token check avoids
    # false positives, e.g. "document" containing "doc").
    token_rows = conn.execute(
        """
        SELECT path_tokens_json, header_tokens_json
        FROM files
        WHERE repo_id = ? AND file_type != 'generated'
        """,
        (repo_id,),
    ).fetchall()

    seen_tools: set[str] = set()
    tool_hints: list[str] = []
    for row in token_rows:
        combined = (row["path_tokens_json"] or "") + (row["header_tokens_json"] or "")
        for kw, label in _TOOL_KEYWORDS.items():
            if label not in seen_tools and f'"{kw}"' in combined:
                seen_tools.add(label)
                tool_hints.append(label)

    return lang_hints + sorted(tool_hints)


@dataclass
class RepoOverview:
    """Result of :func:`get_repo_overview`."""

    repo_name: str
    repo_root: str
    is_git_repo: bool
    stack_hints: list[str]
    top_directories: list[dict]
    critical_files: list[dict]
    provenance: dict = field(default_factory=dict)


def get_repo_overview(repo_root: str) -> RepoOverview:
    """Return a high-level orientation snapshot for *repo_root*.

    Queries the index for repo metadata, the top-scored directories, and the
    top-scored non-generated files.  Stack hints are derived from extension
    counts and stored token columns.

    Args:
        repo_root: path to the repository root (resolved internally).

    Returns:
        :class:`RepoOverview` matching the ARCHITECTURE.md §11 contract.

    Raises:
        ValueError: if *repo_root* is not a valid directory, or if no index
            exists (caller should run ``refresh_index`` first).
    """
    repo_root = resolve_repo_root(repo_root)
    status = get_index_status(repo_root)

    if not status.has_index:
        raise ValueError(
            f"No index found for {repo_root!r}. Run refresh_index first."
        )

    conn = open_db(repo_root)
    try:
        meta = conn.execute("SELECT * FROM repo_index LIMIT 1").fetchone()
        repo_id: str = meta["repo_id"]
        repo_name: str = meta["repo_name"]
        is_git: bool = bool(meta["is_git_repo"])

        stack_hints = _derive_stack_hints(conn, repo_id)

        dir_rows = conn.execute(
            """
            SELECT path, role, importance_score
            FROM directories
            WHERE repo_id = ?
            ORDER BY importance_score DESC
            LIMIT ?
            """,
            (repo_id, _TOP_DIRS_LIMIT),
        ).fetchall()
        top_directories = [
            {
                "path": r["path"],
                "role": r["role"],
                "importance_score": r["importance_score"],
            }
            for r in dir_rows
        ]

        file_rows = conn.execute(
            """
            SELECT path, file_type, importance_score
            FROM files
            WHERE repo_id = ? AND file_type != 'generated'
            ORDER BY importance_score DESC
            LIMIT ?
            """,
            (repo_id, _CRITICAL_FILES_LIMIT),
        ).fetchall()
        critical_files = [
            {
                "path": r["path"],
                "file_type": r["file_type"],
                "importance_score": r["importance_score"],
            }
            for r in file_rows
        ]
    finally:
        conn.close()

    return RepoOverview(
        repo_name=repo_name,
        repo_root=repo_root,
        is_git_repo=is_git,
        stack_hints=stack_hints,
        top_directories=top_directories,
        critical_files=critical_files,
        provenance=status.provenance,
    )


# ---------------------------------------------------------------------------
# get_directory_map
# ---------------------------------------------------------------------------


@dataclass
class DirectoryMap:
    """Result of :func:`get_directory_map`."""

    directories: list[dict]
    provenance: dict = field(default_factory=dict)


def get_directory_map(
    repo_root: str,
    path_filter: str | None = None,
) -> DirectoryMap:
    """Return all indexed directories ordered by importance score.

    Optionally restrict to directories whose path starts with *path_filter*
    (e.g. ``"src"`` returns ``src``, ``src/utils``, etc.).

    Args:
        repo_root: path to the repository root (resolved internally).
        path_filter: optional directory path prefix to restrict results.
            Leading/trailing slashes are stripped before matching.

    Returns:
        :class:`DirectoryMap` matching the ARCHITECTURE.md §11 contract.

    Raises:
        ValueError: if *repo_root* is not a valid directory, or if no index
            exists (caller should run ``refresh_index`` first).
    """
    import json as _json

    repo_root = resolve_repo_root(repo_root)
    status = get_index_status(repo_root)

    if not status.has_index:
        raise ValueError(
            f"No index found for {repo_root!r}. Run refresh_index first."
        )

    # Normalise the filter: strip slashes so "src/", "/src", "src" all work.
    normalized_filter: str | None = None
    if path_filter is not None:
        normalized_filter = path_filter.strip("/")

    conn = open_db(repo_root)
    try:
        meta = conn.execute("SELECT repo_id FROM repo_index LIMIT 1").fetchone()
        repo_id: str = meta["repo_id"]

        dir_rows = conn.execute(
            """
            SELECT path, role, summary, representative_files_json, importance_score
            FROM directories
            WHERE repo_id = ?
            ORDER BY importance_score DESC
            """,
            (repo_id,),
        ).fetchall()
    finally:
        conn.close()

    directories: list[dict] = []
    for row in dir_rows:
        path: str = row["path"]
        if normalized_filter is not None:
            # Include exact match and any child paths.
            if path != normalized_filter and not path.startswith(
                normalized_filter + "/"
            ):
                continue
        directories.append(
            {
                "path": path,
                "role": row["role"],
                "summary": row["summary"],
                "representative_files": _json.loads(
                    row["representative_files_json"] or "[]"
                ),
                "importance_score": row["importance_score"],
            }
        )

    return DirectoryMap(directories=directories, provenance=status.provenance)

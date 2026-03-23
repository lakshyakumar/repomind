"""Query service: reads from SQLite index to serve tool responses."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from repomind.db import get_db_path, open_db
from repomind.extractor import _tokenize as _tokenize_text
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
    partial_reason: dict[str, Any] | None = None,
    quality_signal: str = "degraded",
) -> dict:
    prov: dict[str, Any] = {
        "repo_root": repo_root,
        "indexed_branch": indexed_branch,
        "indexed_head_sha": indexed_head_sha,
        "indexed_at": indexed_at,
        "current_branch": current_branch,
        "current_head_sha": current_head_sha,
        "stale": stale,
        "partial": partial,
        "quality_signal": quality_signal,
    }
    if partial and partial_reason is not None:
        prov["partial_reason"] = partial_reason
    return prov


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
    # Trust signals (I2-T6).
    # Seconds elapsed since the index was written; None when no index exists.
    age_seconds: float | None
    # Number of files stored in the index; None when no index exists.
    indexed_file_count: int | None
    # Composite trust signal: "full" | "partial" | "degraded".
    # "degraded" = no index; "partial" = partial index; "full" = complete index.
    quality_signal: str
    # Provenance block attached to every tool response.
    provenance: dict = field(default_factory=dict)


def _index_age_seconds(indexed_at: str | None) -> float | None:
    """Return elapsed seconds since *indexed_at* (UTC ISO string), or None."""
    if indexed_at is None:
        return None
    try:
        dt = datetime.fromisoformat(indexed_at)
        return (datetime.now(tz=timezone.utc) - dt).total_seconds()
    except (ValueError, TypeError):
        return None


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
            quality_signal="degraded",
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
            age_seconds=None,
            indexed_file_count=None,
            quality_signal="degraded",
            provenance=prov,
        )

    # Index exists — load metadata.
    conn = open_db(repo_root)
    try:
        row = conn.execute("SELECT * FROM repo_index LIMIT 1").fetchone()
        if row is not None:
            file_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM files WHERE repo_id = ?",
                (row["repo_id"],),
            ).fetchone()
            indexed_file_count: int | None = file_count_row["cnt"]
        else:
            indexed_file_count = None
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
            quality_signal="degraded",
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
            age_seconds=None,
            indexed_file_count=None,
            quality_signal="degraded",
            provenance=prov,
        )

    indexed_branch = row["branch_name"]
    indexed_head = row["head_sha"]
    indexed_at = row["indexed_at"]
    partial = bool(row["partial_index"])

    # Deserialize partial_reason JSON if present.
    _raw_reason = row["partial_reason"]
    partial_reason: dict[str, Any] | None
    if _raw_reason is not None:
        try:
            partial_reason = json.loads(_raw_reason)
        except (json.JSONDecodeError, TypeError):
            partial_reason = None
    else:
        partial_reason = None

    age_seconds = _index_age_seconds(indexed_at)
    quality_signal = "partial" if partial else "full"

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
        partial_reason=partial_reason,
        quality_signal=quality_signal,
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
        age_seconds=age_seconds,
        indexed_file_count=indexed_file_count,
        quality_signal=quality_signal,
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
    partial_reason: dict[str, Any] | None  # {"cap_type": str, "cap_value": int} | None
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
                "representative_files": json.loads(
                    row["representative_files_json"] or "[]"
                ),
                "importance_score": row["importance_score"],
            }
        )

    return DirectoryMap(directories=directories, provenance=status.provenance)


# ---------------------------------------------------------------------------
# get_critical_files
# ---------------------------------------------------------------------------

_FILE_TYPE_REASON: dict[str, str] = {
    "manifest": "Project manifest",
    "config": "Configuration file",
    "entrypoint": "Application entrypoint",
    "docs": "Documentation",
    "test": "Test file",
    "source": "Source file",
    "other": "Indexed file",
}


@dataclass
class CriticalFiles:
    """Result of :func:`get_critical_files`."""

    files: list[dict]
    provenance: dict = field(default_factory=dict)


def get_critical_files(repo_root: str) -> CriticalFiles:
    """Return indexed files ranked by importance score, excluding generated files.

    Files with ``file_type == 'generated'`` are excluded.  Each entry carries
    a human-readable *reason* derived from its ``file_type``.

    Args:
        repo_root: path to the repository root (resolved internally).

    Returns:
        :class:`CriticalFiles` matching the ARCHITECTURE.md §11 contract.

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
        meta = conn.execute("SELECT repo_id FROM repo_index LIMIT 1").fetchone()
        repo_id: str = meta["repo_id"]

        file_rows = conn.execute(
            """
            SELECT path, file_type, importance_score
            FROM files
            WHERE repo_id = ? AND file_type != 'generated'
            ORDER BY importance_score DESC
            """,
            (repo_id,),
        ).fetchall()
    finally:
        conn.close()

    files: list[dict] = [
        {
            "path": row["path"],
            "file_type": row["file_type"],
            "importance_score": row["importance_score"],
            "reason": _FILE_TYPE_REASON.get(row["file_type"], "Indexed file"),
        }
        for row in file_rows
    ]

    return CriticalFiles(files=files, provenance=status.provenance)


# ---------------------------------------------------------------------------
# get_recent_changes
# ---------------------------------------------------------------------------


@dataclass
class RecentChanges:
    """Result of :func:`get_recent_changes`."""

    is_git_repo: bool
    commits: list[dict]
    provenance: dict = field(default_factory=dict)


def get_recent_changes(repo_root: str) -> RecentChanges:
    """Return recent commits and their changed files from the index.

    For non-Git repos the function degrades cleanly: ``is_git_repo`` is
    ``False`` and ``commits`` is an empty list.

    Args:
        repo_root: path to the repository root (resolved internally).

    Returns:
        :class:`RecentChanges` matching the ARCHITECTURE.md §11 contract.

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

    if not status.is_git_repo:
        return RecentChanges(
            is_git_repo=False,
            commits=[],
            provenance=status.provenance,
        )

    conn = open_db(repo_root)
    try:
        meta = conn.execute("SELECT repo_id FROM repo_index LIMIT 1").fetchone()
        repo_id: str = meta["repo_id"]

        commit_rows = conn.execute(
            """
            SELECT commit_sha, subject, author_name, authored_at
            FROM recent_commits
            WHERE repo_id = ?
            ORDER BY authored_at DESC
            """,
            (repo_id,),
        ).fetchall()

        # Batch-load all changed files in one query to avoid N+1 queries.
        if commit_rows:
            shas = [r["commit_sha"] for r in commit_rows]
            placeholders = ",".join("?" * len(shas))
            file_rows = conn.execute(
                f"""
                SELECT commit_sha, path
                FROM commit_files
                WHERE repo_id = ? AND commit_sha IN ({placeholders})
                ORDER BY commit_sha, path
                """,
                [repo_id, *shas],
            ).fetchall()
        else:
            file_rows = []
    finally:
        conn.close()

    # Group files by commit sha.
    files_by_sha: dict[str, list[str]] = {}
    for fr in file_rows:
        files_by_sha.setdefault(fr["commit_sha"], []).append(fr["path"])

    commits: list[dict] = [
        {
            "commit_sha": r["commit_sha"],
            "subject": r["subject"],
            "author_name": r["author_name"],
            "authored_at": r["authored_at"],
            "files": files_by_sha.get(r["commit_sha"], []),
        }
        for r in commit_rows
    ]

    return RecentChanges(
        is_git_repo=True,
        commits=commits,
        provenance=status.provenance,
    )


# ---------------------------------------------------------------------------
# get_edit_suggestions
# ---------------------------------------------------------------------------

_DEFAULT_SUGGESTION_LIMIT: int = 10
_HIGH_IMPORTANCE_THRESHOLD: float = 0.7

# ---------------------------------------------------------------------------
# Scoring formula constants (I2-T4a)
# Relevance weights must sum to 1.0.
# ---------------------------------------------------------------------------
_W_PATH: float = 0.45       # path token overlap
_W_DIR: float = 0.25        # directory token overlap
_W_HEADER: float = 0.15     # header comment token overlap
_W_IMPORT: float = 0.15     # import statement token overlap (I2-T2+)
_W_RELEVANCE: float = 0.70  # relevance weight in final_score
_W_IMPORTANCE: float = 0.30  # importance weight in final_score
# Inbound-ref signal stays indirect: it is already baked into importance_score
# via score_file() in the indexer, so it influences _W_IMPORTANCE without
# requiring a separate direct term here.


@dataclass
class EditSuggestions:
    """Result of :func:`get_edit_suggestions`."""

    task: str
    suggestions: list[dict]
    # "fts" when the primary FTS5 retrieval produced candidates;
    # "fallback" when FTS returned zero results and the full-table-scan path
    # was used instead.  Present for observability; not part of the public
    # response contract.
    retrieval_method: str = "fallback"
    # Non-None only when suggestions is empty:
    #   "no_token_overlap"  — task had scoreable tokens but no file matched
    #   "stop_words_only"   — task reduced to empty token set after filtering
    #   None                — suggestions list is non-empty
    empty_reason: str | None = None
    provenance: dict = field(default_factory=dict)


def _build_fts_match(task_tokens: set[str]) -> str:
    """Build an FTS5 MATCH expression with prefix matching for each task token.

    Prefix queries (``token*``) allow 'webhook' to surface documents containing
    'webhooks'.  This is the correct form for I2-T3 retrieval.
    Tokens are sorted for deterministic, readable query strings.
    """
    return " OR ".join(f"{t}*" for t in sorted(task_tokens))


def _confidence(
    matched_path: list[str],
    matched_dir: list[str],
    matched_header: list[str],
    final_score: float,
) -> str:
    """Derive a conservative confidence label from signal breadth and score."""
    signal_count = sum([bool(matched_path), bool(matched_dir), bool(matched_header)])
    if signal_count == 3 and final_score >= 0.6:
        return "high"
    if signal_count >= 2 and final_score >= 0.4:
        return "medium"
    return "low"


def get_edit_suggestions(
    repo_root: str,
    task: str,
    limit: int = _DEFAULT_SUGGESTION_LIMIT,
) -> EditSuggestions:
    """Return ranked file suggestions for *task* based on token overlap and importance.

    Scoring per ARCHITECTURE.md §10:
    - tokenize *task* into lowercase unique tokens (same rules as indexer)
    - for each indexed file compute overlap against path_tokens, directory_tokens
      (derived from directory_path at query time), and header_tokens
    - ``relevance_score = 0.5 * path_overlap + 0.3 * dir_overlap + 0.2 * header_overlap``
    - exclude files with ``relevance_score == 0``
    - ``final_score = 0.7 * relevance_score + 0.3 * normalized_importance``
    - return top *limit* results ordered by final_score descending

    Args:
        repo_root: path to the repository root (resolved internally).
        task: natural-language description of the edit task.
        limit: maximum number of suggestions to return (default 10).

    Returns:
        :class:`EditSuggestions` matching the ARCHITECTURE.md §11 contract.

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

    task_tokens: set[str] = set(_tokenize_text(task))
    if not task_tokens:
        # Task reduced to nothing after stop-word filtering — no signal to match on.
        return EditSuggestions(
            task=task,
            suggestions=[],
            retrieval_method="fallback",
            empty_reason="stop_words_only",
            provenance=status.provenance,
        )

    conn = open_db(repo_root)
    try:
        meta = conn.execute("SELECT repo_id FROM repo_index LIMIT 1").fetchone()
        repo_id: str = meta["repo_id"]

        # ------------------------------------------------------------------
        # Primary: FTS5 candidate retrieval (prefix match per token, OR-joined)
        # ------------------------------------------------------------------
        retrieval_method = "fts"
        try:
            fts_match = _build_fts_match(task_tokens)
            file_rows = conn.execute(
                """
                SELECT f.path, f.directory_path, f.file_type, f.importance_score,
                       f.path_tokens_json, f.header_tokens_json, f.import_tokens_json
                FROM files f
                WHERE f.repo_id = ?
                  AND f.id IN (
                      SELECT rowid FROM files_fts WHERE files_fts MATCH ?
                  )
                """,
                (repo_id, fts_match),
            ).fetchall()
        except Exception:  # noqa: BLE001 — graceful fallback if FTS table absent
            file_rows = []

        # ------------------------------------------------------------------
        # Fallback: full table scan when FTS produced zero candidates
        # ------------------------------------------------------------------
        if not file_rows:
            retrieval_method = "fallback"
            file_rows = conn.execute(
                """
                SELECT path, directory_path, file_type, importance_score,
                       path_tokens_json, header_tokens_json, import_tokens_json
                FROM files
                WHERE repo_id = ?
                """,
                (repo_id,),
            ).fetchall()
    finally:
        conn.close()

    n: int = len(task_tokens)
    suggestions: list[dict] = []

    for row in file_rows:
        path_tokens: set[str] = set(json.loads(row["path_tokens_json"] or "[]"))
        dir_tokens: set[str] = set(_tokenize_text(row["directory_path"] or ""))
        header_tokens: set[str] = set(json.loads(row["header_tokens_json"] or "[]"))
        import_tokens: set[str] = set(json.loads(row["import_tokens_json"] or "[]"))

        matched_path = sorted(task_tokens & path_tokens)
        matched_dir = sorted(task_tokens & dir_tokens)
        matched_header = sorted(task_tokens & header_tokens)
        matched_import = sorted(task_tokens & import_tokens)

        path_overlap = len(matched_path) / n
        dir_overlap = len(matched_dir) / n
        header_overlap = len(matched_header) / n
        import_overlap = len(matched_import) / n

        relevance_score = (
            _W_PATH * path_overlap
            + _W_DIR * dir_overlap
            + _W_HEADER * header_overlap
            + _W_IMPORT * import_overlap
        )

        if relevance_score == 0.0:
            continue

        normalized_importance = min(1.0, row["importance_score"] / 1.5)
        final_score = _W_RELEVANCE * relevance_score + _W_IMPORTANCE * normalized_importance

        # Build human-readable reasons identifying which layer fired.
        # Path match label reflects the active retrieval path so agents can
        # tell whether the result came from FTS prefix or exact-token search.
        reasons: list[str] = []
        if matched_path:
            path_label = "fts" if retrieval_method == "fts" else "exact"
            reasons.append(
                f"Path match ({path_label}): {', '.join(matched_path)}"
            )
        if matched_dir:
            reasons.append(f"Directory token matched: {', '.join(matched_dir)}")
        if matched_header:
            reasons.append(f"Header tokens matched: {', '.join(matched_header)}")
        if matched_import:
            reasons.append(f"Import match: {', '.join(matched_import)}")
        if row["importance_score"] >= _HIGH_IMPORTANCE_THRESHOLD:
            reasons.append("High file importance score")

        suggestions.append(
            {
                "path": row["path"],
                "file_type": row["file_type"],
                "score": round(final_score, 4),
                "confidence": _confidence(matched_path, matched_dir, matched_header, final_score),
                "reason": reasons,
            }
        )

    suggestions.sort(key=lambda s: s["score"], reverse=True)
    top = suggestions[:limit]
    empty_reason: str | None = None if top else "no_token_overlap"
    return EditSuggestions(
        task=task,
        suggestions=top,
        retrieval_method=retrieval_method,
        empty_reason=empty_reason,
        provenance=status.provenance,
    )

"""Query service: reads from SQLite index to serve tool responses."""

from __future__ import annotations

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

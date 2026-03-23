"""MCP server: tool registration and dispatch."""

from __future__ import annotations

import dataclasses

import fastmcp

from repomind.queries import get_critical_files as _get_critical_files
from repomind.queries import get_directory_map as _get_directory_map
from repomind.queries import get_edit_suggestions as _get_edit_suggestions
from repomind.queries import get_index_status as _get_index_status
from repomind.queries import get_recent_changes as _get_recent_changes
from repomind.queries import get_repo_overview as _get_repo_overview
from repomind.queries import run_refresh_index as _run_refresh_index

mcp = fastmcp.FastMCP(
    name="repomind",
    instructions=(
        "Repomind is a query engine for grounded, indexed repo context. "
        "It does NOT answer natural-language questions and does NOT read source code directly. "
        "Always call get_index_status first when starting work on a repository. "
        "If stale=true, call refresh_index before trusting other results. "
        "If the index is current, call get_repo_overview next for orientation, "
        "then use get_edit_suggestions to narrow relevant files before reading raw source."
    ),
)


@mcp.tool()
def get_index_status(repo_root: str) -> dict:
    """Check the index state for a repository. Call this first.

    Returns whether the index is stale relative to the current branch and HEAD.
    The response includes recommended_first_call to guide the next step — follow
    it before calling any other tool.

    Args:
        repo_root: Absolute path to the repository root.
    """
    result = _get_index_status(repo_root)
    return dataclasses.asdict(result)


@mcp.tool()
def refresh_index(repo_root: str) -> dict:
    """Rebuild the repo index for the current branch and HEAD.

    Call this when get_index_status reports stale=true, or when no index exists yet.
    Walks the repository, classifies files and directories, gathers recent commits,
    and writes a fresh index to local storage. Provenance in the response confirms
    the indexed branch and HEAD SHA.

    Args:
        repo_root: Absolute path to the repository root.
    """
    result = _run_refresh_index(repo_root)
    return dataclasses.asdict(result)


@mcp.tool()
def get_repo_overview(repo_root: str) -> dict:
    """Return a high-level orientation snapshot: stack hints, top directories, and critical files.

    Call this after confirming the index is current (via get_index_status).
    Useful as the first substantive call when starting work on an unfamiliar repository.

    Args:
        repo_root: Absolute path to the repository root.
    """
    result = _get_repo_overview(repo_root)
    return dataclasses.asdict(result)


@mcp.tool()
def get_directory_map(
    repo_root: str,
    path_filter: str | None = None,
) -> dict:
    """Return ranked directories with their role, summary, and representative files.

    Directories are ordered by importance score descending. Use path_filter to restrict
    results to a subtree (e.g. "src" returns src and all nested directories under it).
    Useful for navigating large codebases without reading every file.

    Args:
        repo_root: Absolute path to the repository root.
        path_filter: Optional directory path prefix to restrict results (e.g. "src").
            Leading and trailing slashes are stripped before matching.
    """
    result = _get_directory_map(repo_root, path_filter=path_filter)
    return dataclasses.asdict(result)


@mcp.tool()
def get_critical_files(repo_root: str) -> dict:
    """Return indexed files ranked by importance score, excluding generated files.

    Each file includes its type (manifest, entrypoint, config, source, test, docs)
    and a human-readable reason. Use this to identify the highest-signal files in a
    repository before diving into specific directories.

    Args:
        repo_root: Absolute path to the repository root.
    """
    result = _get_critical_files(repo_root)
    return dataclasses.asdict(result)


@mcp.tool()
def get_recent_changes(repo_root: str) -> dict:
    """Return recent commits and their changed files from the index.

    For non-Git repositories, returns is_git_repo=false with an empty commits list.
    Commits are ordered most-recent-first. Useful for understanding what changed
    before starting a new task, or for establishing context about active work areas.

    Args:
        repo_root: Absolute path to the repository root.
    """
    result = _get_recent_changes(repo_root)
    return dataclasses.asdict(result)


@mcp.tool()
def get_edit_suggestions(
    repo_root: str,
    task: str,
    limit: int = 10,
) -> dict:
    """Return ranked file suggestions for a natural-language task description.

    Scores files by token overlap between the task and each file's path, directory,
    and header tokens, combined with the file's importance score. Files with zero
    token overlap are excluded. Each suggestion includes a reason list explaining
    which signals matched, and a conservative confidence label.

    Call this to narrow likely files before reading raw source — do not use it as
    a substitute for reading the files it returns.

    Args:
        repo_root: Absolute path to the repository root.
        task: Natural-language description of the edit task (e.g. "add retry logic
            for failed webhook delivery").
        limit: Maximum number of suggestions to return. Default is 10.
    """
    result = _get_edit_suggestions(repo_root, task=task, limit=limit)
    return dataclasses.asdict(result)


def main() -> None:
    """Entry point for the MCP server (stdio transport)."""
    mcp.run()

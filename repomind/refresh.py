"""Refresh coordinator: atomic write flow for index replacement."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from repomind.db import (
    CURRENT_SCHEMA_VERSION,
    get_db_path,
    get_tmp_db_path,
    open_fresh_db_at,
    repo_hash,
)
from repomind.extractor import classify_and_extract
from repomind.models import ClassifiedFile
from repomind.repo import (
    get_branch,
    get_head_sha,
    get_recent_commits,
    is_git_repo,
    resolve_repo_root,
)
from repomind.scoring import (
    compute_inbound_refs,
    get_recently_modified_paths,
    score_directory,
    score_file,
)
from repomind.walker import walk_repo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Repos above this file count are indexed with a depth cap.
_PARTIAL_FILE_THRESHOLD: int = 50_000
# Maximum depth used when partial indexing kicks in.
_PARTIAL_MAX_DEPTH: int = 3
# Top-N files to store per directory as representative files.
_REPRESENTATIVE_FILES_COUNT: int = 5

# ---------------------------------------------------------------------------
# Directory role inference
# ---------------------------------------------------------------------------

_DIR_ROLE_MAP: dict[str, str] = {
    "": "root",
    "src": "source",
    "lib": "source",
    "pkg": "source",
    "internal": "source",
    "app": "application",
    "core": "core",
    "tests": "testing",
    "test": "testing",
    "__tests__": "testing",
    "spec": "testing",
    "specs": "testing",
    "docs": "documentation",
    "doc": "documentation",
    "documentation": "documentation",
    "config": "configuration",
    "configs": "configuration",
    "scripts": "scripts",
    "tools": "tools",
    "api": "api",
    "handlers": "handlers",
    "routes": "routes",
    "models": "models",
    "schemas": "schemas",
    "utils": "utilities",
    "helpers": "utilities",
}


def _directory_role(dir_path: str) -> str | None:
    """Return a role string for *dir_path* based on its final path segment."""
    name = dir_path.rsplit("/", 1)[-1].lower() if "/" in dir_path else dir_path.lower()
    return _DIR_ROLE_MAP.get(name)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RefreshResult:
    """Outcome of a :func:`refresh_index` call."""

    status: str              # "ok" | "error"
    refreshed: bool
    files_indexed: int
    directories_indexed: int
    partial: bool
    partial_reason: str | None
    branch_name: str | None
    head_sha: str | None
    indexed_at: str
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Internal DB write helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _insert_run(
    conn: sqlite3.Connection,
    repo_id: str,
    branch: str | None,
    head: str | None,
    started_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO index_runs
          (repo_id, started_at, status, branch_name, head_sha, partial_index)
        VALUES (?, ?, 'running', ?, ?, 0)
        """,
        (repo_id, started_at, branch, head),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _complete_run(
    conn: sqlite3.Connection,
    run_id: int,
    files_count: int,
    dirs_count: int,
    partial: bool,
    error: str | None = None,
) -> None:
    status = "failed" if error else "completed"
    conn.execute(
        """
        UPDATE index_runs
        SET completed_at = ?, status = ?, files_indexed = ?,
            directories_indexed = ?, partial_index = ?, error_message = ?
        WHERE id = ?
        """,
        (_utc_now(), status, files_count, dirs_count, 1 if partial else 0, error, run_id),
    )
    conn.commit()


def _write_repo_index(
    conn: sqlite3.Connection,
    repo_id: str,
    repo_root: str,
    branch: str | None,
    head: str | None,
    indexed_at: str,
    is_git: bool,
    partial: bool,
    partial_reason: str | None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO repo_index
          (repo_id, repo_root, repo_name, branch_name, head_sha, indexed_at,
           is_git_repo, index_version, partial_index, partial_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repo_id,
            repo_root,
            Path(repo_root).name,
            branch,
            head,
            indexed_at,
            1 if is_git else 0,
            CURRENT_SCHEMA_VERSION,
            1 if partial else 0,
            partial_reason,
        ),
    )


def _write_files(
    conn: sqlite3.Connection,
    repo_id: str,
    scored_files: list[tuple[ClassifiedFile, float]],
    ref_counts: dict[str, int],
) -> None:
    rows = [
        (
            repo_id,
            cf.path,
            cf.directory_path,
            cf.extension,
            cf.size_bytes,
            cf.line_count,
            cf.depth,
            cf.file_type,
            score,
            ref_counts.get(cf.path, 0),
            json.dumps(cf.path_tokens),
            json.dumps(cf.header_tokens),
            None,  # representative_reason — derived at query time in T13
            cf.last_modified_ts,
        )
        for cf, score in scored_files
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO files
          (repo_id, path, directory_path, extension, size_bytes, line_count, depth,
           file_type, importance_score, inbound_ref_count, path_tokens_json,
           header_tokens_json, representative_reason, last_modified_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _write_directories(
    conn: sqlite3.Connection,
    repo_id: str,
    dir_records: list[dict],
) -> None:
    rows = [
        (
            repo_id,
            dr["path"],
            dr["depth"],
            dr["file_count"],
            dr["role"],
            None,  # summary — not computed in v1
            dr["representative_files_json"],
            dr["importance_score"],
        )
        for dr in dir_records
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO directories
          (repo_id, path, depth, file_count, role, summary,
           representative_files_json, importance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _write_commits(
    conn: sqlite3.Connection,
    repo_id: str,
    commits: list,
) -> None:
    for commit in commits:
        conn.execute(
            """
            INSERT OR IGNORE INTO recent_commits
              (repo_id, commit_sha, author_name, authored_at, subject, files_changed_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                repo_id,
                commit.hash,
                commit.author_name,
                commit.authored_at,
                commit.subject,
                len(commit.files_changed),
            ),
        )
        for path in commit.files_changed:
            conn.execute(
                """
                INSERT OR IGNORE INTO commit_files
                  (repo_id, commit_sha, path, change_type)
                VALUES (?, ?, ?, NULL)
                """,
                (repo_id, commit.hash, path),
            )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_temp_db(conn: sqlite3.Connection, repo_id: str) -> None:
    """Raise RuntimeError if the temp DB is missing required rows."""
    row = conn.execute(
        "SELECT repo_id FROM repo_index WHERE repo_id = ?", (repo_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError("repo_index row missing after write — DB may be corrupt")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def refresh_index(repo_root: str) -> RefreshResult:
    """Run a full index refresh for *repo_root*.

    Flow:
    1. Resolve and validate repo root.
    2. Detect Git metadata (branch, HEAD SHA).
    3. Walk all files; apply partial-index cap if repo is very large.
    4. Classify files, compute inbound refs, score files and directories.
    5. Gather recent commits (Git repos only).
    6. Write all data to a temp SQLite DB.
    7. Validate temp DB, then atomically rename it over the live DB.

    Returns:
        :class:`RefreshResult` — ``status="ok"`` on success, ``status="error"``
        if anything fails (live DB is never touched on error).

    Raises:
        ValueError: if *repo_root* is not a valid directory path.
    """
    indexed_at = _utc_now()
    branch: str | None = None
    head: str | None = None
    tmp_path: Path | None = None
    conn: sqlite3.Connection | None = None
    run_id: int | None = None

    try:
        repo_root = resolve_repo_root(repo_root)
        repo_id = repo_hash(repo_root)

        # Git metadata
        git = is_git_repo(repo_root)
        branch = get_branch(repo_root) if git else None
        head = get_head_sha(repo_root) if git else None

        tmp_path = get_tmp_db_path(repo_root)
        live_path = get_db_path(repo_root)

        conn = open_fresh_db_at(tmp_path)
        run_id = _insert_run(conn, repo_id, branch, head, indexed_at)

        # ------------------------------------------------------------------
        # Walk and classify
        # ------------------------------------------------------------------
        raw_files = list(walk_repo(repo_root))

        partial = len(raw_files) > _PARTIAL_FILE_THRESHOLD
        if partial:
            raw_files = [f for f in raw_files if f.depth <= _PARTIAL_MAX_DEPTH]
            partial_reason = (
                f"Repository exceeds {_PARTIAL_FILE_THRESHOLD} files; "
                f"index capped at depth {_PARTIAL_MAX_DEPTH}."
            )
        else:
            partial_reason = None

        classified = [classify_and_extract(f) for f in raw_files]

        # ------------------------------------------------------------------
        # Score files
        # ------------------------------------------------------------------
        ref_counts = compute_inbound_refs(classified)
        recently_modified = get_recently_modified_paths(classified)

        scored_files: list[tuple[ClassifiedFile, float]] = [
            (
                cf,
                score_file(
                    file_type=cf.file_type,
                    depth=cf.depth,
                    line_count=cf.line_count,
                    inbound_ref_count=ref_counts.get(cf.path, 0),
                    is_recently_modified=cf.path in recently_modified,
                ),
            )
            for cf in classified
        ]

        # ------------------------------------------------------------------
        # Build directory records
        # ------------------------------------------------------------------
        dir_groups: dict[str, list[tuple[ClassifiedFile, float]]] = defaultdict(list)
        for cf, score in scored_files:
            dir_groups[cf.directory_path].append((cf, score))

        dir_records: list[dict] = []
        for dir_path, entries in dir_groups.items():
            file_scores = [s for _, s in entries]
            depth = len(dir_path.split("/")) if dir_path else 0

            manifest_count = sum(1 for cf, _ in entries if cf.file_type == "manifest")
            config_count = sum(1 for cf, _ in entries if cf.file_type == "config")
            entrypoint_count = sum(1 for cf, _ in entries if cf.file_type == "entrypoint")

            dir_score = score_directory(
                file_scores=file_scores,
                dir_depth=depth,
                manifest_count=manifest_count,
                config_count=config_count,
                entrypoint_count=entrypoint_count,
            )

            top_files = [
                cf.path
                for cf, _ in sorted(entries, key=lambda x: x[1], reverse=True)[
                    :_REPRESENTATIVE_FILES_COUNT
                ]
            ]

            dir_records.append(
                {
                    "path": dir_path,
                    "depth": depth,
                    "file_count": len(entries),
                    "role": _directory_role(dir_path),
                    "representative_files_json": json.dumps(top_files),
                    "importance_score": dir_score,
                }
            )

        # ------------------------------------------------------------------
        # Recent commits (Git only)
        # ------------------------------------------------------------------
        commits = get_recent_commits(repo_root) if git else []

        # ------------------------------------------------------------------
        # Write to temp DB
        # ------------------------------------------------------------------
        _write_repo_index(
            conn, repo_id, repo_root, branch, head, indexed_at, git, partial, partial_reason
        )
        _write_files(conn, repo_id, scored_files, ref_counts)
        _write_directories(conn, repo_id, dir_records)
        _write_commits(conn, repo_id, commits)
        _complete_run(conn, run_id, len(scored_files), len(dir_records), partial)
        conn.commit()

        # ------------------------------------------------------------------
        # Validate before swap
        # ------------------------------------------------------------------
        _validate_temp_db(conn, repo_id)
        conn.close()
        conn = None

        # ------------------------------------------------------------------
        # Atomic swap
        # ------------------------------------------------------------------
        os.replace(str(tmp_path), str(live_path))

        return RefreshResult(
            status="ok",
            refreshed=True,
            files_indexed=len(scored_files),
            directories_indexed=len(dir_records),
            partial=partial,
            partial_reason=partial_reason,
            branch_name=branch,
            head_sha=head,
            indexed_at=indexed_at,
        )

    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)

        if conn is not None and run_id is not None:
            try:
                _complete_run(conn, run_id, 0, 0, False, error=err_msg)
            except Exception:  # noqa: BLE001
                pass

        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

        return RefreshResult(
            status="error",
            refreshed=False,
            files_indexed=0,
            directories_indexed=0,
            partial=False,
            partial_reason=None,
            branch_name=branch,
            head_sha=head,
            indexed_at=indexed_at,
            error_message=err_msg,
        )

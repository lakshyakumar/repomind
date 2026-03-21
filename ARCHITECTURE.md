# Architecture: Repomind v1

## 1. Purpose

This document turns the Repomind PRD into an implementation-ready technical architecture.

Repomind v1 is a local MCP server that indexes the currently checked-out state of a Git repository and returns structured, grounded repo data on demand. It records branch and commit metadata at index time, detects staleness when HEAD changes, and exposes a fixed MCP tool surface.

Repomind makes no LLM calls at query time.

## 2. Language Choice

**Language: Python**

### Rationale
- fast iteration for a docs-first MVP
- strong filesystem and SQLite ergonomics in the standard library
- simple Git integration through subprocess calls or lightweight libraries
- good fit for a deterministic local service with a small dependency surface

Repomind should not support both Python and TypeScript. v1 commits to Python.

## 3. Runtime Model

- local MCP server process
- locally deployable, with Docker support
- no hosted backend
- no background daemon required in v1
- one index per repository path
- index reflects the currently checked-out branch state at last refresh

The coding agent remains responsible for:
- deciding when to call Repomind
- reading actual source files before editing
- handling in-flight working tree changes in its own context

## 4. Repository and Index Model

### v1 scope decision
Repomind does **not** maintain simultaneous live indexes for multiple branches.

v1 behavior:
- index the currently checked-out branch state
- record `branch_name`, `head_sha`, and `indexed_at`
- on each query, compare current branch and HEAD to indexed metadata
- if different, mark the index stale
- require explicit refresh via `refresh_index`

## 5. Storage Layout

Default local storage root:

```text
~/.repomind/
  indexes/
    <repo_hash>.sqlite3
  tmp/
```

Where `repo_hash` is a stable hash of the normalized absolute repository root path.

## 6. SQLite Schema

```sql
CREATE TABLE repo_index (
  repo_id TEXT PRIMARY KEY,
  repo_root TEXT NOT NULL,
  repo_name TEXT NOT NULL,
  branch_name TEXT,
  head_sha TEXT,
  indexed_at TEXT NOT NULL,
  is_git_repo INTEGER NOT NULL,
  index_version INTEGER NOT NULL,
  partial_index INTEGER NOT NULL DEFAULT 0,
  partial_reason TEXT
);

CREATE TABLE directories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id TEXT NOT NULL,
  path TEXT NOT NULL,
  depth INTEGER NOT NULL,
  file_count INTEGER NOT NULL,
  role TEXT,
  summary TEXT,
  representative_files_json TEXT NOT NULL,
  importance_score REAL NOT NULL,
  UNIQUE(repo_id, path)
);

CREATE TABLE files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id TEXT NOT NULL,
  path TEXT NOT NULL,
  directory_path TEXT NOT NULL,
  extension TEXT,
  size_bytes INTEGER NOT NULL,
  line_count INTEGER,
  depth INTEGER NOT NULL,
  file_type TEXT NOT NULL,
  importance_score REAL NOT NULL,
  inbound_ref_count INTEGER NOT NULL DEFAULT 0,
  path_tokens_json TEXT NOT NULL,
  header_tokens_json TEXT NOT NULL,
  representative_reason TEXT,
  last_modified_ts TEXT,
  UNIQUE(repo_id, path)
);

CREATE TABLE recent_commits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  author_name TEXT,
  authored_at TEXT,
  subject TEXT NOT NULL,
  files_changed_count INTEGER,
  UNIQUE(repo_id, commit_sha)
);

CREATE TABLE commit_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  path TEXT NOT NULL,
  change_type TEXT,
  UNIQUE(repo_id, commit_sha, path)
);

CREATE TABLE index_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL,
  branch_name TEXT,
  head_sha TEXT,
  files_indexed INTEGER,
  directories_indexed INTEGER,
  partial_index INTEGER NOT NULL DEFAULT 0,
  error_message TEXT
);

CREATE INDEX idx_directories_repo_score ON directories(repo_id, importance_score DESC);
CREATE INDEX idx_files_repo_score ON files(repo_id, importance_score DESC);
CREATE INDEX idx_files_repo_type ON files(repo_id, file_type);
CREATE INDEX idx_files_repo_directory ON files(repo_id, directory_path);
CREATE INDEX idx_commits_repo_time ON recent_commits(repo_id, authored_at DESC);
CREATE INDEX idx_commit_files_repo_path ON commit_files(repo_id, path);
```

## 7. File Classification Model

`file_type` in v1 must be one of:
- `manifest`
- `config`
- `entrypoint`
- `docs`
- `test`
- `source`
- `generated`
- `other`

### Classification rules
Examples:
- `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod` → `manifest`
- `docker-compose.yml`, `.env.example`, `Makefile`, CI YAML → `config`
- `main.py`, `main.go`, `server.js`, `app.ts`, root router/bootstrap files → `entrypoint`
- `README.md`, `docs/**`, `ARCHITECTURE.md` → `docs`
- `tests/**`, `test/**`, `*.test.*`, `*.spec.*` → `test`
- normal application code → `source`
- skipped or derived files should not usually be inserted; if inserted for bookkeeping, classify as `generated`

## 8. Definitive Skip List

Repomind v1 must skip these directories during indexing:

```text
.git
node_modules
.venv
venv
__pycache__
dist
build
.next
.turbo
.cache
target
.gradle
coverage
vendor/bundle
```

Repomind v1 should skip or avoid deep content processing for:
- lockfiles
- minified assets
- sourcemaps
- large binaries
- images and media

Examples:
```text
package-lock.json
yarn.lock
pnpm-lock.yaml
*.min.js
*.map
*.png
*.jpg
*.jpeg
*.gif
*.webp
*.mp4
*.mov
*.pdf
```

## 9. Importance Scoring

### File importance score
The v1 file importance score is deterministic.

Base score by file type:
- manifest: `1.00`
- entrypoint: `0.90`
- config: `0.75`
- docs: `0.55`
- test: `0.45`
- source: `0.40`
- other: `0.20`

Adjustments:
- depth bonus: `max(0, 0.20 - 0.03 * depth)`
- line-count bonus: `+0.10` for files with 80 to 800 lines, else `0`
- recent modification bonus: `+0.10` if modified in the 30 most recently modified indexed files, else `0`
- inbound reference bonus: `min(0.20, inbound_ref_count * 0.02)`
- root documentation bonus: `+0.10` for root-level docs
- generated/noisy penalty: `-0.30`

Formula:
`importance_score = min(1.50, base + depth_bonus + line_bonus + recent_bonus + inbound_ref_bonus + root_docs_bonus - noisy_penalty)`

The score is stored in `files.importance_score`.

### Directory importance score
Directory score is the sum of:
- average importance of contained files multiplied by `0.6`
- count of manifest, config, and entrypoint files multiplied by `0.1` each
- shallow-depth bonus of `max(0, 0.2 - 0.03 * depth)`

This score is stored in `directories.importance_score`.

## 10. Edit Suggestion Heuristics

`get_edit_suggestions` is the most product-critical tool in v1 and must remain deterministic.

### Inputs
- natural-language task string
- optional result limit

### Candidate signals
For each indexed file, compute relevance using:
1. tokenized file path match
2. directory name match
3. file type match
4. extracted header comment token match where available
5. file importance score

### Scoring
- tokenize the task into lowercase unique tokens
- tokenize file path, directory path, and header tokens the same way
- `path_overlap = |task_tokens ∩ path_tokens| / |task_tokens|`
- `dir_overlap = |task_tokens ∩ directory_tokens| / |task_tokens|`
- `header_overlap = |task_tokens ∩ header_tokens| / |task_tokens|`
- `relevance_score = 0.5 * path_overlap + 0.3 * dir_overlap + 0.2 * header_overlap`
- exclude files where `relevance_score == 0`
- normalize `importance_score` to a `0..1` range with `normalized_importance = min(1.0, importance_score / 1.5)`
- `final_score = 0.7 * relevance_score + 0.3 * normalized_importance`

### Output behavior
- return top 10 results by default
- each result must include:
  - `path`
  - `file_type`
  - `score`
  - `reason[]`
  - `confidence`
- confidence is conservative in v1 and should default to `low` unless multiple signals align strongly

## 11. MCP Tool Contracts

All tool responses must include a provenance block:

```json
{
  "provenance": {
    "repo_root": "/abs/path/to/repo",
    "indexed_branch": "main",
    "indexed_head_sha": "abc123",
    "indexed_at": "2026-03-21T16:00:00Z",
    "current_branch": "main",
    "current_head_sha": "abc123",
    "stale": false,
    "partial": false
  }
}
```

### `get_repo_overview`
```json
{
  "repo_name": "repomind",
  "repo_root": "/repo",
  "is_git_repo": true,
  "stack_hints": ["python", "mcp"],
  "top_directories": [{"path": "src", "role": "application", "importance_score": 0.94}],
  "critical_files": [{"path": "pyproject.toml", "file_type": "manifest", "importance_score": 1.0}],
  "provenance": {}
}
```

### `get_directory_map`
```json
{
  "directories": [
    {
      "path": "src",
      "role": "application",
      "summary": "Likely contains the main server and tool handlers",
      "representative_files": ["src/server.py", "src/tools.py"],
      "importance_score": 0.94
    }
  ],
  "provenance": {}
}
```

### `get_critical_files`
```json
{
  "files": [
    {
      "path": "pyproject.toml",
      "file_type": "manifest",
      "importance_score": 1.0,
      "reason": "Project manifest"
    }
  ],
  "provenance": {}
}
```

### `get_recent_changes`
```json
{
  "commits": [
    {
      "commit_sha": "abc123",
      "subject": "feat: add refresh handler",
      "author_name": "Lakshya",
      "authored_at": "2026-03-21T15:00:00Z",
      "files": ["src/refresh.py", "tests/test_refresh.py"]
    }
  ],
  "provenance": {}
}
```

### `get_index_status`
```json
{
  "is_git_repo": true,
  "indexed_branch": "main",
  "indexed_head_sha": "abc123",
  "current_branch": "main",
  "current_head_sha": "def456",
  "stale": true,
  "refresh_recommended": true,
  "recommended_first_call": "refresh_index",
  "partial": false,
  "provenance": {}
}
```

### `get_edit_suggestions`
```json
{
  "task": "add retry logic for failed webhook delivery",
  "suggestions": [
    {
      "path": "src/webhooks/github.py",
      "file_type": "source",
      "score": 0.82,
      "confidence": "low",
      "reason": [
        "Path tokens matched: webhook, github",
        "Directory token matched: webhooks",
        "High file importance score"
      ]
    }
  ],
  "provenance": {}
}
```

### `refresh_index`
```json
{
  "status": "ok",
  "refreshed": true,
  "files_indexed": 412,
  "directories_indexed": 37,
  "partial": false,
  "provenance": {}
}
```

## 12. Component Boundaries

### A. MCP server layer
Responsibilities:
- expose tool handlers
- validate request inputs
- attach provenance to responses
- run staleness check before servicing a tool

### B. Repository inspector
Responsibilities:
- detect repo root
- detect Git status, current branch, and HEAD
- enumerate files and directories
- enforce skip list

### C. Index builder
Responsibilities:
- classify files and directories
- compute importance scores
- gather recent commit data
- write a full refreshed snapshot into SQLite

### D. Query service
Responsibilities:
- read structured data from SQLite
- serve tool-specific result shapes
- compute edit suggestion ranking from indexed fields

### E. Refresh coordinator
Responsibilities:
- orchestrate full refresh
- perform atomic write flow
- record index run status

## 12.5 Agent Usage Guidance

Repomind should be described to MCP clients as a query engine for grounded repo context, not as a natural-language answer bot.

Tool descriptions should guide agent behavior:
- call `get_index_status` first when starting work on a repository
- if stale, call `refresh_index` before trusting other results
- if current, call `get_repo_overview` next
- use `get_edit_suggestions` to narrow likely files before reading raw source

The `get_index_status` response includes `recommended_first_call` so agents can follow the next action without guessing.

## 13. Staleness Check Placement

The staleness check must run in MCP server middleware before every tool response except `refresh_index` itself.

Flow:
1. detect repo root
2. load index metadata
3. get current branch and HEAD
4. compare to indexed branch and SHA
5. set `stale` and provenance fields
6. continue to tool handler

## 14. Refresh Flow

### Explicit refresh sequence
1. `refresh_index` request arrives
2. resolve repo root
3. detect current branch and HEAD
4. create `index_runs` row with `status = running`
5. walk repo using skip rules
6. classify directories and files
7. gather recent commits and changed files
8. write results into a temporary SQLite file
9. validate temp DB integrity
10. atomically replace the live DB with temp DB
11. mark `index_runs` row complete
12. return refresh result with provenance

### Atomic write rule
Use:
- temp file in `~/.repomind/tmp/`
- build complete DB there
- rename into final location only after success

Do not partially update the live DB in place during refresh.

## 15. Performance Rules

- first index build must complete in under 30 seconds for repositories up to 10,000 files
- repositories over 50,000 files must produce a partial index capped at depth 3
- when partial indexing occurs, all tool responses must include `partial: true`
- branch and HEAD checks on each query must remain lightweight

## 16. Failure and Degradation Model

### Non-Git repository
Repomind should still:
- build a local file/directory index
- return overview, directory map, critical files, and edit suggestions

Repomind should not pretend to have:
- branch metadata
- commit history
- HEAD-based freshness

### Missing or stale index
- tools should return a clear error or empty-state response instructing the caller to run `refresh_index`
- stale index responses must not hide stale status

### Partial index
- partial indexes remain queryable
- responses must include `partial: true`
- large-repo depth caps must be visible in status or provenance metadata

## 17. Implementation Notes

Recommended Python package layout:

```text
repomind/
  mcp_server.py
  repo.py
  indexer.py
  scoring.py
  db.py
  queries.py
  refresh.py
  models.py
```

## 18. Out of Scope for v1

- working-tree awareness
- simultaneous multi-branch live indexes
- embeddings or vector retrieval
- AST or call graph analysis
- natural-language answer generation inside Repomind
- background file watching
- git hooks

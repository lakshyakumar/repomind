# Product Requirements Document: Repomind

## 1. Overview

Repomind is a local MCP server and repo query engine for coding agents.

It indexes the currently checked-out state of a Git repository, records branch and commit metadata at index time, and serves structured, grounded repo queries on demand. Its job is not to replace source code reading. Its job is to make source code reading faster, more targeted, and more reliable.

Repomind reflects committed repository state at the time of the last successful index refresh. In-flight working tree edits remain in the coding agent’s own context in v1.

Repomind makes no LLM calls at query time.

## 2. Problem Statement

Coding agents repeatedly pay a context tax when working on the same repository.

Before they can make a useful change, they often need to:
- inspect the directory tree
- find manifests, configs, and entrypoints
- infer architecture from scattered files
- retrace workflows from filenames and structure
- guess where a task should begin
- re-check recent commits to understand what moved

This causes:
1. higher repeated token usage
2. slower time to first useful action
3. inconsistent understanding across sessions
4. too many wrong-file detours before the first correct edit
5. incomplete changes because adjacent files, tests, or configs are missed

This pain becomes worse in medium and large repositories, monorepos, and repeated agent workflows on the same codebase.

## 3. Product Thesis

Coding agents do not need perfect semantic understanding before they can begin useful work.

They need a grounded, refreshable repo index that helps answer:
- what matters in this repository?
- what does this directory or subsystem likely do?
- what changed recently on the current branch?
- which files are likely to matter for a task?
- is the indexed snapshot still current?

Repomind succeeds if it reliably reduces wandering before the first correct edit.

## 4. Goals

### Primary goals
- reduce time to first useful context for coding agents
- reduce the number of irrelevant file reads before the first correct edit
- improve consistency of repo understanding across repeated sessions
- provide structured, grounded repo data through MCP
- surface recent committed changes that affect current work

### Secondary goals
- reduce repeated token spend
- improve navigation in medium and large repositories
- provide a path to richer analyzers in later iterations

## 5. Non-goals

Repomind v1 does not:
- replace direct source code inspection
- make autonomous code edits
- model in-flight uncommitted working tree changes
- provide natural-language question answering inside Repomind itself
- require a hosted backend
- require embeddings or vector retrieval
- require language-server integration
- maintain simultaneous live indexes for multiple branches

## 6. Target Users

### Primary users
- developers using coding agents repeatedly on the same Git repository
- teams building internal AI coding workflows
- agent platform builders who want reusable, structured repo context

### Beachhead user
A developer using Claude Code, Cursor, Codex, or similar tools on a real repository who is tired of the agent rediscovering the same codebase every session.

## 7. Core Use Cases

Repomind should help a coding agent:
- get a high-signal overview of the current repository state
- understand important directories and files
- see recent committed changes on the current branch
- identify likely starting points for a task
- determine whether the current index is stale
- refresh the local index when the repository state has changed

## 8. Product Principles

- grounded over clever
- structured outputs over vague prose
- local-first and inspectable by default
- deterministic query behavior over hidden model calls
- freshness must be visible
- heuristics first, heavier semantics later

## 9. Core Product Requirements

### 9.1 Repository indexing
Repomind must:
- detect repository root
- detect the current checked-out branch and HEAD commit
- traverse the project while skipping noisy and generated directories
- identify important files and directories
- build and store a structured local index
- record branch name, commit SHA, and index timestamp

### 9.2 Query engine
Repomind must expose structured MCP queries that return grounded repo data on demand.

The system is a repo query engine, not a one-shot startup summary generator.

### 9.3 Grounded outputs
Repomind outputs must:
- derive from actual repository contents and Git metadata when available
- include enough source provenance to be inspectable
- remain conservative when confidence is low
- distinguish indexed repo state from live in-flight edits

### 9.4 Staleness and refresh
On each query, Repomind must check the current branch and HEAD commit.

If the current snapshot differs from the indexed snapshot, Repomind must mark the index stale, return the stale status in the response, and allow explicit refresh via `refresh_index`. Auto-refresh is out of v1 scope.

### 9.5 Local and free operation
Repomind must run locally, require no hosted backend, and make no LLM calls at query time.

## 10. Functional Requirements

### FR1. Repository overview
Repomind must return:
- repository name
- root path
- current branch at index time
- indexed commit SHA
- high-level stack hints
- top directories
- critical files
- freshness metadata

### FR2. Directory map
Repomind must return a ranked or filtered list of important directories with likely role descriptions and representative files.

### FR3. Critical files
Repomind must rank and return high-signal files such as:
- manifests
- config files
- root documentation
- entrypoints
- major source files
- key tests

### FR4. Recent changes
Repomind must surface recent committed changes for the current repository state where Git metadata is available.

### FR5. Edit suggestions
Repomind must accept a task description and return likely files or directories to inspect first.

In v1 this must be heuristic and grounded. It must not rely on embeddings or query-time LLM reasoning.

At minimum, v1 heuristics must score candidates using tokenized file path match, directory name match, file type classification, and extracted header comment tokens where available. The score should combine relevance and file importance. The tool should return the top ranked results with a reason field for each result. Confidence should be conservative in v1.

### FR6. Index status
Repomind must return:
- indexed branch name
- indexed commit SHA
- current branch name
- current HEAD commit SHA when available
- whether the index is stale
- whether refresh is recommended

### FR7. Refresh index
Repomind must allow the local index to be refreshed for the current checked-out repository state.

## 11. MCP Tool Surface

Repomind v1 must expose the following MCP tools:
- `get_repo_overview`
- `get_directory_map`
- `get_critical_files`
- `get_recent_changes`
- `get_index_status`
- `get_edit_suggestions`
- `refresh_index`

## 12. Non-Functional Requirements

### Performance
- first index build must complete in under 30 seconds for repositories up to 10,000 files. Repositories over 50,000 files must receive a partial index capped at depth 3, with a `partial: true` flag in the response
- repeated queries should be much faster than full rescans
- checking branch and HEAD on each query should remain lightweight

### Reliability
- must fail safely when Git metadata is unavailable
- must degrade gracefully in non-Git directories with reduced functionality
- must avoid silent stale responses pretending to be current

### Trust
- outputs must be inspectable and grounded in source content
- each response should carry freshness and provenance metadata
- summaries and suggestions should be conservative rather than flashy

### Portability
- must run locally through MCP
- must support Docker as a deployment path; native local install is the primary path
- must require no paid infrastructure in v1

## 13. MVP Scope

### In scope
- local MCP server
- Docker-supported deployment
- local repository walking and indexing
- branch and commit metadata capture
- directory summaries
- critical file ranking
- recent committed change summaries
- task-to-edit suggestions
- index staleness detection
- refreshable local cache/index

### Out of scope
- natural-language answer generation inside Repomind
- embeddings or vector retrieval
- AST call graphs
- language-server integration
- hosted indexing
- multi-user shared state
- working tree intelligence
- simultaneous multi-branch active indexing
- automatic file watching
- PR and issue overlays

## 14. Success Metrics

### Primary metrics
- reduction in number of files opened before the first correct edit
- reduction in time to first useful edit
- usefulness rating of edit suggestions and repo overview
- repeated-session speed improvement on the same repository

### Secondary metrics
- reduction in repeated token usage
- stale-index detection accuracy
- refresh usage rate
- cache hit rate

## 15. Risks

- edit suggestions may be too shallow if heuristics are weak
- stale indexes may reduce trust quickly
- weak repo conventions may reduce inference quality
- Docker-first setup may add adoption friction for some users
- the product may be mistaken for a static repo summary tool if positioning is weak

## 16. Open Questions

- how should non-Git directories degrade in the MCP responses?
- when should per-branch stored indexes become worth the added complexity?
- what later analyzers provide the biggest value after the heuristic MVP is proven?

## 17. Positioning

Repomind is not:
- a generic code search tool
- a hosted code intelligence platform
- a natural-language answer bot
- a replacement for reading source code

Repomind is:
- a locally deployable repo query engine for coding agents, with Docker support
- a local MCP server that serves structured, grounded repo queries on demand
- a reusable indexed context layer for repeated work on the same repository

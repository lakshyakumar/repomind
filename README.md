# Repomind

Repomind is a local MCP server and repo query engine for coding agents.

It indexes the currently checked-out state of a Git repository, records branch and commit metadata at index time, and serves structured, grounded repo queries on demand.

Repomind reflects committed repository state at the time of the last successful index refresh. In-flight working tree edits stay in the coding agent’s own context in v1.

Repomind makes no LLM calls at query time.

## What it does

Repomind helps a coding agent query a repository while it works instead of re-discovering the same codebase every session.

In v1 it is designed to:
- index the current checked-out repository state
- capture branch and commit metadata at index time
- return repository overview and directory map data
- rank critical files
- surface recent committed changes
- provide index freshness and staleness status
- suggest likely files or directories to inspect for a task
- refresh the local index on demand

## MCP tools

Repomind v1 exposes:
- `get_repo_overview`
- `get_directory_map`
- `get_critical_files`
- `get_recent_changes`
- `get_index_status`
- `get_edit_suggestions`
- `refresh_index`

## Product constraints

- local-first
- structured outputs, not natural-language generation inside Repomind
- no LLM calls at query time
- committed repository state only in v1
- explicit refresh via `refresh_index`
- Docker-supported deployment

## What Repomind is not

Repomind is not:
- a generic code search tool
- a hosted code intelligence platform
- a natural-language answer bot
- a replacement for reading source code
- a working-tree intelligence engine in v1

## Docs

- [PRD](./PRD.md)
- [Leanstack](./Leanstack.md)
- [Architecture](./ARCHITECTURE.md)

## Status

The repository is currently documentation-first. The next step is to turn the product definition into an implementation-ready architecture and then scaffold the MCP server.

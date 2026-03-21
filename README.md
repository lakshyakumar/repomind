# repomind

**Repository intelligence for coding agents.**

Repomind is an MCP server that helps coding agents understand a repository without re-reading the entire codebase every session.

Instead of making an agent repeatedly scan directories, grep for entrypoints, and reconstruct architecture from scratch, Repomind provides a structured, reusable understanding of the repo:

- directory purpose
- critical files
- module relationships
- function and request flow
- likely edit points
- branch-specific or change-specific context

The agent can still read source files when precision matters, but it does not need to spend tokens rebuilding the repo's mental model over and over again.

## Why this exists

Coding agents are surprisingly good at burning tokens on the same repo repeatedly.

In most real projects, the expensive part is not writing code. It is forcing the agent to:

- rediscover the architecture
- infer which folders matter
- trace the same function flows again
- decide where a change probably belongs
- reload context after every new session

Repomind turns that repeated exploration into reusable infrastructure.

## Core idea

Repomind builds and serves a compressed understanding of a repository through MCP tools.

Instead of asking the agent to read 40 files to answer a simple question like:

> Where does auth start, and which modules does it touch?

The agent should be able to ask Repomind for:

- an architecture overview
- the relevant directories
- the call path
- the critical files to inspect next

That means lower latency, lower token usage, and more consistent edits.

## What Repomind should provide

### Repository overview
- high-level repo summary
- architecture summary
- major subsystems and boundaries
- important entrypoints

### Directory and module understanding
- directory purpose map
- module summaries
- public interfaces
- internal dependencies

### Flow understanding
- request flow summaries
- function call chains
- data movement across modules
- likely paths for debugging or changes

### Edit guidance
- likely files to modify for a task
- related files that may also need updates
- critical files that should be checked before edits

### Change-aware context
- what changed recently
- branch-specific deltas
- changed flows or impacted modules

## Example MCP capabilities

These are conceptual for now, not locked API names.

- `repo.get_overview`
- `repo.get_directory_map`
- `repo.get_critical_files`
- `repo.get_module_summary`
- `repo.get_function_flow`
- `repo.find_edit_points`
- `repo.get_recent_changes`
- `repo.get_branch_context`
- `repo.refresh_index`

## Who this is for

- developers using coding agents repeatedly on the same repo
- teams building internal AI coding workflows
- agent platforms that want faster repo understanding
- maintainers working in medium to large codebases where repeated context loading is expensive

## Why MCP

MCP is the right fit because it lets a repository expose structured tools instead of forcing every agent to rely on fragile shell inference, prompt stuffing, or repeated codebase scans.

Repomind is not trying to replace source-of-truth code reading. It is trying to make code reading targeted.

## Current MVP

The first working version now includes:

- repo overview
- directory purpose map
- critical files index
- recent git changes
- likely edit-point suggestions for a task
- cached local index refresh

## Installation

```bash
npm install
npm run build
```

## Run the MCP server

```bash
npm run dev
```

or with compiled output:

```bash
npm run build
npm start
```

## Available tools

- `repo.get_overview`
- `repo.get_directory_map`
- `repo.get_critical_files`
- `repo.get_recent_changes`
- `repo.find_edit_points`
- `repo.refresh_index`

## How it works

Repomind walks the repository, skips noisy folders like `.git` and `node_modules`, extracts lightweight summaries from readable files, scores important files, captures recent git history, and caches the result in `.repomind/index.json`.

That gives coding agents a reusable structural map before they start opening source files one by one.

## Design principles

- **Token efficiency matters.** If the agent keeps relearning the same repo, the system is wasting money.
- **Structure beats grep.** Raw search is useful, but not enough.
- **The repo is the source of truth.** Repomind should summarize and index it, not invent alternate reality.
- **Incremental refresh beats full rescans.** Rebuild only what changed.
- **Humans should be able to trust the output.** Summaries should remain inspectable and grounded.

## Status

Early concept. Docs first, implementation next.

## Roadmap

- [ ] Finalize MCP tool surface
- [ ] Define repo index format
- [ ] Build a local parser and summarization pipeline
- [ ] Support incremental refresh after file changes
- [ ] Add branch-aware and diff-aware context
- [ ] Add confidence and provenance metadata to outputs

## Leanstack

See [leanstack.md](./leanstack.md) for the product framing and problem analysis.

## Contributing

Not formal yet. For now, open an issue with:

- the repo shape you want indexed
- the agent workflow you care about
- where current agents waste the most tokens

That is where the real signal lives.

# Leanstack: Repomind

## 1. Problem

Coding agents repeatedly re-discover the same repository structure, important files, and recent committed changes every time they start work.

Before they can make a useful change, they often need to:
- inspect the directory tree
- find manifests, configs, and entrypoints
- infer architecture from scattered files
- re-check recent commits to understand what changed
- guess which files matter for the task

This creates a context tax:
- repeated token usage
- slower time to first useful edit
- inconsistent repo understanding across sessions
- too many wrong-file detours before the first correct edit

## 2. Customer Segments

### Early adopters
- developers using Claude Code, Cursor, Codex, or similar coding agents repeatedly on the same Git repository
- teams building internal AI coding workflows
- agent platform builders who want reusable structured repo context
- maintainers working in medium and large repositories where repeated context loading is expensive

### Beachhead user
A developer using a coding agent on a real Git repository who is tired of the agent rediscovering the same codebase every session.

## 3. Existing Alternatives

### A. Let the coding agent inspect the repo every time
**Examples:** Claude Code, Cursor, Cline, Aider-style workflows without persistent repo indexing.

**Why people use it:**
- zero setup
- works today
- no extra tooling

**Limitations:**
- repeated token burn
- repeated latency
- inconsistent understanding depending on what the agent inspects first
- weak reuse across sessions

### B. Hand-written repo docs and architecture notes
**Examples:** `README.md`, onboarding docs, `docs/architecture.md`, internal wiki pages.

**Why people use it:**
- cheap to start
- human-readable
- useful for onboarding

**Limitations:**
- drifts quickly
- usually incomplete
- not branch-specific
- not exposed as structured MCP queries

### C. Code search and grep-based navigation
**Examples:** ripgrep, GitHub code search, Sourcegraph, IDE search.

**Why people use it:**
- powerful and flexible
- good for exact strings and symbols
- already part of normal workflows

**Limitations:**
- returns raw matches, not reusable repo context
- still forces the agent to synthesize structure manually
- does not track freshness against repo state by itself

### D. IDE or language-server indexing
**Examples:** TypeScript language server, IntelliJ indexing, VS Code workspace intelligence.

**Why people use it:**
- strong symbol navigation
- semantic awareness
- already present in many editors

**Limitations:**
- not packaged as portable MCP repo queries
- often editor-specific
- does not become reusable context for external coding agents automatically

### E. Embedding or vector retrieval over code
**Examples:** codebase RAG systems, embedding-backed repo search tools.

**Why people use it:**
- semantic retrieval can be useful in large repos
- query experience feels flexible

**Limitations:**
- adds operational complexity
- can become opaque and stale
- overkill for a disciplined local MVP
- not required for the first version of Repomind

## 4. Unique Value Proposition

**Repomind gives coding agents a structured, queryable index of the current checked-out repository state so they can stop re-learning the codebase every session.**

### One-liner
**A local repo query engine for coding agents.**

## 5. Solution

Repomind is a local MCP server that indexes the current checked-out state of a Git repository and serves structured, grounded repo queries on demand.

It records branch and commit metadata at index time, detects when the index has gone stale because HEAD changed, and exposes MCP tools for things like:
- repository overview
- directory map
- critical files
- recent committed changes
- index status
- edit suggestions for a task
- explicit refresh

Repomind reflects committed repository state at last refresh. In-flight working tree edits stay in the coding agent’s own context in v1.

Repomind makes no LLM calls at query time.

## 6. Key Benefits

- lower repeated token spend
- faster startup for repeated tasks on the same repo
- more consistent repo understanding across sessions
- grounded visibility into recent committed changes
- structured MCP queries instead of repeated repo rediscovery

## 7. Unfair Advantage

Most tools expose raw code, raw search, or editor-local indexing.

Repomind aims to combine:
- local indexing of repo structure
- branch and commit-aware freshness metadata
- structured MCP queries
- deterministic, inspectable outputs
- no hosted dependency and no query-time model cost

The advantage is not magic semantics. The advantage is a reusable local repo index that coding agents can query while they work.

## 8. Channels

- GitHub
- MCP ecosystem directories
- Claude Code, Cursor, and coding-agent communities
- X, Reddit, Hacker News, and Discord devtool communities
- demos showing repeated-session speedup and fewer wrong-file detours

## 9. Revenue Streams

### Open source core
- local MCP server
- local repo indexing
- structured repo query tools
- Docker-supported deployment

### Possible paid layer later
- hosted team indexes
- shared organization-level repo context
- PR and issue overlays
- analytics and usage insights
- enterprise controls and audit trails

Not needed for v1. First prove the workflow pain.

## 10. Cost Structure

### Build costs
- repo walker and local index pipeline
- Git metadata extraction
- MCP tool surface and contracts
- storage schema and refresh logic
- testing across repo sizes and languages

### Ongoing costs
- keeping outputs grounded and trustworthy
- handling large repositories and monorepos
- maintenance of heuristics for edit suggestions
- compatibility across MCP clients and local environments

## 11. Key Metrics

- average reduction in files opened before first correct edit
- average reduction in time to first useful edit
- repeated-session speed improvement on the same repository
- usefulness rating of repo overview and edit suggestions
- stale-index detection accuracy

## 12. Early Adopter Signal

Strong signal sounds like:
- "My agent stops re-reading the same repo every time."
- "I can ask for repo context instead of rebuilding it with grep."
- "It tells me when the index is stale instead of lying about current state."
- "It gets me to the right files faster."

## 13. High-Level MVP

### Must-have
- local MCP server
- current-repo indexing
- branch and commit metadata capture
- repository overview
- directory map
- critical files
- recent committed changes
- index status / staleness detection
- heuristic edit suggestions
- explicit refresh via MCP

### Later
- stored per-branch indexes
- embeddings or vector retrieval
- AST-aware symbol graph
- framework detection
- working tree intelligence
- branch overlays and diff intelligence
- confidence scoring beyond heuristic low-confidence defaults

## 14. Riskiest Assumptions

1. Developers will configure and actually use a repo query MCP server during coding workflows.
2. Structured repo queries are more useful than repeated raw repo exploration for common agent tasks.
3. Heuristic edit suggestions are useful enough without embeddings in v1.
4. Stale detection plus explicit refresh is enough for trust in the first version.
5. Docker-supported local deployment remains simple enough for early adopters.

## 15. Experiments

### Experiment 1
Compare two workflows on the same repo:
- normal agent search and file reads only
- agent uses Repomind queries before reading code

Measure:
- files opened before first useful progress
- time to first correct edit
- token usage

### Experiment 2
Run repeated sessions on the same repo and measure the speedup from an existing local index.

### Experiment 3
Test on three repo shapes:
- small service
- medium app repo
- monorepo

Measure where index quality, performance, and edit suggestions break down.

## 16. Why Now

- coding agents are moving from novelty to repeated real repo work
- MCP provides a portable interface for local external tooling
- teams are noticing context cost, not just model quality
- local-first dev tools are more credible when they avoid hosted dependencies and query-time model fees

## 17. Positioning

Repomind should be positioned as:

**a local repo query engine for coding agents**

Not:
- a generic code search tool
- a hosted code intelligence platform
- a natural-language answer bot
- a replacement for reading source code

The hook is faster repeated work on the same repository.
The actual value is structured, grounded repo context that agents can query on demand.

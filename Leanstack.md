# Leanstack: Repomind

## 1. Problem

Coding agents repeatedly spend tokens and time re-understanding the same repository.

Before they can make a useful change, they often need to:
- inspect the directory tree
- search for entrypoints
- read config files and manifests
- infer architecture from scattered modules
- retrace common flows
- guess where a task should be implemented

This creates a persistent context tax:
- **higher token usage**
- **slower task startup**
- **inconsistent understanding across sessions**
- **more wandering before the first correct edit**

## 2. Customer Segments

### Early adopters
- developers using coding agents repeatedly on the same repo
- teams building internal AI coding workflows
- agent platform builders who want reusable codebase context
- maintainers working in medium or large repos where repeated context loading is expensive

### Beachhead user
A developer using Claude Code, Cursor, or similar agents on a real production repo who is tired of watching the agent rediscover the same architecture every time.

## 3. Existing Alternatives

This section should be grounded in real alternatives, not startup fog.

### A. Let the coding agent inspect the repo every time
**Examples:** Claude Code, Cursor, Cline, Aider-style workflows without a persistent repo intelligence layer.

**How it works:**
The agent uses search, file reads, grep, and shell commands each session to reconstruct context.

**Why people use it:**
- zero setup
- works today
- no extra infrastructure

**Limitations:**
- repeated token burn
- repeated latency
- architecture gets re-inferred every session
- quality depends on what the agent decides to inspect first

### B. Hand-written repo docs and architecture notes
**Examples:** `README.md`, `docs/architecture.md`, onboarding docs, internal wiki pages.

**How it works:**
Humans document the codebase and agents rely on those docs as shortcuts.

**Why people use it:**
- cheap to start
- human-readable
- helpful for onboarding

**Limitations:**
- docs drift fast
- usually incomplete
- weak for task-specific edit guidance
- not exposed as structured MCP tools

### C. Code search and grep-based navigation
**Examples:** ripgrep, GitHub code search, Sourcegraph, IDE search.

**How it works:**
Agents or developers query raw code text to find likely files, symbols, and references.

**Why people use it:**
- powerful and flexible
- great for exact strings and symbols
- already part of normal workflows

**Limitations:**
- returns raw matches, not repo understanding
- still requires the agent to synthesize architecture manually
- not a reusable memory layer by itself

### D. Vector search / embedding retrieval over code
**Examples:** codebase RAG pipelines, embedding-backed retrieval systems, custom repo indexing stacks.

**How it works:**
The system embeds code chunks and retrieves similar snippets for a query.

**Why people use it:**
- helps semantic retrieval
- useful for large repos
- can work across sessions

**Limitations:**
- retrieves snippets, not always structural understanding
- weak at directory-purpose or workflow mapping unless additional layers exist
- can become stale and opaque

### E. IDE or language-server indexing
**Examples:** TypeScript language server, IntelliJ indexing, VS Code workspace intelligence.

**How it works:**
The IDE understands symbols, references, imports, and diagnostics.

**Why people use it:**
- deep semantic power
- strong symbol navigation
- already available in many editor workflows

**Limitations:**
- not cleanly packaged as portable MCP repo intelligence
- often client-specific
- does not automatically become reusable context for external agents

## 4. Unique Value Proposition

**Repomind gives coding agents a reusable understanding of a repository so they can spend tokens solving problems instead of re-learning the codebase.**

### One-liner
**Repository intelligence for coding agents.**

## 5. Solution

Repomind is an MCP server that exposes a structured, reusable model of the repo.

Instead of making the agent infer everything from raw file access every session, Repomind provides:
- repository overview
- directory purpose map
- critical files index
- recent change summaries
- likely edit points for a task
- later, branch-aware and diff-aware overlays

The agent still reads raw files when precision matters, but only after it has a map.

## 6. Key Benefits

- lower token spend
- faster startup for repeated tasks
- more consistent repo understanding across sessions
- better navigation in medium and large repos
- fewer wrong-file detours before implementation starts

## 7. Unfair Advantage

Most tools expose code. Very few expose a maintained understanding of the codebase.

Repomind can build leverage by combining:
- repository structure indexing
- grounded summaries
- critical-file ranking
- change-aware context
- later, language-aware semantic analysis

The moat is not raw parsing.
The moat is useful, refreshable repository understanding exposed through a standard MCP interface.

## 8. Channels

- GitHub
- MCP ecosystem directories
- Claude Code, Cursor, and agent-builder communities
- X, Reddit, Hacker News, Discord devtool communities
- demos comparing repeated-session cost with and without Repomind

## 9. Revenue Streams

### Open source core
- local MCP server
- local repo indexing
- local cached repo understanding

### Possible paid layer later
- shared team indexes
- hosted indexing
- PR and issue overlays
- dashboards and analytics
- enterprise controls and audit trails

Not needed now. First prove the workflow pain.

## 10. Cost Structure

### Build costs
- repository walker and index pipeline
- summary extraction and ranking logic
- MCP tool surface
- cache format and refresh logic
- testing across repo shapes and languages

### Ongoing costs
- keeping outputs grounded and trusted
- language and framework support
- scale issues for large repos and monorepos
- compatibility across MCP clients

## 11. Key Metrics

- average tokens saved per repeated task
- average time-to-useful-context
- number of file reads avoided before first correct edit
- usefulness rating for overview and edit-point tools
- repeated-session speed improvement on the same repo

## 12. Early Adopter Signal

Strong signal sounds like:
- "My agent stops re-reading the same repo every time."
- "I can point an agent at a big codebase without paying the full context tax."
- "It knows where to start before it starts poking random files."

## 13. High-Level MVP

### Must-have
- repo overview
- directory purpose map
- critical files index
- recent changes
- likely edit points
- refreshable local cache

### Later
- AST-aware symbol graph
- framework detection
- branch and diff overlays
- confidence and provenance metadata
- incremental invalidation

## 14. Riskiest Assumptions

1. Developers will trust a summarized repo layer enough to use it as first-pass context.
2. The summaries can stay fresh enough to remain useful.
3. The token and latency savings are meaningful enough to change behavior.
4. Structured repo understanding is more useful than plain search for common coding tasks.
5. MCP is the right portability layer for this product category.

## 15. Experiments

### Experiment 1
Compare two workflows on the same repo:
- normal agent search and file reads only
- agent uses Repomind before reading code

Measure:
- token usage
- time to first correct edit
- files opened before useful progress

### Experiment 2
Run repeated sessions on the same repo and track speedup from cached context.

### Experiment 3
Test across three repo types:
- small service
- medium app repo
- monorepo

Find where the MVP breaks instead of pretending one heuristic fits all.

## 16. Why Now

- coding agents are moving from novelty to repeated real repo work
- MCP gives a standard tool interface for external intelligence layers
- teams are starting to notice context cost, not just model quality
- large context windows still waste money if the agent keeps relearning stable architecture

## 17. Positioning

Repomind should be positioned as:

**repository intelligence infrastructure for coding agents**

Token savings is the hook.
The actual value is faster, cheaper, more reliable codebase understanding.

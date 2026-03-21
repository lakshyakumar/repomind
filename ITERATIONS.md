# Iterations: Repomind

This document outlines the two most likely iterations after the v1 repo query engine MVP.

The goal is to extend Repomind without breaking the constraints that make v1 useful:
- local-first
- no LLM calls at query time
- grounded, structured outputs
- committed repository state as the trust boundary

---

## Iteration 2: Better retrieval and larger-repo usability

### Goal
Make Repomind materially better on medium and large repositories without turning it into a hosted platform or a semantic science project.

### Why this iteration exists
If v1 works, the first real pressure will come from:
- larger repos with weaker naming conventions
- users wanting better task routing than simple path/token overlap
- repos where shallow heuristics are useful but not strong enough
- repeated use across a few long-lived branches

### In scope
- SQLite FTS5 or equivalent local full-text indexing for better path/comment/text matching
- better edit suggestion scoring using indexed text and richer file metadata
- optional per-branch stored indexes for a small number of active branches
- improved directory purpose inference
- configurable large-repo caps and partial-index reporting
- stronger index status diagnostics
- better non-Git degraded-mode behavior

### Out of scope
- embeddings as a required dependency
- query-time LLM answering
- background daemon or file-watcher architecture
- hosted sync or multi-user shared state
- live working-tree intelligence

### Technical additions
- add FTS-backed search tables or equivalent local text-search layer
- support cached index metadata per branch when explicitly refreshed
- improve scoring inputs with richer extracted tokens and maybe import/reference counts by language where cheap
- add more explicit machine-readable reasons in `get_edit_suggestions`
- improve large-repo indexing strategy beyond blunt depth caps

### Risks
- scope drift from “better local retrieval” into “build a search engine”
- per-branch index storage complexity growing faster than real user value
- FTS quality still not solving weakly named repos
- index build times increasing faster than query quality improves

### Exit criteria
- edit suggestions measurably outperform v1 on medium/large repos
- large-repo partial indexing is understandable and predictable
- branch-scoped indexing is useful without becoming operationally annoying
- per-branch index routing is only added if real v1 usage shows repeated branch-switching pain; it is not added proactively
- retrieval quality improves without adding hosted dependencies or query-time model calls

---

## Iteration 3: Language-aware repo intelligence

### Goal
Make Repomind more accurate on real engineering tasks by adding selective language-aware analysis where it buys obvious value.

### Why this iteration exists
Once v1 and iteration 2 are proven, the next ceiling is heuristic ambiguity.

At that point, users will want:
- better understanding of entrypoints and boundaries
- better task routing in weakly named codebases
- better hints about adjacent files and likely blast radius
- more precise suggestions in structured languages and common frameworks

### In scope
- language-aware analyzers for a small set of high-value ecosystems
- lightweight symbol extraction where cheap and deterministic
- framework detectors for common stacks
- better related-file and blast-radius hints
- richer provenance about why a file was suggested
- optional issue/PR overlays only as explicit remote-dependent integrations in later iterations

### Out of scope
- full AST call-graph perfection across all languages
- autonomous code editing inside Repomind
- replacing language servers
- hosted enterprise indexing platform behavior
- agent memory of uncommitted worktree state

### Technical additions
- pluggable analyzer interface by language/framework
- extracted symbol metadata stored in SQLite alongside file metadata
- richer relationship tables for files, directories, symbols, or framework boundaries
- more precise edit suggestion scoring using language-aware signals
- stronger related-file queries for tests, schemas, configs, and entrypoints

### Risks
- analyzer proliferation turning the project into a maintenance swamp
- inconsistent support across languages leading to confusing behavior
- “intelligence” claims outrunning actual analyzer quality
- schema churn if analyzers are added without a stable plugin contract

### Exit criteria
- at least one or two language analyzers provide clear improvement over heuristic-only routing
- related-file and blast-radius hints become materially more useful
- architecture remains local-first and inspectable
- analyzers are modular instead of hard-wired into the whole indexing pipeline

---

## What stays true across iterations

Even in later iterations, Repomind should preserve these constraints unless intentionally redefined:
- local MCP server model
- explicit freshness and provenance in responses
- deterministic core query path
- committed repository state as the baseline source of truth
- no merge of “repo query engine” and “agent memory” into one muddy abstraction

# Iteration 2: Retrieval Quality and Large-Repo Usability

Iteration 2 starts from a completed v1 on `main` and `dev`: local indexing, structured repo queries, MCP wiring, and end-to-end validation already exist.

The goal now is not to add more surface area. The goal is to make Repomind more useful on real repositories.

## Goal

Make Repomind materially better at:
- returning useful edit suggestions on real codebases
- handling medium and large repositories more gracefully
- giving agents clearer trust signals about index quality and freshness

Iteration 2 is a retrieval-quality and usability iteration. It is not a platform expansion iteration.

## Why this iteration exists

v1 works, but it has visible limits:
- `get_edit_suggestions` is brittle because it depends heavily on exact token matches
- large-repo behavior is safe but blunt
- `partial=true` exists, but the explanation is still thin
- `get_index_status` is useful but not rich enough to help an agent calibrate trust cleanly

This iteration should improve the product where users will actually feel it.

## In Scope

### 1. Better retrieval for `get_edit_suggestions`
Improve candidate retrieval so it handles more real task phrasing and is less fragile than exact token-overlap only.

### 2. Richer cheap signals for ranking
Add import-line token extraction where it is cheap and deterministic, so ranking can use more than path and header tokens.
Python is the first-class target. JS/TS is in scope only if the Python implementation is clean and the regex pattern is directly reusable. Otherwise JS/TS moves to Iteration 3.

### 3. Better large-repo ergonomics
Add configurable index limits and more explicit partial-index reporting.

### 4. Better trust/status signals
Improve `get_index_status` so agents can more easily tell whether an index is fresh, partial, or degraded.

### 5. Test and documentation updates
Cover iteration-2 changes with end-to-end tests and update the architecture/docs accordingly.

## Out of Scope

Iteration 2 must not include:
- embeddings or vector search
- query-time LLM calls
- hosted sync or remote backend features
- working-tree or uncommitted-change intelligence
- per-branch stored indexes unless real usage proves the pain first
- AST/call-graph analysis
- language-server integration
- issue/PR overlays
- directory semantic summaries beyond cheap grounded heuristics
- superproject detection and parent-Git metadata enrichment

## Technical Priorities

1. SQLite FTS5-backed retrieval for `get_edit_suggestions` (design decision required before implementation — see I2-T1)
2. Import-line token extraction (Python; JS/TS conditional on clean reuse — see I2-T2)
3. Ranking formula update incorporating import tokens (I2-T4a), then reason/empty_reason improvements (I2-T4b) — separate PRs
4. Configurable file/depth caps and structured partial-index reporting
5. Richer `get_index_status` trust signals
6. End-to-end coverage for all new behavior

## Product Risks

- FTS improves recall, but may still disappoint if users expect semantic understanding.
- Import tokens can add noise from third-party package names if filtering is weak.
- Better partial-index reporting can become more confusing instead of more helpful if it becomes too verbose.
- Iteration 2 can quietly turn into “let’s build a search engine” unless scope is kept tight.

## Exit Criteria

Iteration 2 is successful when:
- `get_edit_suggestions` performs visibly better than v1 on real medium-sized repos for at least a few realistic task prompts
- partial-index behavior is configurable and understandable from the response itself
- `get_index_status` gives enough signal for agents to decide whether to trust or refresh the index
- no runtime external dependency is introduced
- the new behavior is covered by tests and reflected in docs

## Non-goal reminder

Iteration 2 should still preserve the v1 identity:
- local
- deterministic
- inspectable
- grounded in committed repo state
- cheap to run

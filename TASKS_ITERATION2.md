# Tasks: Iteration 2

This file breaks Iteration 2 into small, reviewable tasks.

The goal is to improve retrieval quality and large-repo usability without reopening v1 architecture.

---

## Workflow Rules

- One task at a time.
- One PR per task into `dev` unless explicitly grouped.
- Merge only after review and green checks.
- Feature branches should be deleted after merge.
- `main` remains a promotion target, not the day-to-day integration branch.
- Prioritize throughput, but do not hide product-quality regressions behind green CI.

---

## I2-T1. Add FTS5 schema and refresh integration

**Why**
The current exact-token retrieval is too brittle for real task phrasing.

**Scope**
- add a standalone SQLite FTS5 virtual table for file retrieval, not a `content=` table
- populate it with a batch `INSERT ... SELECT` after the main file insert completes during refresh
- index these content columns:
  - raw `path`
  - raw `directory_path`
  - space-joined header tokens derived from `header_tokens_json`
- use the default `unicode61` tokenizer
- rebuild FTS data during every full refresh
- do not add incremental FTS sync logic

**Dependencies**
- existing v1 schema and refresh pipeline

**Acceptance criteria**
- FTS table exists and is populated after refresh
- `MATCH` queries retrieve indexed files by token/prefix-style search
- existing v1 behavior remains intact

**PR-sized**
- yes

---

## I2-T2. Add import-token extraction

**Why**
Many source files have weak or absent header comments, but import lines are cheap and informative.

**Scope**
- extract import-line tokens for Python files
- store import tokens in the files table
- define `_IMPORT_STOP_TOKENS: frozenset[str]` as a named constant before writing extraction logic
- `_IMPORT_STOP_TOKENS` must include obvious low-signal import noise such as `os`, `sys`, `re`, `json`, `typing`, `dataclasses`, `pathlib`, `collections`, `fs`, and `path`
- JS/TS import extraction is out of scope for the first pass of iteration 2 unless explicitly added later as a follow-up task

**Dependencies**
- existing extraction/index pipeline

**Acceptance criteria**
- import tokens are stored for Python files
- stop-token filtering is deterministic and tested
- indexing time does not regress badly

**PR-sized**
- yes

---

## I2-T3. Improve edit-suggestion candidate retrieval with FTS

**Why**
Candidate retrieval is the main weak point of v1.

**Scope**
- use FTS as the first-pass candidate retriever for `get_edit_suggestions`
- keep fallback behavior when FTS produces nothing
- do not introduce embeddings, stemming libraries, or semantic rerankers

**Dependencies**
- I2-T1

**Acceptance criteria**
- a test asserts that task string `webhook` surfaces at least one file with `webhooks` in its path via FTS, not fallback
- fallback behavior remains predictable
- response shape stays compatible with current clients

**PR-sized**
- yes

---

## I2-T4a. Improve edit-suggestion scoring

**Why**
Better retrieval alone is not enough if ranking is weak or import signals are ignored.

**Scope**
- incorporate import-token signal into ranking
- refine the ranking formula to balance retrieval relevance and importance score
- explicitly decide whether inbound-ref behavior stays indirect through `importance_score` or becomes a direct ranking signal

**Dependencies**
- I2-T2
- I2-T3

**Acceptance criteria**
- results are ranked more sanely on realistic task prompts
- import-only match cases are covered by tests
- ranking changes are isolated from presentation-only changes

**PR-sized**
- yes

---

## I2-T4b. Improve edit-suggestion explanations

**Why**
Ranking improvements are hard to trust if `reason[]` is vague or empty-result cases are silent.

**Scope**
- improve `reason[]` so it explains which signals actually fired
- add `empty_reason` or equivalent for zero-result cases

**Dependencies**
- I2-T4a

**Acceptance criteria**
- `reason[]` is useful and non-redundant
- empty results are explicit, not silent

**PR-sized**
- yes

---

## I2-T5. Add configurable file/depth caps and structured partial reporting

**Why**
The current partial-index behavior is safe but blunt.

**Scope**
- add env-configurable file limit
- add env-configurable depth cap
- `REPOMIND_MAX_DEPTH` replaces `_PARTIAL_MAX_DEPTH` as the single depth cap
- both file-count and depth caps can set `partial=true` independently
- replace bare partial-reason strings with structured partial metadata
- surface structured partial info in provenance/status

**Dependencies**
- existing refresh/index flow

**Acceptance criteria**
- limits are configurable
- partial responses explain what cap fired
- tools remain callable on partial indexes

**PR-sized**
- yes

---

## I2-T6. Improve `get_index_status` trust signals

**Why**
Agents need a better calibration signal than stale/not-stale alone.

**Scope**
- add age since last index
- add indexed file count
- add `quality_signal` such as `full`, `partial`, `degraded`
- preserve existing response compatibility where possible

**Dependencies**
- I2-T5 recommended, but not mandatory

**Acceptance criteria**
- status response is more informative without becoming noisy
- values are correct and covered by tests

**PR-sized**
- yes

---

## I2-T7. Add iteration-2 end-to-end coverage

**Why**
The new retrieval path and trust signals need system-level testing, not just unit tests.

**Scope**
- add e2e tests for improved edit-suggestion retrieval
- test import-token usefulness
- test partial-index configuration and reporting
- test new index-status trust signals

**Dependencies**
- I2-T1 through I2-T6 as needed

**Acceptance criteria**
- FTS scenario: `webhook` in task matches a file with `webhooks` in its path via FTS, not fallback
- import-token scenario: Python file importing `repomind.queries` yields `queries` in import tokens and surfaces for task `queries`, while stop-tokens like `os` do not contribute
- partial scenario: low file limit on a repo over the threshold produces `partial=true` and structured `partial_reason`
- quality-signal scenario: fresh index -> `full`, partial index -> `partial`, missing index -> `degraded`
- no regressions in v1 behavior

**PR-sized**
- yes

---

## I2-T8. Update docs for iteration 2 behavior

**Why**
New retrieval behavior and configuration need to be visible to users and future maintainers.

**Scope**
- update ARCHITECTURE.md
- update README.md
- update Iteration 2 plan/task docs if implementation differs from the original plan

**Dependencies**
- final behavior of I2-T1 through I2-T7

**Acceptance criteria**
- docs match actual implementation
- new env vars and retrieval behavior are documented

**PR-sized**
- yes

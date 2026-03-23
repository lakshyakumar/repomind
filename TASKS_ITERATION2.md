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
- add SQLite FTS5 virtual table(s) for file retrieval
- index path text, directory path, and header text during refresh
- rebuild FTS data during every full refresh
- do not add incremental FTS sync logic

**Dependencies**
- existing v1 schema and refresh pipeline

**Acceptance criteria**
- FTS table exists and is populated after refresh
- FTS queries can retrieve indexed files by token/prefix-style search
- existing v1 behavior remains intact

**PR-sized**
- yes

---

## I2-T2. Add import-token extraction

**Why**
Many source files have weak or absent header comments, but import lines are cheap and informative.

**Scope**
- extract import-line tokens for Python files
- extract JS/TS import tokens if low-friction
- store import tokens in the files table
- filter obvious low-signal noise tokens conservatively

**Dependencies**
- existing extraction/index pipeline

**Acceptance criteria**
- import tokens are stored for supported languages
- extraction is deterministic and tested
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
- singular/plural-ish retrieval improves on realistic examples such as `webhook` vs `webhooks`
- fallback behavior remains predictable
- response shape stays compatible with current clients

**PR-sized**
- yes

---

## I2-T4. Improve edit-suggestion scoring and explanations

**Why**
Better retrieval alone is not enough if ranking and reasons are weak.

**Scope**
- incorporate import-token signal into ranking
- refine the ranking formula to balance retrieval relevance and importance score
- improve `reason[]` so it explains which signals actually fired
- add `empty_reason` or equivalent for zero-result cases

**Dependencies**
- I2-T2
- I2-T3

**Acceptance criteria**
- results are ranked more sanely on realistic task prompts
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
- iteration-2 behaviors are exercised through the full refresh/query path
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

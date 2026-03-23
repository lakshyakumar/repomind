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
- add a standalone FTS5 virtual table `files_fts` (not a `content=` table — standalone avoids
  delete-trigger complexity and is sufficient for rebuild-on-refresh use)
- content columns: `rowid` (joining key back to `files.id`), `path` (raw string),
  `directory_path` (raw string), `header_tokens` (space-joined from `header_tokens_json`)
- FTS tokenizer: default `unicode61` — do not configure a custom tokenizer in I2
- populated by a single batch `INSERT INTO files_fts SELECT ...` after the files bulk insert
  completes each refresh; the FTS table is dropped and recreated on every refresh (no
  incremental sync)
- do not change any existing query functions in this PR — FTS is only added to the schema
  and populated; it is wired into `get_edit_suggestions` in I2-T3

**Dependencies**
- existing v1 schema and refresh pipeline

**Acceptance criteria**
- `files_fts` table present and populated after `refresh_index` on a test repo
- `SELECT rowid FROM files_fts WHERE files_fts MATCH 'webhook'` returns rows for a repo
  that has files with "webhooks" in their path (confirms prefix/token matching works)
- `SELECT rowid FROM files_fts WHERE files_fts MATCH 'xyzzy'` returns no rows
- existing v1 test suite (464 tests) passes without modification
- FTS rebuild adds no more than 10% to index build time on a 500-file repo

**PR-sized**
- yes

---

## I2-T2. Add import-token extraction

**Why**
Many source files have weak or absent header comments, but import lines are cheap and informative.
A file with no docstring but `from repomind.queries import get_edit_suggestions` carries
the token "queries" which path-token extraction misses entirely.

**Scope**
- Python: regex-extract `from X.Y.Z import ...` and `import X.Y.Z` → tokenize module path segments
  using the same `_tokenize` function used elsewhere
- JS/TS: in scope only if the Python regex is clean and the extraction function can be structured
  as a simple per-language dispatch; otherwise defer JS/TS to Iteration 3
- store as `import_tokens_json TEXT NOT NULL DEFAULT '[]'` column added to the `files` table
- define `_IMPORT_STOP_TOKENS: frozenset[str]` as a named constant in `extractor.py` before
  writing extraction logic; this constant must be reviewed in the PR and must include at minimum:
  `os`, `sys`, `re`, `io`, `abc`, `typing`, `types`, `collections`, `functools`, `itertools`,
  `contextlib`, `dataclasses`, `pathlib`, `logging`, `warnings`, `string`, `enum`, `datetime`,
  `threading`, `asyncio`, `inspect`, `traceback`, `struct`, `hashlib`, `base64`, `uuid`,
  `http`, `urllib`, `socket`, `json`, `math`, `time`, `copy`, `random`, `subprocess`
- apply existing `_MIN_TOKEN_LEN` and general `_STOP_TOKENS` on top of `_IMPORT_STOP_TOKENS`
- do NOT attempt stdlib-vs-third-party distinction in I2

**Dependencies**
- existing extraction/index pipeline

**Acceptance criteria**
- a Python file containing `from repomind.queries import get_edit_suggestions` has `"queries"`
  and `"edit"` and `"suggestions"` in its import tokens (or subset thereof after filtering)
- `"os"`, `"sys"`, `"json"`, `"typing"` are absent from import tokens for any file
- `import_tokens_json` is populated (non-empty list) for all Python source files in test fixtures
  that have import statements
- `import_tokens_json` is `[]` for files with no extractable imports
- no performance regression > 10% on index build time on a 500-file repo

**PR-sized**
- yes

---

## I2-T3. Improve edit-suggestion candidate retrieval with FTS

**Why**
Candidate retrieval is the main weak point of v1. Exact token intersection misses real task
phrasing where the user writes "webhook" and the file path contains "webhooks".

**Scope**
- use `files_fts MATCH ?` as the primary candidate retrieval step in `get_edit_suggestions`;
  join back to `files` table for scoring columns
- FTS query: join task tokens with `OR` so any single match produces a candidate
- fallback: if FTS returns zero candidates, fall back to the existing full-table-scan +
  set-intersection path (which remains unchanged)
- add `retrieval_method: "fts" | "fallback"` field to `EditSuggestions` — present in the
  response for observability but not part of the public response contract
- do not change the scoring formula in this PR (that is I2-T4a)

**Dependencies**
- I2-T1

**Acceptance criteria**
- a test asserts: task string `"webhook"` surfaces at least one file with `"webhooks"` in
  its path, `retrieval_method == "fts"`, and no file with an unrelated path is returned
  that would not have been returned by the fallback path
- a test asserts: a task string with no matching tokens (e.g. `"xyzzy qwerty"`) triggers
  fallback (`retrieval_method == "fallback"`) and returns an empty suggestions list
- all 28 existing `test_get_edit_suggestions.py` tests pass without modification
- ranking order for exact-token-match tasks is not degraded compared to v1

**PR-sized**
- yes

---

## I2-T4a. Update edit-suggestion scoring formula to include import tokens

**Why**
With import tokens indexed, the scoring formula should use them. The current formula ignores
import signals entirely.

**Scope**
- add `import_overlap = |task_tokens ∩ import_tokens| / |task_tokens|` to per-file scoring
- updated formula:
  `relevance_score = 0.45 * path_overlap + 0.25 * dir_overlap + 0.15 * header_overlap + 0.15 * import_overlap`
  (weights sum to 1.0; formula constants must be named, not inline magic numbers)
- update existing tests that assert specific score values; do not assume scores are stable
  across formula changes
- add a test case: a file that only matches via import tokens (path and header tokens have no
  overlap with the task) should appear in results; a file with no import overlap and no other
  overlap should not

**Dependencies**
- I2-T2
- I2-T3

**Acceptance criteria**
- import-only match case: file surfaces when task tokens match only import tokens
- no-overlap case: file absent when task tokens match nothing (path, dir, header, import)
- formula weights defined as named constants
- full test suite passes

**PR-sized**
- yes

---

## I2-T4b. Improve `reason[]` entries and add `empty_reason`

**Why**
Current reason strings like "Path tokens matched: x, y" don't tell an agent which retrieval
layer drove the result or how strong the match was. Zero-result cases are silent.

**Scope**
- update `reason[]` entries to identify the layer: `"Path match (fts): webhook"`,
  `"Path match (exact): handler"`, `"Import match: queries"`, `"Directory token matched: X"`,
  `"Header tokens matched: X"`, `"High file importance score"` (threshold unchanged)
- add `empty_reason: "no_token_overlap" | "stop_words_only" | None` to `EditSuggestions`:
  - `"no_token_overlap"`: task had scoreable tokens but no file matched
  - `"stop_words_only"`: task reduced to empty token set after filtering
  - `None`: suggestions list is non-empty
- `empty_reason` is additive — existing fields unchanged

**Dependencies**
- I2-T4a

**Acceptance criteria**
- every suggestion in a non-empty result has at least one reason entry identifying its layer
- `empty_reason == "no_token_overlap"` for a task like `"xyzzy qwerty"`
- `empty_reason == "stop_words_only"` for a task like `"the a in to for"`
- `empty_reason is None` for any non-empty suggestions result
- existing tests updated for new reason string patterns

**PR-sized**
- yes

---

## I2-T5. Add configurable file/depth caps and structured partial reporting

**Why**
The current partial-index behavior is safe but blunt: a single hard-coded 50k-file threshold,
a fixed depth-3 cap, and a bare string `partial_reason`. Operators and agents cannot tune it
or understand what was skipped from the response alone.

**Scope**
- add `REPOMIND_FILE_LIMIT` env var (default: `50000`); replaces `_PARTIAL_FILE_THRESHOLD`
- add `REPOMIND_MAX_DEPTH` env var (default: `8`); this is an independent cap — files deeper
  than `REPOMIND_MAX_DEPTH` are excluded regardless of file count; replaces `_PARTIAL_MAX_DEPTH`
  as the single depth cap (the two caps are independent: either can trigger `partial=true`)
- depth cap applies after the skip list — skipped directories do not count toward depth
- change `partial_reason TEXT` column to store JSON:
  `{"cap_type": "file_count" | "depth", "cap_value": N}`
  — omit `files_excluded_estimate` unless it falls out naturally from the walker (do not add
  a second walk to compute it)
- surface structured `partial_reason` (parsed dict, not raw string) in all tool response
  provenances when `partial=true`

**Dependencies**
- existing refresh/index flow

**Acceptance criteria**
- `REPOMIND_FILE_LIMIT=3` triggers partial indexing on a 6-file repo; `partial=true`,
  `partial_reason.cap_type == "file_count"`, `partial_reason.cap_value == 3`
- `REPOMIND_MAX_DEPTH=0` excludes all files below depth 0 (root-level only); `partial=true`,
  `partial_reason.cap_type == "depth"`
- existing partial-index e2e tests updated to monkeypatch new constant names
- all query tools callable on partial index; provenance includes structured `partial_reason`

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
One test file per feature area (can be a single `test_e2e_i2.py` with clearly sectioned
scenarios, or separate files — implementer decides based on fixture reuse):

- **FTS retrieval**: fixture repo with a file at `webhooks/handler.py`; assert task `"webhook"`
  surfaces it via FTS (`retrieval_method == "fts"`); assert task `"xyzzy"` returns empty
  via fallback
- **Import tokens**: Python fixture file containing `from repomind.queries import get_index_status`;
  after refresh, assert `"queries"` is in its `import_tokens_json`; assert a task `"queries"`
  surfaces it; assert `"os"` and `"sys"` are absent from import tokens for any file
- **Configurable caps**: monkeypatch `REPOMIND_FILE_LIMIT` to a small number on a repo that
  exceeds it; assert `partial=true`, `partial_reason.cap_type == "file_count"`; repeat for
  `REPOMIND_MAX_DEPTH`; assert all query tools callable on the partial index
- **Quality signal**: fresh index → `quality_signal == "full"`; partial index →
  `quality_signal == "partial"`; missing index → `quality_signal == "degraded"`
- **empty_reason**: task `"xyzzy"` → `empty_reason == "no_token_overlap"`;
  task `"the a in"` → `empty_reason == "stop_words_only"`

**Dependencies**
- I2-T1 through I2-T6

**Acceptance criteria**
- each of the five scenario categories above has at least one passing test
- all 464 v1 tests still pass
- no new test relies on mock or stub of the indexer or query layer

**PR-sized**
- yes

---

## I2-T8. Update docs for iteration 2 behavior

**Why**
New retrieval behavior and configuration need to be visible to users and future maintainers.

**Scope**
- `ARCHITECTURE.md`: FTS5 schema section, `import_tokens_json` column, updated scoring formula
  with named weights, `_IMPORT_STOP_TOKENS` rationale, new env vars, `partial_reason` structure,
  new `get_index_status` fields, `empty_reason` field
- `README.md`: env var table, updated `get_edit_suggestions` description (FTS behavior, import
  tokens), `get_index_status` quality signal
- update `ITERATION2.md` and `TASKS_ITERATION2.md` only if final implementation differs
  meaningfully from the plan

**Dependencies**
- final behavior of I2-T1 through I2-T7

**Acceptance criteria**
- ARCHITECTURE.md reflects actual schema and scoring as implemented
- README env var table is accurate
- no v1-only content left un-updated in docs

**PR-sized**
- yes

---

## Dependency graph

```
I2-T1 (FTS schema)
  └─→ I2-T3 (FTS retrieval in get_edit_suggestions)
        └─→ I2-T4a (import token scoring)
              └─→ I2-T4b (reason[] + empty_reason)

I2-T2 (import token extraction)
  └─→ I2-T4a

I2-T5 (configurable caps)     ← independent, can run in parallel with retrieval track
I2-T6 (quality signal)        ← independent, can run in parallel with retrieval track

I2-T7 (e2e tests)             ← depends on I2-T1 through I2-T6
I2-T8 (docs)                  ← depends on I2-T7
```

I2-T5 and I2-T6 are independent of the retrieval track and can be developed in parallel.
Do not start I2-T3 before I2-T1 is merged. Do not start I2-T4a before both I2-T2 and I2-T3
are merged.

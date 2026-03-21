# Tasks: Repomind v1

This document breaks the v1 implementation into PR-sized engineering tasks.

The goal is to keep work small, reviewable, and testable.

---

## Workflow Rules

- Claude can pick one task at a time.
- Each task should normally result in one PR into `dev`.
- No merge happens without explicit user approval.
- Tests must pass before a PR is considered ready.
- `main` only receives changes after they have landed in `dev` and been validated.
- Every PR should include a short implementation note explaining what changed, how it was tested, and what remains risky.

---

## T01. Bootstrap Python project skeleton

**Why**
Everything else depends on a sane project layout, packaging config, and test harness.

**Scope**
- add Python package skeleton
- add `pyproject.toml`
- add base module layout from architecture doc
- add `.gitignore` updates if needed
- add test runner setup
- add minimal Dockerfile and local run instructions stub

**Dependencies**
- none

**Acceptance criteria**
- project installs locally
- tests can run through a single command
- package layout matches architecture doc
- Dockerfile builds successfully

**PR-sized**
- yes

---

## T02. Implement configuration and path resolution

**Why**
Repomind needs deterministic local storage paths and repo root resolution before it can index anything.

**Scope**
- implement config module
- implement repo root normalization
- implement stable repo hash generation
- implement index DB path resolution under local storage root
- support default storage path and override hooks if needed

**Dependencies**
- T01

**Acceptance criteria**
- same repo path always resolves to same DB path
- moved or invalid paths fail clearly
- config behavior is covered by tests

**PR-sized**
- yes

---

## T03. Implement SQLite schema and DB layer

**Why**
The DB schema is the contract the rest of the service builds against.

**Scope**
- create schema init and migration bootstrap
- implement DB open/init helpers
- create tables and indexes from `ARCHITECTURE.md`
- add integrity checks and schema version handling

**Dependencies**
- T01, T02

**Acceptance criteria**
- fresh DB initializes correctly
- schema version stored and readable
- indexes exist as expected
- tests verify schema bootstrap

**PR-sized**
- yes

---

## T04. Implement Git metadata detection

**Why**
Index freshness and branch-aware metadata depend on current branch and HEAD detection.

**Scope**
- detect whether repo is a Git repo
- get current branch
- get current HEAD SHA
- get recent commits and changed file lists
- handle non-Git degraded mode safely

**Dependencies**
- T01, T02

**Acceptance criteria**
- Git repos return branch and HEAD info
- non-Git repos degrade without crashing
- recent commit queries return structured data
- tests cover Git and non-Git cases

**PR-sized**
- yes

---

## T05. Implement repository walker and skip rules

**Why**
The indexer cannot exist until repo walking and skip behavior are deterministic.

**Scope**
- implement file and directory traversal
- enforce definitive skip list from architecture doc
- handle binary/noisy file filtering
- collect raw file metadata needed for indexing

**Dependencies**
- T01, T02

**Acceptance criteria**
- walker skips required directories and files
- collected metadata includes path, size, depth, and timestamps
- traversal works on small fixture repos
- tests verify skip behavior explicitly

**PR-sized**
- yes

---

## T06. Implement file classification and token extraction

**Why**
Critical files and edit suggestions depend on file types and extracted tokens.

**Scope**
- implement file classification rules
- extract path tokens
- extract directory tokens
- extract header/comment tokens where available
- store normalized metadata for later scoring

**Dependencies**
- T03, T05

**Acceptance criteria**
- manifests/configs/entrypoints/docs/tests are classified correctly on fixtures
- path and header tokens are deterministic
- token extraction is tested on representative samples

**PR-sized**
- yes

---

## T07. Implement importance scoring

**Why**
Repo overview, directory map, and critical files all depend on stable ranking.

**Scope**
- implement file importance scoring from architecture doc
- implement directory importance scoring
- implement inbound reference counting if included in schema
- persist computed scores during indexing

**Dependencies**
- T03, T05, T06

**Acceptance criteria**
- scoring follows documented formula
- outputs are deterministic for fixture repos
- directories and files get stable ranked order
- tests cover representative score scenarios

**PR-sized**
- yes

---

## T08. Implement refresh pipeline

**Why**
Repomind needs a safe way to build and replace indexes.

**Scope**
- implement full refresh coordinator
- create and finalize `index_runs`
- build temp DB and atomically replace live DB
- persist repo metadata, files, directories, and commits
- support partial-index flagging when limits are hit

**Dependencies**
- T03, T04, T05, T06, T07

**Acceptance criteria**
- refresh creates a usable DB
- failed refresh does not corrupt live DB
- atomic swap behavior is tested
- partial indexing state is preserved when triggered

**PR-sized**
- yes

---

## T09. Implement `get_index_status`

**Why**
This is the first tool agents should call and the trust anchor for freshness.

**Scope**
- implement current-vs-indexed branch/HEAD comparison
- return stale state, provenance, and `recommended_first_call`
- handle missing index and non-Git states clearly

**Dependencies**
- T03, T04, T08

**Acceptance criteria**
- missing index returns refresh recommendation
- current index returns `get_repo_overview` recommendation
- stale index returns `refresh_index` recommendation
- tests cover all three states

**PR-sized**
- yes

---

## T10. Implement `refresh_index`

**Why**
Without this tool the service cannot move from stale docs to actual indexable state.

**Scope**
- expose refresh pipeline through MCP tool
- return structured refresh result with provenance
- surface partial and failure states clearly

**Dependencies**
- T08, T09

**Acceptance criteria**
- tool triggers a full refresh successfully
- tool returns expected response contract
- tests cover success and failure paths

**PR-sized**
- yes

---

## T11. Implement `get_repo_overview`

**Why**
This is the main orientation tool after index status.

**Scope**
- return repo metadata
- return top directories
- return critical files
- attach provenance consistently

**Dependencies**
- T08, T09

**Acceptance criteria**
- output matches architecture contract
- ordering is driven by stored importance scores
- stale provenance is included when applicable

**PR-sized**
- yes

---

## T12. Implement `get_directory_map`

**Why**
Agents need navigable directory-level structure, not just top files.

**Scope**
- query important directories
- return role/summary/representative files
- support optional path filtering if convenient

**Dependencies**
- T08, T11

**Acceptance criteria**
- important directories are ranked and returned correctly
- response contract matches architecture doc
- tests cover representative fixture repo outputs

**PR-sized**
- yes

---

## T13. Implement `get_critical_files`

**Why**
Agents need a direct ranked file list before task-specific routing exists.

**Scope**
- query critical files by score and type
- filter out generated/noisy outputs
- return reasons where available

**Dependencies**
- T08, T11

**Acceptance criteria**
- manifests/entrypoints/configs rank near top where expected
- output shape matches architecture doc
- tests verify ranking sanity on fixtures

**PR-sized**
- yes

---

## T14. Implement `get_recent_changes`

**Why**
Branch-aware repo context is incomplete without recent committed change visibility.

**Scope**
- return recent commit data
- join commit-to-file changes
- degrade clearly for non-Git repos

**Dependencies**
- T04, T08

**Acceptance criteria**
- Git repos return recent commits and changed files
- non-Git repos return a clear degraded response
- tests cover both cases

**PR-sized**
- yes

---

## T15. Implement `get_edit_suggestions`

**Why**
This is the most product-critical v1 tool.

**Scope**
- tokenize task descriptions
- compute relevance score from path, directory, and header tokens
- combine with importance score
- exclude zero-overlap files
- return ranked suggestions with reasons and conservative confidence

**Dependencies**
- T06, T07, T08

**Acceptance criteria**
- scoring follows documented formula
- output includes `path`, `file_type`, `score`, `reason`, and `confidence`
- tests cover at least several realistic task queries against fixtures

**PR-sized**
- yes

---

## T16. MCP server wiring and tool descriptions

**Why**
The query engine needs an actual MCP surface and agent guidance.

**Scope**
- wire Python MCP server
- register all v1 tools
- add tool descriptions matching architecture guidance
- ensure `get_index_status` is clearly described as first call

**Dependencies**
- T09 through T15

**Acceptance criteria**
- all tools are callable through MCP
- response contracts match architecture doc
- tool descriptions guide usage correctly

**PR-sized**
- yes

---

## T17. End-to-end tests and fixture repos

**Why**
The system needs confidence beyond isolated unit tests.

**Scope**
- create fixture repos for Git and non-Git cases
- add end-to-end tests for refresh + query flow
- add stale-index behavior tests
- add partial-index behavior tests where practical

**Dependencies**
- T08 through T16

**Acceptance criteria**
- happy path works end-to-end
- stale and non-Git modes are covered
- test commands are documented and reproducible

**PR-sized**
- yes

---

## T18. Packaging and dev workflow hardening

**Why**
The repo should be runnable and reviewable by other agents and humans.

**Scope**
- tighten Docker support
- document local setup
- document MCP configuration example
- add lint/test commands to README or Make targets

**Dependencies**
- T16, T17

**Acceptance criteria**
- repo can be installed locally
- Docker image builds and runs
- MCP setup instructions are clear enough for first use

**PR-sized**
- yes

---

## Recommended first execution order

1. T01
2. T02
3. T03
4. T04
5. T05
6. T06
7. T07
8. T08
9. T09
10. T10
11. T11
12. T12
13. T13
14. T14
15. T15
16. T16
17. T17
18. T18

---

## Review note

If a task starts growing beyond one reviewable PR, split it before implementation instead of after the diff becomes unreadable.

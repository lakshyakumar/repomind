# Product Requirements Document: Repomind

## 1. Overview

Repomind is an MCP server that gives coding agents a reusable understanding of a repository so they do not have to repeatedly scan, grep, and re-learn the same codebase every session.

The goal is not to replace source code reading. The goal is to make source code reading targeted, cheaper, and more reliable.

Repomind should act as a repository intelligence layer that exposes structured answers to questions like:

- What does this repo do?
- Which directories matter?
- What are the critical files?
- Where does a request or workflow begin?
- Which files are likely edit points for a given task?
- What changed recently?

## 2. Problem Statement

Coding agents waste tokens and time re-understanding the same repository repeatedly.

In a normal task, an agent often has to:

- list directories
- inspect file trees
- read entry files
- infer architecture from file names
- retrace important flows
- guess where a change should be made

This creates four problems:

1. **High token usage** from repeated exploration
2. **Slow task startup** because context must be rebuilt every session
3. **Inconsistent understanding** across runs and across agents
4. **Lower edit quality** because agents often inspect the wrong files first

This pain becomes worse in medium or large repos, monorepos, and workflows where multiple tasks happen over time in the same codebase.

## 3. Vision

Repomind should become the MCP layer that gives coding agents a compact mental model of a repository before they start editing code.

Instead of asking an agent to rediscover architecture from scratch, the client should be able to ask Repomind for structured repo context and then use raw file reads only where precision is needed.

## 4. Goals

### Primary goals
- Reduce repeated token spend for repo understanding
- Reduce time-to-useful-context for coding agents
- Provide a structured, reusable repo map through MCP
- Improve consistency of agent understanding across repeated sessions
- Help agents identify likely edit points before opening many files

### Secondary goals
- Support recent change awareness
- Support branch-specific or diff-specific overlays later
- Support language-aware and framework-aware analysis over time

## 5. Non-goals

- Replacing normal source code reads
- Acting as a code execution environment
- Performing autonomous edits by itself
- Replacing Git or code search tools
- Guaranteeing perfect semantic understanding in v1

## 6. Target Users

### Primary users
- Developers using coding agents repeatedly on the same repository
- Teams building internal AI coding workflows
- Agent platform builders who want structured repo context

### Early adopter profile
A developer using Claude Code, Cursor, or similar coding agents on a medium-to-large repository who is frustrated by repeated context loading and wasted tokens.

## 7. User Stories

### Repository overview
- As a coding agent, I want a compact repo overview so I can understand the codebase before reading dozens of files.

### Directory map
- As a coding agent, I want to know what the main directories are for so I can navigate intentionally.

### Critical files
- As a coding agent, I want a ranked list of important files so I can inspect the highest-signal files first.

### Edit-point suggestions
- As a coding agent, I want likely edit targets for a task so I can start in the right place.

### Change awareness
- As a coding agent, I want recent changes summarized so I can understand what moved without scanning the whole repo again.

### Refresh
- As a coding agent or developer, I want to refresh repo intelligence after changes so the context stays trustworthy.

## 8. Core Product Requirements

### 8.1 Repository indexing
The system must:
- detect repository root
- traverse the project while skipping noisy directories
- identify important files and directories
- build a local structured index
- store index data locally for reuse

### 8.2 MCP tools
The system must expose MCP tools for:
- repository overview
- directory map
- critical files
- recent changes
- likely edit points
- index refresh

### 8.3 Grounded outputs
The system should:
- derive outputs from actual repo contents
- avoid hallucinated architectural claims
- preserve enough source references that outputs can be verified

### 8.4 Incremental usefulness
The system should provide useful output even with lightweight heuristics in v1.

It does not need perfect semantic analysis on day one.

## 9. Functional Requirements

### FR1. Repo overview
Repomind must return:
- repository name
- root path
- high-level summary
- primary languages or stack hints
- top directories
- critical files

### FR2. Directory purpose map
Repomind must return a ranked or filtered list of key directories with likely purpose descriptions.

### FR3. Critical files index
Repomind must rank and return high-signal files such as:
- manifests
- config files
- major entrypoints
- dense source files
- root documentation

### FR4. Recent changes
Repomind must surface recent Git history where available.

### FR5. Edit-point suggestions
Repomind must accept a natural-language task description and return likely files or directories to inspect first.

### FR6. Refreshable local index
Repomind must allow forced re-indexing.

## 10. Non-Functional Requirements

### Performance
- first index build should be reasonable for local development repos
- cached reads should be much faster than full rescans

### Reliability
- must fail safely when Git metadata is unavailable
- must degrade gracefully in non-Git directories

### Trust
- outputs must remain inspectable and grounded in source content
- summaries should be conservative over flashy

### Portability
- should run locally via MCP stdio
- should not require a remote backend for v1

## 11. MVP Scope

### In scope
- local MCP server
- local repo walking and indexing
- directory summaries
- critical file ranking
- recent Git change summaries
- task-to-edit-point suggestions
- local cache

### Out of scope
- deep AST call graphing
- language-server integration
- hosted indexing
- embeddings/vector retrieval
- multi-user shared state
- automatic file watching
- full branch intelligence model

## 12. Future Scope

- AST-based symbol graphs
- language-specific analyzers
- framework detectors
- branch/diff overlays
- confidence scores
- provenance metadata
- worktree awareness
- issue and PR overlays
- index invalidation on file changes

## 13. Success Metrics

### Primary metrics
- reduction in average tokens used for repo understanding
- reduction in time-to-first-useful-edit
- reduction in number of files opened before first correct edit

### Secondary metrics
- repeated session speedup on the same repo
- usefulness rating of overview and edit-point tools
- cache hit rate

## 14. Risks

- summaries may become stale if refresh is not used enough
- lightweight heuristics may be too shallow for complex repos
- poor grounding would reduce trust fast
- product may be mistaken for generic code search if positioning is weak

## 15. Open Questions

- What is the best cache format for long-term evolution?
- Which languages should get first-class analyzers first?
- How much of the repo graph should be precomputed vs generated on demand?
- Should branch-aware overlays be a core feature or a later module?
- How should Repomind expose provenance in MCP responses?

## 16. Positioning

Repomind should be positioned as:

**Repository intelligence for coding agents**

Not:
- just a token-saving utility
- just another code search tool
- just a Git helper

Token savings is the wedge.
The real product is faster, more reliable repo understanding.

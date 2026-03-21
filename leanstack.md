# Leanstack: Repomind

## 1. Problem

Coding agents repeatedly spend tokens re-understanding the same repository.

Before they can make a useful change, they often need to:

- scan the directory tree
- identify important folders
- locate likely entrypoints
- infer architecture from scattered modules
- retrace function flow
- rediscover where a bug or feature likely lives

This creates three problems:

1. **High token usage** from repeated repo exploration
2. **Slow startup** for every new agent session
3. **Inconsistent understanding** of the same codebase across runs

The pain gets worse in large repos, monorepos, and repeated issue-fix workflows.

## 2. Existing Alternatives

Current workarounds are all a bit cursed:

- let the agent search and read the repo every time
- stuff architecture notes into prompts
- maintain hand-written docs that drift out of date
- use vector search over code snippets
- rely on IDE indexing that is not cleanly exposed to agents through MCP

### Why these fall short

- repeated token burn
- stale documentation
- poor structural understanding
- no reusable architectural memory
- low consistency between sessions and agents

## 3. Customer Segments

### Early adopters
- developers using coding agents daily on the same repo
- teams building internal AI coding assistants
- agent platform builders who need codebase context as infrastructure
- maintainers of medium or large codebases where repeated context loading is expensive

### Beachhead user
A developer who uses a coding agent repeatedly on a medium-to-large repo and is tired of watching it rediscover the same architecture every session.

## 4. Unique Value Proposition

**Repomind gives coding agents a reusable understanding of a repository so they can spend tokens solving problems instead of re-learning the codebase.**

### One-liner

**Repository intelligence for coding agents.**

### High-concept pitch

Like an architecture map and working memory layer for AI agents operating on real codebases.

## 5. Solution

Repomind is an MCP server that exposes a structured, token-efficient model of the repository.

Instead of forcing the agent to infer everything from raw file access, Repomind can provide:

- repository overview
- directory purpose map
- critical files index
- module summaries
- function and request flow summaries
- likely edit points for a task
- recent or branch-specific context

The agent still reads source files when precision matters, but only after it knows where to look.

## 6. Key Benefits

- lower token usage
- faster agent startup
- more consistent repo understanding
- fewer wrong edits in unrelated files
- better continuity across sessions
- improved support for repeated work on the same codebase

## 7. Unfair Advantage

Most tools expose code. Very few expose a maintained, structured understanding of the codebase.

Repomind can build an advantage by combining:

- repo structure indexing
- architecture summaries
- flow extraction
- incremental refresh
- branch-aware or diff-aware overlays
- provenance-backed outputs tied to real source files

The moat is not raw parsing. The moat is useful repo understanding that stays grounded and refreshable.

## 8. Channels

### Launch channels
- GitHub
- MCP ecosystem directories and examples
- developer communities around Claude Code, Cursor, Copilot, OpenAI MCP clients
- X, Hacker News, Reddit, Discord devtool communities
- demos showing repeated agent sessions with lower context cost

### Best content angle
- why coding agents waste tokens on repo rediscovery
- why repo intelligence is better than prompt stuffing
- how MCP can expose architecture context cleanly

## 9. Revenue Streams

### Open source core
- local MCP server
- local index generation
- local structured repo context tools

### Potential paid layer later
- team-shared repo intelligence
- background indexing service
- GitHub or GitLab integration
- branch, PR, and issue overlays
- audit and approval workflows
- hosted dashboards and observability

Not needed on day one. First prove the pain.

## 10. Cost Structure

### Build costs
- parser and indexing pipeline
- storage for repo intelligence
- summarization and flow extraction logic
- incremental refresh logic
- testing across multiple repo types

### Ongoing costs
- keeping summaries grounded and useful
- handling multiple languages and frameworks
- edge cases in large repos and monorepos
- UX consistency across MCP clients

## 11. Key Metrics

For validation, track:

- average tokens saved per task
- average time-to-useful-context
- number of repo queries answered without full file rescans
- number of repeated sessions on the same repo
- developer-rated usefulness of summaries and edit hints
- reduction in irrelevant file reads

## 12. Early Adopter Signal

Strong signals would be users saying:

- "My agent stops re-reading the same project every time"
- "I can point the agent at a big repo without paying the context tax"
- "The agent now knows where to look before it starts poking random files"

## 13. High-Level MVP

### Must-have
- repo overview
- directory purpose map
- critical files index
- module summaries
- flow summaries for key entrypoints
- refresh or reindex tool

### Nice-to-have after
- branch-specific overlays
- recent change awareness
- likely edit points for a task
- confidence scoring
- provenance and source references

## 14. Riskiest Assumptions

1. Agents and developers will trust summarized repo understanding enough to use it as a first stop.
2. The MCP server can stay fresh enough that the summaries do not rot instantly.
3. The token savings are meaningful enough to change workflow behavior.
4. The repo model can be generated cheaply enough to justify maintaining it.
5. Structured repo understanding is more useful than plain search for common coding tasks.

## 15. Experiments

### Experiment 1
Build a thin MVP that returns:
- repo overview
- critical files
- directory purpose map

Measure whether this reduces file reads during common tasks.

### Experiment 2
Compare two workflows on the same repo:
- agent with normal search and file reads only
- agent with Repomind context first

Measure:
- token usage
- time to first correct edit
- number of files opened

### Experiment 3
Test repeated sessions over the same repo.

If Repomind works, the second and third session should get sharply faster and cheaper.

## 16. Why Now

- coding agents are now operating on real repositories, not toy snippets
- MCP gives a standard way to expose structured tools to agents
- repo context costs are becoming visible as teams use agents repeatedly
- large-context models still waste money if they keep rediscovering stable architecture

## 17. Positioning

Do not pitch this as just "token savings."
That sounds small.

Pitch it as:

**repository intelligence infrastructure for coding agents**

Token savings is the wedge.
The real value is faster, cheaper, more reliable codebase understanding.

## 18. Tagline Ideas

- Repository intelligence for coding agents
- Stop making agents rediscover your repo
- Structured codebase understanding over MCP
- Give coding agents a memory of your codebase

## 19. Current Recommendation

Start simple.

Build the layer that answers:
- what this repo does
- where things live
- what files matter
- how key flows work
- where to start editing

If that works, branch-aware context becomes an excellent second layer instead of the whole product.

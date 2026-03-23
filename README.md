# Repomind

Repomind is a local MCP server and repo query engine for coding agents.

It indexes the currently checked-out state of a Git repository, records branch and commit metadata at index time, and serves structured, grounded repo queries on demand. It makes no LLM calls at query time.

## MCP tools

| Tool | Purpose |
|---|---|
| `get_index_status` | Check index freshness. **Call this first.** |
| `refresh_index` | Rebuild the index for the current branch and HEAD |
| `get_repo_overview` | Stack hints, top directories, critical files |
| `get_directory_map` | Ranked directory tree with roles and representative files |
| `get_critical_files` | Files ranked by importance score |
| `get_recent_changes` | Recent commits and changed files |
| `get_edit_suggestions` | Ranked file suggestions for a task description |

## Local setup (venv)

```bash
git clone https://github.com/lakshyakumar/repomind.git
cd repomind
git checkout dev
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
make check
```

If you reopen the repo later, reactivate the environment with:

```bash
source .venv/bin/activate
```

The MCP server entrypoint is then:

```bash
.venv/bin/repomind
```


## MCP configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent on your platform:

```json
{
  "mcpServers": {
    "repomind": {
      "command": "repomind"
    }
  }
}
```

Once configured, instruct the agent to call `get_index_status` with the `repo_root` set to the absolute path of the repository it is working on.

### Other MCP clients

Repomind uses stdio transport. Any MCP client that supports stdio servers can run it with:

```
repomind
```

Each tool accepts `repo_root` as the absolute path to the repository.

## Docker

Build the image:

```bash
make docker-build
# or: docker build -t repomind:latest .
```

Run as an MCP server with a local repository mounted:

```bash
docker run --rm -i \
  -v /path/to/your/repo:/repo \
  -v "$HOME/.repomind:/root/.repomind" \
  repomind:latest
```

- `-i` is required — MCP communicates over stdio.
- Mount the target repository at any path and pass that path as `repo_root` when calling tools.
- The second volume persists the index across container runs. Omit it to use a fresh index each time.

To configure Claude Desktop to use the Docker image:

```json
{
  "mcpServers": {
    "repomind": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/your/repo:/repo",
        "-v", "/path/to/.repomind:/root/.repomind",
        "repomind:latest"
      ]
    }
  }
}
```

## Dev commands

| Command | What it does |
|---|---|
| `make install` | Install production package |
| `make install-dev` | Install with test + lint deps |
| `make test` | Run test suite |
| `make lint` | Check with ruff |
| `make format` | Auto-fix lint issues |
| `make check` | Lint + test |
| `make docker-build` | Build Docker image |
| `make clean` | Remove build artifacts |

## Storage

Repomind stores its index at `~/.repomind/` by default. Override with:

```bash
export REPOMIND_STORAGE_ROOT=/custom/path
```

## Why this is useful for agents

Repomind is useful when an agent keeps paying the same repo-context tax over and over.

Instead of repeatedly listing directories, opening manifests, grepping for entrypoints, and rediscovering recent changes, the agent can query a local index first and read source files more selectively.

### What should improve
- fewer irrelevant file reads before the first correct edit
- fewer repeated repo-exploration tool calls
- lower token/context burn from re-learning the same codebase
- faster time to first useful change on repeated sessions
- clearer stale-vs-fresh signals before trusting repo context

### Practical metrics to track
If you want to prove Repomind is helping, compare a normal agent workflow vs a Repomind-first workflow on the same repo and task set.

Track things like:
- **files opened before first correct edit**
- **time to first useful edit**
- **number of repo-exploration tool calls** such as repeated `find`, `ls`, `grep`, `read`, or code-search calls
- **token spend / context usage** if your client exposes it
- **refresh frequency** and stale-index detection rate

### Agent-oriented success signal
A good outcome is not “the overview looks nice.”
A good outcome is:
- the agent starts in the right files sooner
- asks fewer exploratory questions about the repo
- avoids re-reading stable architecture every session
- produces fewer wrong-file detours before making the intended change


## Docs

- [PRD](./PRD.md)
- [Architecture](./ARCHITECTURE.md)


## Docker setup

Build the image:

```bash
docker build -t repomind:latest .
```

Run it as an MCP stdio server with your repo mounted in:

```bash
docker run --rm -i   -v /absolute/path/to/your/repo:/repo   -v "$HOME/.repomind:/root/.repomind"   repomind:latest
```

Notes:
- replace `/absolute/path/to/your/repo` with the real repo path you want the MCP client to point at
- the `~/.repomind` mount keeps the local index/cache persistent between runs
- this is an stdio MCP server, so it will sit quietly until a client connects

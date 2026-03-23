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

## Local setup

Requires Python 3.11+.

```bash
# Install (production dependencies only)
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"

# Run the test suite
make test

# Lint
make lint

# Lint + test together
make check
```

The `repomind` entry point is registered by the package install. Confirm it is available:

```bash
which repomind
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

## Docs

- [PRD](./PRD.md)
- [Architecture](./ARCHITECTURE.md)

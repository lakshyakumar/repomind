FROM python:3.11-slim

WORKDIR /app

# Copy package files and install
COPY pyproject.toml .
COPY repomind/ ./repomind/
RUN pip install --no-cache-dir -e .

# MCP servers communicate over stdio — the container must be run with -i.
# The repo to index and the index storage directory are supplied as bind mounts
# at runtime (see README for examples).
ENTRYPOINT ["repomind"]

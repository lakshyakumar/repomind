"""Git metadata layer: branch, HEAD SHA, recent commits."""

import os
from pathlib import Path


def resolve_repo_root(path: str = "") -> str:
    """Resolve and validate a repo root path.

    Args:
        path: directory path to resolve. If empty, defaults to cwd.

    Returns:
        Absolute, canonicalised path string.

    Raises:
        ValueError: if the resolved path is not an existing directory.
    """
    if not path:
        path = os.getcwd()

    resolved = Path(path).resolve()

    if not resolved.exists():
        raise ValueError(f"Path does not exist: {path!r} (resolved: {resolved})")

    if not resolved.is_dir():
        raise ValueError(
            f"Path is not a directory: {path!r} (resolved: {resolved})"
        )

    return str(resolved)

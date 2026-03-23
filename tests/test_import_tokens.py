"""Tests for I2-T2: Python import-token extraction.

Acceptance criteria:
- 'queries', 'edit', 'suggestions' in import tokens for a file containing
  'from repomind.queries import get_edit_suggestions' (or subset after filtering)
- 'os', 'sys', 'json', 'typing' absent from import tokens for any file
- import_tokens_json populated (non-empty) for Python files with imports
- import_tokens_json is '[]' for files with no extractable imports
- import_tokens_json is '[]' for non-Python files
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomind.extractor import (
    _IMPORT_STOP_TOKENS,
    extract_import_tokens,
)
from repomind.refresh import refresh_index

# ---------------------------------------------------------------------------
# Unit tests for extract_import_tokens
# ---------------------------------------------------------------------------


def test_from_import_yields_module_and_name_tokens(tmp_path: Path):
    f = tmp_path / "queries.py"
    f.write_text("from repomind.queries import get_edit_suggestions\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "queries" in tokens
    # get_edit_suggestions → 'get' filtered (stop word), 'edit', 'suggestions' remain
    assert "edit" in tokens
    assert "suggestions" in tokens


def test_stop_tokens_absent_os(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("import os\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "os" not in tokens


def test_stop_tokens_absent_sys(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("import sys\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "sys" not in tokens


def test_stop_tokens_absent_json(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("import json\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "json" not in tokens


def test_stop_tokens_absent_typing(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("from typing import List, Dict\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "typing" not in tokens


def test_all_required_stop_tokens_are_defined():
    """Verify the mandated minimum stop-token set is present."""
    required = {
        "os", "sys", "re", "io", "abc", "typing", "types", "collections",
        "functools", "itertools", "contextlib", "dataclasses", "pathlib",
        "logging", "warnings", "string", "enum", "datetime", "threading",
        "asyncio", "inspect", "traceback", "struct", "hashlib", "base64",
        "uuid", "http", "urllib", "socket", "json", "math", "time", "copy",
        "random", "subprocess",
    }
    assert required.issubset(_IMPORT_STOP_TOKENS)


def test_non_python_extension_returns_empty(tmp_path: Path):
    f = tmp_path / "index.js"
    f.write_text("import express from 'express';\n")
    assert extract_import_tokens(str(f), ".js") == []


def test_no_imports_returns_empty(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\ny = 2\n")
    assert extract_import_tokens(str(f), ".py") == []


def test_plain_import_module(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("import repomind.queries\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "repomind" in tokens
    assert "queries" in tokens


def test_multiple_import_lines(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text(
        "from repomind.db import open_db\n"
        "from repomind.extractor import classify_and_extract\n"
    )
    tokens = extract_import_tokens(str(f), ".py")
    assert "repomind" in tokens
    assert "db" in tokens
    assert "extractor" in tokens
    assert "classify" in tokens


def test_comma_separated_from_import(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("from repomind.queries import get_index_status, get_directory_map\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "queries" in tokens
    assert "index" in tokens
    assert "status" in tokens
    assert "directory" in tokens


def test_import_tokens_are_unique(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text(
        "from repomind.queries import get_index_status\n"
        "from repomind.refresh import refresh_index\n"
    )
    tokens = extract_import_tokens(str(f), ".py")
    assert tokens.count("repomind") == 1


def test_missing_file_returns_empty(tmp_path: Path):
    assert extract_import_tokens(str(tmp_path / "nonexistent.py"), ".py") == []


def test_stop_words_from_general_list_filtered(tmp_path: Path):
    """Tokens in _STOP_TOKENS (e.g. 'get') are also filtered."""
    f = tmp_path / "a.py"
    f.write_text("from repomind.queries import get_index_status\n")
    tokens = extract_import_tokens(str(f), ".py")
    assert "get" not in tokens


# ---------------------------------------------------------------------------
# Integration tests: import_tokens_json in the DB after refresh
# ---------------------------------------------------------------------------


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


def _make_import_repo(base: Path) -> Path:
    """Repo with Python files that have import statements."""
    r = base / "repo"
    r.mkdir()

    (r / "main.py").write_text(
        "from repomind.queries import get_edit_suggestions\n"
        "import repomind.db\n"
        "x = 1\n"
    )
    (r / "utils.py").write_text(
        "import os\n"
        "import sys\n"
        "import json\n"
        "from typing import List\n"
        "def helper(): pass\n"
    )
    (r / "clean.py").write_text("x = 1\ny = 2\n")  # no imports
    (r / "README.md").write_text("# Repo\n")        # non-Python
    return r


def test_import_tokens_json_populated_for_python_with_imports(tmp_path, storage):
    repo = _make_import_repo(tmp_path)
    result = refresh_index(str(repo))
    assert result.status == "ok"

    from repomind.db import open_db
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT import_tokens_json FROM files WHERE path = 'main.py'"
    ).fetchone()
    assert row is not None
    tokens = json.loads(row["import_tokens_json"])
    assert isinstance(tokens, list)
    assert len(tokens) > 0
    assert "queries" in tokens
    assert "edit" in tokens


def test_import_tokens_json_empty_for_no_imports(tmp_path, storage):
    repo = _make_import_repo(tmp_path)
    refresh_index(str(repo))

    from repomind.db import open_db
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT import_tokens_json FROM files WHERE path = 'clean.py'"
    ).fetchone()
    assert row is not None
    assert json.loads(row["import_tokens_json"]) == []


def test_stop_tokens_absent_from_db_row(tmp_path, storage):
    repo = _make_import_repo(tmp_path)
    refresh_index(str(repo))

    from repomind.db import open_db
    conn = open_db(str(repo))
    rows = conn.execute("SELECT import_tokens_json FROM files").fetchall()
    for row in rows:
        tokens = json.loads(row["import_tokens_json"])
        for bad in ("os", "sys", "json", "typing"):
            assert bad not in tokens, f"stop token '{bad}' found in {tokens}"


def test_import_tokens_json_empty_for_non_python(tmp_path, storage):
    repo = _make_import_repo(tmp_path)
    refresh_index(str(repo))

    from repomind.db import open_db
    conn = open_db(str(repo))
    row = conn.execute(
        "SELECT import_tokens_json FROM files WHERE path = 'README.md'"
    ).fetchone()
    assert row is not None
    assert json.loads(row["import_tokens_json"]) == []


def test_import_tokens_json_column_exists_in_schema(tmp_path, storage):
    repo = _make_import_repo(tmp_path)
    refresh_index(str(repo))

    from repomind.db import open_db
    conn = open_db(str(repo))
    cols = [row[1] for row in conn.execute("PRAGMA table_info(files)").fetchall()]
    assert "import_tokens_json" in cols

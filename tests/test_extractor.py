"""Tests for repomind.extractor: classification, path tokens, header tokens."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomind.extractor import (
    classify_and_extract,
    classify_file,
    extract_header_tokens,
    extract_path_tokens,
)
from repomind.models import ClassifiedFile, FileRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(path: str, depth: int | None = None, is_noisy: bool = False) -> FileRecord:
    """Build a minimal FileRecord for classification tests."""
    if depth is None:
        depth = path.count("/")
    return FileRecord(
        path=path,
        abs_path=f"/repo/{path}",
        size_bytes=100,
        depth=depth,
        last_modified_ts=None,
        is_noisy=is_noisy,
    )


# ---------------------------------------------------------------------------
# classify_file: manifest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "setup.py",
        "requirements.txt",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "Gemfile",
        "src/Cargo.toml",
        "services/api/pyproject.toml",
    ],
)
def test_classify_manifest(path: str) -> None:
    assert classify_file(_rec(path)) == "manifest"


def test_classify_csproj_extension() -> None:
    assert classify_file(_rec("MyApp.csproj")) == "manifest"


# ---------------------------------------------------------------------------
# classify_file: config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "Makefile",
        "Dockerfile",
        ".env",
        ".env.example",
        ".gitignore",
        "docker-compose.yml",
        "tsconfig.json",
        ".eslintrc.json",
        ".prettierrc",
        "jest.config.ts",
        "vite.config.js",
        "webpack.config.ts",
        "ruff.toml",
        "pytest.ini",
        "mypy.ini",
        ".travis.yml",
        "renovate.json",
    ],
)
def test_classify_config(path: str) -> None:
    assert classify_file(_rec(path)) == "config"


def test_classify_config_suffix_pattern() -> None:
    # *.config.js / *.config.ts
    assert classify_file(_rec("tailwind.config.js")) == "config"
    assert classify_file(_rec("next.config.ts")) == "config"


def test_classify_yaml_in_ci_dir() -> None:
    assert classify_file(_rec(".github/workflows/ci.yml", depth=2)) == "config"
    assert classify_file(_rec(".circleci/config.yml", depth=1)) == "config"


def test_yaml_outside_ci_dir_is_not_config() -> None:
    # A plain YAML in src/ should not become config — it falls through to other.
    result = classify_file(_rec("src/data.yml", depth=1))
    assert result != "config"


# ---------------------------------------------------------------------------
# classify_file: docs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE.md",
        "ARCHITECTURE.md",
        "docs/getting-started.md",
        "doc/api.rst",
        "documentation/guide.md",
    ],
)
def test_classify_docs(path: str) -> None:
    assert classify_file(_rec(path)) == "docs"


def test_classify_md_extension_is_always_docs() -> None:
    # Any .md file (even deep in source) is docs.
    assert classify_file(_rec("src/internal/notes.md", depth=2)) == "docs"


# ---------------------------------------------------------------------------
# classify_file: test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_main.py",
        "test/api_test.go",
        "__tests__/App.test.tsx",
        "src/utils.test.ts",
        "src/utils.spec.ts",
        "test_utils.py",
    ],
)
def test_classify_test(path: str) -> None:
    assert classify_file(_rec(path)) == "test"


# ---------------------------------------------------------------------------
# classify_file: entrypoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "main.py",
        "main.go",
        "server.js",
        "app.ts",
        "index.ts",
        "src/main.py",
        "src/server.js",
        "manage.py",
        "__main__.py",
    ],
)
def test_classify_entrypoint(path: str) -> None:
    assert classify_file(_rec(path)) == "entrypoint"


def test_deep_main_is_source_not_entrypoint() -> None:
    # main.py at depth 3 should not be entrypoint.
    rec = _rec("a/b/c/main.py", depth=3)
    result = classify_file(rec)
    assert result == "source"


# ---------------------------------------------------------------------------
# classify_file: source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "src/api.py",
        "lib/utils.ts",
        "internal/handler.go",
        "src/components/Button.tsx",
        "pkg/service.rs",
    ],
)
def test_classify_source(path: str) -> None:
    assert classify_file(_rec(path)) == "source"


# ---------------------------------------------------------------------------
# classify_file: generated (noisy)
# ---------------------------------------------------------------------------


def test_classify_noisy_is_generated() -> None:
    rec = _rec("package-lock.json", is_noisy=True)
    assert classify_file(rec) == "generated"


def test_classify_image_noisy_is_generated() -> None:
    rec = _rec("assets/logo.png", is_noisy=True)
    assert classify_file(rec) == "generated"


# ---------------------------------------------------------------------------
# classify_file: other
# ---------------------------------------------------------------------------


def test_classify_other_for_unknown_extension() -> None:
    result = classify_file(_rec("data/export.csv"))
    assert result == "other"


def test_classify_other_for_no_extension() -> None:
    result = classify_file(_rec("somefile"))
    assert result == "other"


# ---------------------------------------------------------------------------
# extract_path_tokens
# ---------------------------------------------------------------------------


def test_path_tokens_root_file() -> None:
    tokens = extract_path_tokens("main.py")
    assert "main" in tokens


def test_path_tokens_includes_dir_components() -> None:
    tokens = extract_path_tokens("src/api/user_handler.py")
    assert "src" in tokens
    assert "api" in tokens
    assert "user" in tokens
    assert "handler" in tokens


def test_path_tokens_excludes_extension() -> None:
    tokens = extract_path_tokens("src/server.py")
    # "py" is a short stop word — should not appear as a token
    assert "py" not in tokens


def test_path_tokens_camel_case_split() -> None:
    tokens = extract_path_tokens("src/MyService.ts")
    assert "my" in tokens
    assert "service" in tokens


def test_path_tokens_snake_case_split() -> None:
    tokens = extract_path_tokens("src/user_auth_handler.py")
    assert "user" in tokens
    assert "auth" in tokens
    assert "handler" in tokens


def test_path_tokens_are_lowercase() -> None:
    tokens = extract_path_tokens("src/UserController.ts")
    for t in tokens:
        assert t == t.lower()


def test_path_tokens_are_unique() -> None:
    tokens = extract_path_tokens("src/src/utils.py")
    assert tokens.count("src") == 1


def test_path_tokens_no_empty_strings() -> None:
    tokens = extract_path_tokens("src/api/v1/handler.go")
    assert all(len(t) > 0 for t in tokens)


# ---------------------------------------------------------------------------
# extract_header_tokens
# ---------------------------------------------------------------------------


def test_header_tokens_python_hash_comment(tmp_path: Path) -> None:
    f = tmp_path / "module.py"
    f.write_text("# Authentication helper for user sessions\n\ndef login(): pass\n")
    tokens = extract_header_tokens(str(f), ".py")
    assert "authentication" in tokens or "auth" in tokens
    assert "helper" in tokens
    assert "user" in tokens
    assert "sessions" in tokens or "session" in tokens


def test_header_tokens_js_slash_comment(tmp_path: Path) -> None:
    f = tmp_path / "server.js"
    f.write_text(
        "// HTTP server initialization and routing\n"
        "// Handles webhook callbacks\n"
        "const express = require('express');\n"
    )
    tokens = extract_header_tokens(str(f), ".js")
    assert "http" in tokens
    assert "server" in tokens
    assert "routing" in tokens
    assert "webhook" in tokens


def test_header_tokens_go_comment(tmp_path: Path) -> None:
    f = tmp_path / "main.go"
    f.write_text(
        "// Package main is the entry point for the indexing service.\n"
        "package main\n"
    )
    tokens = extract_header_tokens(str(f), ".go")
    assert "package" in tokens or "indexing" in tokens or "service" in tokens


def test_header_tokens_unknown_extension_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "data.csv"
    f.write_text("col1,col2\n1,2\n")
    tokens = extract_header_tokens(str(f), ".csv")
    assert tokens == []


def test_header_tokens_no_comments_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "plain.py"
    f.write_text("x = 1\ny = 2\n")
    tokens = extract_header_tokens(str(f), ".py")
    assert tokens == []


def test_header_tokens_are_lowercase(tmp_path: Path) -> None:
    f = tmp_path / "svc.py"
    f.write_text("# Database Connection Manager\n")
    tokens = extract_header_tokens(str(f), ".py")
    for t in tokens:
        assert t == t.lower()


def test_header_tokens_are_unique(tmp_path: Path) -> None:
    f = tmp_path / "dup.py"
    f.write_text("# cache cache cache layer\n# cache manager\n")
    tokens = extract_header_tokens(str(f), ".py")
    assert tokens.count("cache") == 1


def test_header_tokens_unreadable_returns_empty() -> None:
    tokens = extract_header_tokens("/nonexistent/path/file.py", ".py")
    assert tokens == []


def test_header_tokens_yaml_comment(tmp_path: Path) -> None:
    f = tmp_path / "ci.yml"
    f.write_text("# Continuous integration workflow for deployment\nname: CI\n")
    tokens = extract_header_tokens(str(f), ".yml")
    assert "continuous" in tokens or "integration" in tokens or "deployment" in tokens


# ---------------------------------------------------------------------------
# classify_and_extract (end-to-end)
# ---------------------------------------------------------------------------


def test_classify_and_extract_returns_classified_file(tmp_path: Path) -> None:
    f = tmp_path / "main.py"
    f.write_text("# Entry point\ndef main(): pass\n")
    rec = FileRecord(
        path="main.py",
        abs_path=str(f),
        size_bytes=f.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
    )
    result = classify_and_extract(rec)
    assert isinstance(result, ClassifiedFile)
    assert result.file_type == "entrypoint"
    assert result.extension == ".py"
    assert result.directory_path == ""
    assert "main" in result.path_tokens
    assert isinstance(result.line_count, int)
    assert result.line_count == 2


def test_classify_and_extract_nested_source(tmp_path: Path) -> None:
    src = tmp_path / "src" / "api"
    src.mkdir(parents=True)
    f = src / "handler.py"
    f.write_text("# Request handler\ndef handle(): pass\n")
    rec = FileRecord(
        path="src/api/handler.py",
        abs_path=str(f),
        size_bytes=f.stat().st_size,
        depth=2,
        last_modified_ts=None,
        is_noisy=False,
    )
    result = classify_and_extract(rec)
    assert result.file_type == "source"
    assert result.directory_path == "src/api"
    assert result.extension == ".py"
    assert "src" in result.path_tokens
    assert "api" in result.path_tokens
    assert "handler" in result.path_tokens
    assert "request" in result.header_tokens or "handler" in result.header_tokens


def test_classify_and_extract_noisy_skips_line_count(tmp_path: Path) -> None:
    f = tmp_path / "package-lock.json"
    f.write_text("{}")
    rec = FileRecord(
        path="package-lock.json",
        abs_path=str(f),
        size_bytes=f.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=True,
    )
    result = classify_and_extract(rec)
    assert result.file_type == "generated"
    assert result.line_count is None


def test_classify_and_extract_preserves_record_fields(tmp_path: Path) -> None:
    f = tmp_path / "lib.py"
    f.write_text("x = 1\n")
    rec = FileRecord(
        path="lib.py",
        abs_path=str(f),
        size_bytes=5,
        depth=0,
        last_modified_ts="2026-03-22T00:00:00+00:00",
        is_noisy=False,
    )
    result = classify_and_extract(rec)
    assert result.path == rec.path
    assert result.abs_path == rec.abs_path
    assert result.size_bytes == rec.size_bytes
    assert result.depth == rec.depth
    assert result.last_modified_ts == rec.last_modified_ts
    assert result.is_noisy == rec.is_noisy

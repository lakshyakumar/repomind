"""Tests for the MCP server wiring (T16).

Uses the fastmcp in-process Client to verify that all v1 tools are
registered, callable, and return the expected shape. Tests run the
actual query layer against real fixture repos — no mocking.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastmcp import Client

from repomind.mcp_server import mcp
from repomind.queries import run_refresh_index

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)


def _init_git(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "t@t.com")
    _git(path, "config", "user.name", "T")
    (path / ".keep").write_text("")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    s = tmp_path / "storage"
    s.mkdir()
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(s))
    return s


@pytest.fixture()
def indexed_repo(tmp_path: Path, storage: Path) -> Path:
    """Minimal git repo that has been indexed."""
    r = tmp_path / "repo"
    r.mkdir()
    src = r / "src"
    src.mkdir()
    (src / "main.py").write_text("def main(): pass\n" * 20)
    (r / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    _init_git(r)
    run_refresh_index(str(r))
    return r


@pytest.fixture()
def unindexed_repo(tmp_path: Path, storage: Path) -> Path:
    """Git repo with no index yet."""
    r = tmp_path / "repo"
    r.mkdir()
    (r / "main.py").write_text("x = 1\n")
    _init_git(r)
    return r


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_all_tools_registered() -> None:
    """All 7 v1 tools must be registered on the MCP server."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    expected = {
        "get_index_status",
        "refresh_index",
        "get_repo_overview",
        "get_directory_map",
        "get_critical_files",
        "get_recent_changes",
        "get_edit_suggestions",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


@pytest.mark.anyio
async def test_all_tools_have_descriptions() -> None:
    """Every registered tool must have a non-empty description."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description, f"Tool {tool.name!r} has no description"
        assert len(tool.description.strip()) > 10, (
            f"Tool {tool.name!r} description too short: {tool.description!r}"
        )


@pytest.mark.anyio
async def test_get_index_status_description_mentions_first(
    indexed_repo: Path,
) -> None:
    """get_index_status description must make clear it should be called first."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    status_tool = next(t for t in tools if t.name == "get_index_status")
    desc_lower = status_tool.description.lower()
    assert "first" in desc_lower or "start" in desc_lower, (
        "get_index_status description does not indicate it should be called first"
    )


# ---------------------------------------------------------------------------
# get_index_status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_index_status_callable(unindexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_index_status", {"repo_root": str(unindexed_repo)}
        )
    assert not result.is_error
    assert isinstance(result.data, dict)


@pytest.mark.anyio
async def test_get_index_status_has_required_keys(unindexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_index_status", {"repo_root": str(unindexed_repo)}
        )
    data = result.data
    for key in ("is_git_repo", "has_index", "stale", "refresh_recommended",
                "recommended_first_call", "partial", "provenance"):
        assert key in data, f"Missing key: {key}"


@pytest.mark.anyio
async def test_get_index_status_no_index_recommends_refresh(
    unindexed_repo: Path,
) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_index_status", {"repo_root": str(unindexed_repo)}
        )
    assert result.data["has_index"] is False
    assert result.data["recommended_first_call"] == "refresh_index"


# ---------------------------------------------------------------------------
# refresh_index
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_refresh_index_callable(unindexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "refresh_index", {"repo_root": str(unindexed_repo)}
        )
    assert not result.is_error
    data = result.data
    assert data["status"] == "ok"
    assert data["refreshed"] is True


@pytest.mark.anyio
async def test_refresh_index_has_provenance(unindexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "refresh_index", {"repo_root": str(unindexed_repo)}
        )
    assert "provenance" in result.data
    assert isinstance(result.data["provenance"], dict)


# ---------------------------------------------------------------------------
# get_repo_overview
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_repo_overview_callable(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_repo_overview", {"repo_root": str(indexed_repo)}
        )
    assert not result.is_error
    data = result.data
    for key in ("repo_name", "repo_root", "is_git_repo", "stack_hints",
                "top_directories", "critical_files", "provenance"):
        assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# get_directory_map
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_directory_map_callable(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_directory_map", {"repo_root": str(indexed_repo)}
        )
    assert not result.is_error
    assert "directories" in result.data
    assert isinstance(result.data["directories"], list)


@pytest.mark.anyio
async def test_get_directory_map_path_filter(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_directory_map",
            {"repo_root": str(indexed_repo), "path_filter": "src"},
        )
    assert not result.is_error
    for d in result.data["directories"]:
        assert d["path"] == "src" or d["path"].startswith("src/")


# ---------------------------------------------------------------------------
# get_critical_files
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_critical_files_callable(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_critical_files", {"repo_root": str(indexed_repo)}
        )
    assert not result.is_error
    assert "files" in result.data
    assert isinstance(result.data["files"], list)


@pytest.mark.anyio
async def test_get_critical_files_no_generated(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_critical_files", {"repo_root": str(indexed_repo)}
        )
    for f in result.data["files"]:
        assert f["file_type"] != "generated"


# ---------------------------------------------------------------------------
# get_recent_changes
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_recent_changes_callable(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_changes", {"repo_root": str(indexed_repo)}
        )
    assert not result.is_error
    assert "commits" in result.data
    assert "is_git_repo" in result.data


@pytest.mark.anyio
async def test_get_recent_changes_git_repo(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_changes", {"repo_root": str(indexed_repo)}
        )
    assert result.data["is_git_repo"] is True


# ---------------------------------------------------------------------------
# get_edit_suggestions
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_edit_suggestions_callable(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_edit_suggestions",
            {"repo_root": str(indexed_repo), "task": "main entry"},
        )
    assert not result.is_error
    data = result.data
    assert "task" in data
    assert "suggestions" in data
    assert isinstance(data["suggestions"], list)


@pytest.mark.anyio
async def test_get_edit_suggestions_with_limit(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_edit_suggestions",
            {"repo_root": str(indexed_repo), "task": "main entry", "limit": 3},
        )
    assert not result.is_error
    assert len(result.data["suggestions"]) <= 3


@pytest.mark.anyio
async def test_get_edit_suggestions_zero_overlap_empty(indexed_repo: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_edit_suggestions",
            {"repo_root": str(indexed_repo), "task": "xyzzy qwerty zork"},
        )
    assert not result.is_error
    assert result.data["suggestions"] == []


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tool_error_on_invalid_path() -> None:
    """Tools should surface errors cleanly for bad inputs."""
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_index_status",
            {"repo_root": "/nonexistent/totally/fake"},
            raise_on_error=False,
        )
    assert result.is_error


@pytest.mark.anyio
async def test_tool_error_on_missing_index(unindexed_repo: Path) -> None:
    """get_repo_overview should error when no index exists."""
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_repo_overview",
            {"repo_root": str(unindexed_repo)},
            raise_on_error=False,
        )
    assert result.is_error

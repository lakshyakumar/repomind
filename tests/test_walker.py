"""Tests for repomind.walker: traversal, skip rules, and file metadata."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repomind.models import FileRecord
from repomind.walker import (
    NOISY_FILENAMES,
    SKIP_DIRS,
    walk_repo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a small fixture repository."""
    # Normal source files
    (tmp_path / "README.md").write_text("# Repo\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')\n")
    (src / "utils.py").write_text("def helper(): pass\n")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_x(): pass\n")

    # Noisy files
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")
    (src / "bundle.min.js").write_text("(function(){})()")

    # Directories that must be skipped
    for skip in [".git", "node_modules", "__pycache__", ".venv", "dist"]:
        d = tmp_path / skip
        d.mkdir()
        (d / "should_not_appear.txt").write_text("skip me")

    # vendor/bundle — two-part skip
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    bundle = vendor / "bundle"
    bundle.mkdir()
    (bundle / "gem.rb").write_text("# gem")
    # vendor itself is not skipped, only vendor/bundle
    (vendor / "kept.rb").write_text("# kept")

    return tmp_path


# ---------------------------------------------------------------------------
# Basic traversal
# ---------------------------------------------------------------------------


def test_returns_file_records(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    assert all(isinstance(r, FileRecord) for r in records)


def test_paths_are_relative(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    for r in records:
        assert not os.path.isabs(r.path), f"Expected relative path, got: {r.path}"


def test_forward_slashes(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    for r in records:
        assert "\\" not in r.path, f"Backslash found in path: {r.path}"


def test_depth_root_level(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    root_level = [r for r in records if "/" not in r.path]
    for r in root_level:
        assert r.depth == 0, f"{r.path} should have depth 0"


def test_depth_one_level(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    src_files = [r for r in records if r.path.startswith("src/")]
    for r in src_files:
        assert r.depth == 1, f"{r.path} should have depth 1"


def test_size_bytes_populated(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    for r in records:
        assert r.size_bytes >= 0


def test_last_modified_ts_format(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    for r in records:
        if r.last_modified_ts is not None:
            # Must be parseable ISO 8601 with UTC offset
            assert "T" in r.last_modified_ts
            assert r.last_modified_ts.endswith("+00:00") or r.last_modified_ts.endswith("Z")


def test_abs_path_exists(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    for r in records:
        assert os.path.isfile(r.abs_path), f"abs_path does not exist: {r.abs_path}"


# ---------------------------------------------------------------------------
# Skip rules — directories
# ---------------------------------------------------------------------------


def _paths(records: list[FileRecord]) -> set[str]:
    return {r.path for r in records}


@pytest.mark.parametrize(
    "skip_dir",
    list(SKIP_DIRS),
)
def test_skip_dirs_are_excluded(repo: Path, skip_dir: str) -> None:
    target = repo / skip_dir
    if not target.exists():
        target.mkdir()
        (target / "skip_me.txt").write_text("skip")
    records = list(walk_repo(str(repo)))
    for r in records:
        assert not r.path.startswith(skip_dir + "/"), (
            f"File from skipped dir found: {r.path}"
        )
        assert r.path != skip_dir, f"File from skipped dir found: {r.path}"


def test_vendor_bundle_skipped(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    paths = _paths(records)
    assert not any("vendor/bundle" in p for p in paths), (
        f"vendor/bundle should be skipped, found: {[p for p in paths if 'vendor/bundle' in p]}"
    )


def test_vendor_itself_not_skipped(repo: Path) -> None:
    records = list(walk_repo(str(repo)))
    paths = _paths(records)
    assert "vendor/kept.rb" in paths, "vendor/kept.rb should NOT be skipped"


# ---------------------------------------------------------------------------
# Noisy file detection
# ---------------------------------------------------------------------------


def test_lockfile_is_noisy(repo: Path) -> None:
    records = {r.path: r for r in walk_repo(str(repo))}
    assert "package-lock.json" in records
    assert records["package-lock.json"].is_noisy


def test_image_is_noisy(repo: Path) -> None:
    records = {r.path: r for r in walk_repo(str(repo))}
    assert "logo.png" in records
    assert records["logo.png"].is_noisy


def test_minified_js_is_noisy(repo: Path) -> None:
    records = {r.path: r for r in walk_repo(str(repo))}
    assert "src/bundle.min.js" in records
    assert records["src/bundle.min.js"].is_noisy


def test_normal_source_not_noisy(repo: Path) -> None:
    records = {r.path: r for r in walk_repo(str(repo))}
    assert "src/main.py" in records
    assert not records["src/main.py"].is_noisy


def test_large_file_is_noisy(repo: Path) -> None:
    big = repo / "big.bin"
    big.write_bytes(b"\x00" * (1 * 1024 * 1024 + 1))
    records = {r.path: r for r in walk_repo(str(repo))}
    assert "big.bin" in records
    assert records["big.bin"].is_noisy


@pytest.mark.parametrize("lockfile", list(NOISY_FILENAMES))
def test_all_lockfiles_are_noisy(repo: Path, lockfile: str) -> None:
    # NOISY_FILENAMES stores lowercase names; use them directly as the filename.
    f = repo / lockfile
    f.write_text("lock content")
    records = {r.path.lower(): r for r in walk_repo(str(repo))}
    assert lockfile in records
    assert records[lockfile].is_noisy


@pytest.mark.parametrize("ext", [".png", ".jpg", ".gif", ".webp", ".mp4", ".map"])
def test_noisy_extensions(repo: Path, ext: str) -> None:
    f = repo / f"asset{ext}"
    f.write_bytes(b"\x00\x01")
    records = {r.path: r for r in walk_repo(str(repo))}
    assert f"asset{ext}" in records
    assert records[f"asset{ext}"].is_noisy


# ---------------------------------------------------------------------------
# max_depth enforcement
# ---------------------------------------------------------------------------


def test_max_depth_zero_yields_only_root_files(repo: Path) -> None:
    records = list(walk_repo(str(repo), max_depth=0))
    for r in records:
        assert r.depth == 0, f"Depth {r.depth} exceeds max_depth=0 for {r.path}"


def test_max_depth_one_yields_up_to_depth_one(repo: Path) -> None:
    records = list(walk_repo(str(repo), max_depth=1))
    for r in records:
        assert r.depth <= 1, f"Depth {r.depth} exceeds max_depth=1 for {r.path}"


def test_max_depth_none_yields_all_depths(repo: Path) -> None:
    # Create a deeply nested file.
    deep = repo / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x")
    records = list(walk_repo(str(repo), max_depth=None))
    paths = _paths(records)
    assert "a/b/c/deep.py" in paths


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_directory(tmp_path: Path) -> None:
    records = list(walk_repo(str(tmp_path)))
    assert records == []


def test_single_file_repo(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi")
    records = list(walk_repo(str(tmp_path)))
    assert len(records) == 1
    assert records[0].path == "hello.txt"
    assert records[0].depth == 0

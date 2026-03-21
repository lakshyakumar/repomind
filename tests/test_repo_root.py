"""Tests for repo root path resolution."""

import os
from pathlib import Path

import pytest

from repomind.repo import resolve_repo_root


def test_empty_path_defaults_to_cwd():
    result = resolve_repo_root("")
    assert result == str(Path(os.getcwd()).resolve())


def test_no_arg_defaults_to_cwd():
    result = resolve_repo_root()
    assert result == str(Path(os.getcwd()).resolve())


def test_valid_directory_resolves(tmp_path):
    result = resolve_repo_root(str(tmp_path))
    assert result == str(tmp_path.resolve())


def test_returns_absolute_path(tmp_path):
    result = resolve_repo_root(str(tmp_path))
    assert Path(result).is_absolute()


def test_nonexistent_path_raises(tmp_path):
    fake = tmp_path / "does_not_exist"
    with pytest.raises(ValueError, match="does not exist"):
        resolve_repo_root(str(fake))


def test_file_path_raises(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hello")
    with pytest.raises(ValueError, match="not a directory"):
        resolve_repo_root(str(f))


def test_dotdot_traversal_resolves_to_real_path(tmp_path):
    # ../.. style paths should resolve cleanly to their real location
    # The resolved path must be a directory that exists
    result = resolve_repo_root(str(tmp_path / ".." ))
    assert Path(result).is_dir()
    assert Path(result).is_absolute()

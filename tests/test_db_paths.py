"""Tests for db path resolution and storage directory management."""

import os
from pathlib import Path

import pytest

from repomind.db import get_db_path, get_tmp_db_path, repo_hash


def test_repo_hash_is_stable():
    assert repo_hash("/some/repo") == repo_hash("/some/repo")


def test_repo_hash_differs_for_different_paths():
    assert repo_hash("/repo/a") != repo_hash("/repo/b")


def test_repo_hash_normalises_trailing_slash():
    assert repo_hash("/some/repo") == repo_hash("/some/repo/")


def test_repo_hash_is_hex_string():
    h = repo_hash("/some/repo")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_get_db_path_returns_path_under_indexes(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    db_path = get_db_path("/some/repo")
    assert db_path.parent == tmp_path / "indexes"
    assert db_path.suffix == ".sqlite3"


def test_get_db_path_creates_storage_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    get_db_path("/some/repo")
    assert (tmp_path / "indexes").is_dir()
    assert (tmp_path / "tmp").is_dir()


def test_get_db_path_is_stable_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    assert get_db_path("/some/repo") == get_db_path("/some/repo")


def test_get_db_path_differs_for_different_repos(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    assert get_db_path("/repo/a") != get_db_path("/repo/b")


def test_get_tmp_db_path_returns_path_under_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    tmp_db = get_tmp_db_path("/some/repo")
    assert tmp_db.parent == tmp_path / "tmp"
    assert tmp_db.name.endswith(".sqlite3.tmp")


def test_get_tmp_db_path_and_db_path_share_same_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMIND_STORAGE_ROOT", str(tmp_path))
    db = get_db_path("/some/repo")
    tmp = get_tmp_db_path("/some/repo")
    # Both filenames should be rooted in the same repo hash
    assert db.stem == tmp.name.replace(".sqlite3.tmp", "")

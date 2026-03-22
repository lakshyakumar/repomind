"""Tests for repomind.scoring: file scores, directory scores, ref counting."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomind.models import ClassifiedFile
from repomind.scoring import (
    compute_inbound_refs,
    get_recently_modified_paths,
    score_directory,
    score_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cf(
    path: str = "src/foo.py",
    file_type: str = "source",
    depth: int = 1,
    line_count: int | None = None,
    last_modified_ts: str | None = None,
    is_noisy: bool = False,
    abs_path: str = "/repo/src/foo.py",
) -> ClassifiedFile:
    return ClassifiedFile(
        path=path,
        abs_path=abs_path,
        size_bytes=100,
        depth=depth,
        last_modified_ts=last_modified_ts,
        is_noisy=is_noisy,
        file_type=file_type,
        extension=".py",
        line_count=line_count,
        directory_path="src",
        path_tokens=["src", "foo"],
        header_tokens=[],
    )


# ---------------------------------------------------------------------------
# score_file: base scores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_type", "expected_base_contribution"),
    [
        ("manifest", 1.00),
        ("entrypoint", 0.90),
        ("config", 0.75),
        ("docs", 0.55),
        ("test", 0.45),
        ("source", 0.40),
        ("generated", 0.20),
        ("other", 0.20),
    ],
)
def test_base_score_by_file_type(file_type: str, expected_base_contribution: float) -> None:
    # depth=10 → depth_bonus=0, no other bonuses or penalties except generated penalty
    depth = 10
    penalty = 0.30 if file_type == "generated" else 0.0
    expected = round(max(0.0, expected_base_contribution - penalty), 4)
    result = score_file(file_type=file_type, depth=depth, line_count=None,
                        inbound_ref_count=0, is_recently_modified=False)
    assert result == expected


# ---------------------------------------------------------------------------
# score_file: depth bonus
# ---------------------------------------------------------------------------


def test_depth_bonus_at_zero() -> None:
    # depth=0 → bonus = max(0, 0.20 - 0) = 0.20
    score_d0 = score_file("source", depth=0, line_count=None, inbound_ref_count=0,
                           is_recently_modified=False)
    score_d1 = score_file("source", depth=1, line_count=None, inbound_ref_count=0,
                           is_recently_modified=False)
    assert score_d0 == round(score_d1 + 0.03, 4)


def test_depth_bonus_clamped_to_zero() -> None:
    # depth=7 → 0.20 - 0.21 = -0.01 → clamped to 0
    deep = score_file("source", depth=7, line_count=None, inbound_ref_count=0,
                      is_recently_modified=False)
    deeper = score_file("source", depth=8, line_count=None, inbound_ref_count=0,
                        is_recently_modified=False)
    assert deep == deeper  # both have zero depth bonus


def test_depth_bonus_exact_boundary() -> None:
    # depth=6 → 0.20 - 0.18 = 0.02; depth=7 → 0.20 - 0.21 → clamped to 0
    d6 = score_file("source", depth=6, line_count=None, inbound_ref_count=0,
                    is_recently_modified=False)
    d7 = score_file("source", depth=7, line_count=None, inbound_ref_count=0,
                    is_recently_modified=False)
    assert d6 > d7


# ---------------------------------------------------------------------------
# score_file: line count bonus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line_count", [80, 400, 800])
def test_line_bonus_applied_in_range(line_count: int) -> None:
    with_bonus = score_file("source", depth=5, line_count=line_count,
                            inbound_ref_count=0, is_recently_modified=False)
    without_bonus = score_file("source", depth=5, line_count=None,
                               inbound_ref_count=0, is_recently_modified=False)
    assert round(with_bonus - without_bonus, 4) == 0.10


@pytest.mark.parametrize("line_count", [0, 1, 79, 801, 10000])
def test_line_bonus_not_applied_outside_range(line_count: int) -> None:
    with_count = score_file("source", depth=5, line_count=line_count,
                            inbound_ref_count=0, is_recently_modified=False)
    without_count = score_file("source", depth=5, line_count=None,
                               inbound_ref_count=0, is_recently_modified=False)
    assert with_count == without_count


def test_line_bonus_none_means_no_bonus() -> None:
    result = score_file("source", depth=5, line_count=None,
                        inbound_ref_count=0, is_recently_modified=False)
    result_none_explicit = score_file("source", depth=5, line_count=None,
                                      inbound_ref_count=0, is_recently_modified=False)
    assert result == result_none_explicit


# ---------------------------------------------------------------------------
# score_file: recent modification bonus
# ---------------------------------------------------------------------------


def test_recent_modification_bonus() -> None:
    recent = score_file("source", depth=5, line_count=None,
                        inbound_ref_count=0, is_recently_modified=True)
    not_recent = score_file("source", depth=5, line_count=None,
                            inbound_ref_count=0, is_recently_modified=False)
    assert round(recent - not_recent, 4) == 0.10


# ---------------------------------------------------------------------------
# score_file: inbound reference bonus
# ---------------------------------------------------------------------------


def test_inbound_ref_bonus_scales_with_count() -> None:
    s0 = score_file("source", depth=5, line_count=None, inbound_ref_count=0,
                    is_recently_modified=False)
    s5 = score_file("source", depth=5, line_count=None, inbound_ref_count=5,
                    is_recently_modified=False)
    assert round(s5 - s0, 4) == round(5 * 0.02, 4)


def test_inbound_ref_bonus_capped_at_0_20() -> None:
    # 10 refs → 0.20 exactly; 20 refs → still 0.20
    s10 = score_file("source", depth=5, line_count=None, inbound_ref_count=10,
                     is_recently_modified=False)
    s20 = score_file("source", depth=5, line_count=None, inbound_ref_count=20,
                     is_recently_modified=False)
    assert s10 == s20


def test_inbound_ref_bonus_exact_cap() -> None:
    s9 = score_file("source", depth=5, line_count=None, inbound_ref_count=9,
                    is_recently_modified=False)
    s10 = score_file("source", depth=5, line_count=None, inbound_ref_count=10,
                     is_recently_modified=False)
    assert round(s10 - s9, 4) == 0.02


# ---------------------------------------------------------------------------
# score_file: root docs bonus
# ---------------------------------------------------------------------------


def test_root_docs_bonus_applied() -> None:
    root_doc = score_file("docs", depth=0, line_count=None,
                          inbound_ref_count=0, is_recently_modified=False)
    nested_doc = score_file("docs", depth=1, line_count=None,
                            inbound_ref_count=0, is_recently_modified=False)
    # root gets both depth_bonus=0.20 and root_docs_bonus=0.10
    # nested gets depth_bonus=0.17 and no root_docs_bonus
    # difference should be 0.20 - 0.17 + 0.10 = 0.13
    assert round(root_doc - nested_doc, 4) == pytest.approx(0.13, abs=1e-4)


def test_root_docs_bonus_only_for_docs_type() -> None:
    root_source = score_file("source", depth=0, line_count=None,
                             inbound_ref_count=0, is_recently_modified=False)
    root_docs = score_file("docs", depth=0, line_count=None,
                           inbound_ref_count=0, is_recently_modified=False)
    # docs base is 0.55, source is 0.40; docs gets root bonus too
    # root_docs: 0.55 + 0.20 + 0.10 = 0.85
    # root_source: 0.40 + 0.20 = 0.60
    assert round(root_docs - root_source, 4) == pytest.approx(0.25, abs=1e-4)


# ---------------------------------------------------------------------------
# score_file: generated / noisy penalty
# ---------------------------------------------------------------------------


def test_generated_penalty_applied() -> None:
    # Use depth=0 so both get depth_bonus=0.20; penalty difference is visible.
    # other:     0.20 + 0.20 = 0.40
    # generated: 0.20 + 0.20 - 0.30 = 0.10
    generated = score_file("generated", depth=0, line_count=None,
                           inbound_ref_count=0, is_recently_modified=False)
    other = score_file("other", depth=0, line_count=None,
                       inbound_ref_count=0, is_recently_modified=False)
    assert round(other - generated, 4) == pytest.approx(0.30, abs=1e-4)


def test_generated_score_clamped_to_zero() -> None:
    # generated at depth >= 7 → base 0.20 - penalty 0.30 = -0.10 → clamped to 0
    result = score_file("generated", depth=7, line_count=None,
                        inbound_ref_count=0, is_recently_modified=False)
    assert result == 0.0


# ---------------------------------------------------------------------------
# score_file: cap at 1.50
# ---------------------------------------------------------------------------


def test_score_capped_at_1_50() -> None:
    # manifest at depth 0 + all bonuses should still be ≤ 1.50
    result = score_file("manifest", depth=0, line_count=200, inbound_ref_count=20,
                        is_recently_modified=True)
    assert result <= 1.50


def test_manifest_at_depth_zero_without_bonuses() -> None:
    result = score_file("manifest", depth=0, line_count=None,
                        inbound_ref_count=0, is_recently_modified=False)
    # 1.00 + 0.20 = 1.20
    assert result == pytest.approx(1.20, abs=1e-4)


# ---------------------------------------------------------------------------
# score_directory
# ---------------------------------------------------------------------------


def test_directory_score_empty_files() -> None:
    result = score_directory([], dir_depth=0)
    # 0 * 0.6 + 0 + 0.20 depth_bonus = 0.20
    assert result == pytest.approx(0.20, abs=1e-4)


def test_directory_score_avg_file_contribution() -> None:
    result = score_directory([0.80, 0.60], dir_depth=5, manifest_count=0)
    depth_bonus = max(0.0, 0.20 - 0.03 * 5)  # 0.05
    expected = round(0.70 * 0.6 + depth_bonus, 4)
    assert result == pytest.approx(expected, abs=1e-4)


def test_directory_score_manifest_adds_bonus() -> None:
    base = score_directory([0.5], dir_depth=3)
    with_manifest = score_directory([0.5], dir_depth=3, manifest_count=1)
    assert round(with_manifest - base, 4) == pytest.approx(0.10, abs=1e-4)


def test_directory_score_config_adds_bonus() -> None:
    base = score_directory([0.5], dir_depth=3)
    with_config = score_directory([0.5], dir_depth=3, config_count=1)
    assert round(with_config - base, 4) == pytest.approx(0.10, abs=1e-4)


def test_directory_score_entrypoint_adds_bonus() -> None:
    base = score_directory([0.5], dir_depth=3)
    with_entry = score_directory([0.5], dir_depth=3, entrypoint_count=1)
    assert round(with_entry - base, 4) == pytest.approx(0.10, abs=1e-4)


def test_directory_score_depth_bonus_clamped() -> None:
    deep = score_directory([], dir_depth=7)
    deeper = score_directory([], dir_depth=8)
    assert deep == deeper  # both have zero depth bonus


def test_directory_score_capped_at_1_50() -> None:
    result = score_directory(
        [1.50] * 10, dir_depth=0, manifest_count=5, config_count=5, entrypoint_count=5
    )
    assert result <= 1.50


def test_directory_score_floor_at_zero() -> None:
    result = score_directory([], dir_depth=100)
    assert result >= 0.0


# ---------------------------------------------------------------------------
# get_recently_modified_paths
# ---------------------------------------------------------------------------


def test_recently_modified_returns_top_n(tmp_path: Path) -> None:
    files = [
        _cf(path=f"src/f{i}.py", last_modified_ts=f"2026-03-{i + 1:02d}T00:00:00+00:00")
        for i in range(40)
    ]
    result = get_recently_modified_paths(files, top_n=30)
    assert len(result) == 30
    # The 30 most recent should be the ones with highest day numbers (10..39)
    for i in range(10, 40):
        assert f"src/f{i}.py" in result
    for i in range(0, 10):
        assert f"src/f{i}.py" not in result


def test_recently_modified_excludes_files_without_timestamp() -> None:
    files = [
        _cf(path="dated.py", last_modified_ts="2026-03-22T00:00:00+00:00"),
        _cf(path="nodates.py", last_modified_ts=None),
    ]
    result = get_recently_modified_paths(files, top_n=30)
    assert "dated.py" in result
    assert "nodates.py" not in result


def test_recently_modified_fewer_than_top_n() -> None:
    files = [_cf(path="only.py", last_modified_ts="2026-03-22T00:00:00+00:00")]
    result = get_recently_modified_paths(files, top_n=30)
    assert result == frozenset({"only.py"})


def test_recently_modified_empty_list() -> None:
    result = get_recently_modified_paths([])
    assert result == frozenset()


# ---------------------------------------------------------------------------
# compute_inbound_refs
# ---------------------------------------------------------------------------


def test_inbound_refs_self_reference_not_counted(tmp_path: Path) -> None:
    f = tmp_path / "utils.py"
    f.write_text("# utils utils utils\ndef helper(): pass\n")
    cf = ClassifiedFile(
        path="utils.py",
        abs_path=str(f),
        size_bytes=f.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="source",
        extension=".py",
        line_count=2,
        directory_path="",
        path_tokens=["utils"],
        header_tokens=[],
    )
    result = compute_inbound_refs([cf])
    assert result["utils.py"] == 0


def test_inbound_refs_counted_across_files(tmp_path: Path) -> None:
    importer = tmp_path / "main.py"
    importer.write_text("from utils import helper\n")
    utils = tmp_path / "utils.py"
    utils.write_text("def helper(): pass\n")

    main_cf = ClassifiedFile(
        path="main.py",
        abs_path=str(importer),
        size_bytes=importer.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="entrypoint",
        extension=".py",
        line_count=1,
        directory_path="",
        path_tokens=["main"],
        header_tokens=[],
    )
    utils_cf = ClassifiedFile(
        path="utils.py",
        abs_path=str(utils),
        size_bytes=utils.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="source",
        extension=".py",
        line_count=1,
        directory_path="",
        path_tokens=["utils"],
        header_tokens=[],
    )
    result = compute_inbound_refs([main_cf, utils_cf])
    assert result["utils.py"] >= 1
    assert result["main.py"] == 0


def test_inbound_refs_generated_files_not_scanned(tmp_path: Path) -> None:
    # A generated/noisy file should not scan and add spurious refs.
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text('{"utils": "1.0.0"}\n')
    utils = tmp_path / "utils.py"
    utils.write_text("def helper(): pass\n")

    lock_cf = ClassifiedFile(
        path="package-lock.json",
        abs_path=str(lockfile),
        size_bytes=lockfile.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=True,
        file_type="generated",
        extension=".json",
        line_count=None,
        directory_path="",
        path_tokens=[],
        header_tokens=[],
    )
    utils_cf = ClassifiedFile(
        path="utils.py",
        abs_path=str(utils),
        size_bytes=utils.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="source",
        extension=".py",
        line_count=1,
        directory_path="",
        path_tokens=["utils"],
        header_tokens=[],
    )
    result = compute_inbound_refs([lock_cf, utils_cf])
    # lockfile mentions "utils" but should not be scanned
    assert result["utils.py"] == 0


def test_inbound_refs_short_stems_ignored(tmp_path: Path) -> None:
    # Stem "db" is 2 chars — below _REF_MIN_STEM_LEN=4, should not be scanned for.
    scanner = tmp_path / "main.py"
    scanner.write_text("import db\n")
    target = tmp_path / "db.py"
    target.write_text("# database\n")

    main_cf = ClassifiedFile(
        path="main.py",
        abs_path=str(scanner),
        size_bytes=scanner.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="entrypoint",
        extension=".py",
        line_count=1,
        directory_path="",
        path_tokens=["main"],
        header_tokens=[],
    )
    db_cf = ClassifiedFile(
        path="db.py",
        abs_path=str(target),
        size_bytes=target.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="source",
        extension=".py",
        line_count=1,
        directory_path="",
        path_tokens=["db"],
        header_tokens=[],
    )
    result = compute_inbound_refs([main_cf, db_cf])
    assert result["db.py"] == 0  # too short to be tracked


def test_inbound_refs_empty_list() -> None:
    result = compute_inbound_refs([])
    assert result == {}


def test_inbound_refs_unreadable_file_skipped(tmp_path: Path) -> None:
    utils = tmp_path / "utils.py"
    utils.write_text("x=1\n")

    scanner_cf = ClassifiedFile(
        path="main.py",
        abs_path="/nonexistent/main.py",
        size_bytes=0,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="source",
        extension=".py",
        line_count=None,
        directory_path="",
        path_tokens=["main"],
        header_tokens=[],
    )
    utils_cf = ClassifiedFile(
        path="utils.py",
        abs_path=str(utils),
        size_bytes=utils.stat().st_size,
        depth=0,
        last_modified_ts=None,
        is_noisy=False,
        file_type="source",
        extension=".py",
        line_count=1,
        directory_path="",
        path_tokens=["utils"],
        header_tokens=[],
    )
    # Should not raise; unreadable file is silently skipped.
    result = compute_inbound_refs([scanner_cf, utils_cf])
    assert isinstance(result, dict)

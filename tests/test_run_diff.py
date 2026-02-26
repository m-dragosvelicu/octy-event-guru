"""Unit tests for compute_run_diff -- pure logic, no external deps."""
from app.domain.run_diff import compute_run_diff


def test_identical_runs_zero_leaks_zero_new() -> None:
    candidates = ["a", "b", "c"]
    inserted = ["a", "b", "c"]

    diff = compute_run_diff(
        r1_candidates=candidates,
        r1_inserted=inserted,
        r2_candidates=candidates,
        r2_inserted=[],
    )

    assert diff.run1_candidate_count == 3
    assert diff.run2_inserted_count == 0
    assert diff.duplicate_leaks_in_run2 == []
    assert diff.new_discovery_in_run2 == []
    assert sorted(diff.shared_candidates) == ["a", "b", "c"]
    assert diff.new_candidates_in_run2 == []


def test_partial_overlap_detects_leak() -> None:
    diff = compute_run_diff(
        r1_candidates=["a", "b", "c"],
        r1_inserted=["a", "b"],
        r2_candidates=["a", "b", "c"],
        r2_inserted=["a"],  # "a" was already inserted in run1 -> leak
    )

    assert diff.duplicate_leaks_in_run2 == ["a"]
    assert diff.new_discovery_in_run2 == []


def test_full_new_discovery() -> None:
    diff = compute_run_diff(
        r1_candidates=["a", "b"],
        r1_inserted=["a", "b"],
        r2_candidates=["a", "b", "x", "y"],
        r2_inserted=["x", "y"],  # never in run1 candidates
    )

    assert diff.duplicate_leaks_in_run2 == []
    assert sorted(diff.new_discovery_in_run2) == ["x", "y"]
    assert sorted(diff.new_candidates_in_run2) == ["x", "y"]


def test_mixed_leak_and_discovery() -> None:
    diff = compute_run_diff(
        r1_candidates=["a", "b", "c"],
        r1_inserted=["a", "b"],
        r2_candidates=["a", "b", "c", "d"],
        r2_inserted=["a", "d"],  # "a" is leak, "d" is discovery
    )

    assert diff.duplicate_leaks_in_run2 == ["a"]
    assert diff.new_discovery_in_run2 == ["d"]


def test_empty_runs() -> None:
    diff = compute_run_diff(
        r1_candidates=[],
        r1_inserted=[],
        r2_candidates=[],
        r2_inserted=[],
    )

    assert diff.run1_candidate_count == 0
    assert diff.run2_candidate_count == 0
    assert diff.duplicate_leaks_in_run2 == []
    assert diff.new_discovery_in_run2 == []


def test_run2_inserts_from_run1_candidates_but_not_inserted_is_not_leak() -> None:
    """If run1 had candidate "c" but did NOT insert it, and run2 inserts "c",
    that is NOT a leak -- it could be a legitimate insert of something
    previously skipped (past event that became future, etc.)."""
    diff = compute_run_diff(
        r1_candidates=["a", "b", "c"],
        r1_inserted=["a", "b"],
        r2_candidates=["a", "b", "c"],
        r2_inserted=["c"],
    )

    assert diff.duplicate_leaks_in_run2 == []
    # "c" was a candidate in run1 so it's NOT new_discovery either
    assert diff.new_discovery_in_run2 == []

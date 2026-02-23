from __future__ import annotations

from pydantic import BaseModel, Field


class RunDiff(BaseModel):
    run1_candidate_count: int
    run1_inserted_count: int
    run2_candidate_count: int
    run2_inserted_count: int
    new_candidates_in_run2: list[str] = Field(default_factory=list)
    shared_candidates: list[str] = Field(default_factory=list)
    duplicate_leaks_in_run2: list[str] = Field(default_factory=list)
    new_discovery_in_run2: list[str] = Field(default_factory=list)


def compute_run_diff(
    r1_candidates: list[str],
    r1_inserted: list[str],
    r2_candidates: list[str],
    r2_inserted: list[str],
) -> RunDiff:
    """Compare two ingest runs to classify run2 inserts as leaks vs new discovery.

    - duplicate_leaks_in_run2: IDs inserted in BOTH runs (dedupe bug)
    - new_discovery_in_run2: IDs inserted in run2 that were never candidates in run1
    """
    r1_cand_set = set(r1_candidates)
    r1_ins_set = set(r1_inserted)
    r2_cand_set = set(r2_candidates)
    r2_ins_set = set(r2_inserted)

    shared = sorted(r1_cand_set & r2_cand_set)
    new_cands = sorted(r2_cand_set - r1_cand_set)
    leaks = sorted(r1_ins_set & r2_ins_set)
    new_disc = sorted(r2_ins_set - r1_cand_set)

    return RunDiff(
        run1_candidate_count=len(r1_candidates),
        run1_inserted_count=len(r1_inserted),
        run2_candidate_count=len(r2_candidates),
        run2_inserted_count=len(r2_inserted),
        new_candidates_in_run2=new_cands,
        shared_candidates=shared,
        duplicate_leaks_in_run2=leaks,
        new_discovery_in_run2=new_disc,
    )

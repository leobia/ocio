"""Test della fusione di graduatorie."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ocio.fusion import FusionError, RrfFusion, WeightedScoreFusion
from ocio.retrieval import (
    Candidate,
    ChunkReference,
    RankedCandidate,
    Ranking,
    RetrievalRun,
    read_trace,
    write_trace,
)


def _candidate(identifier: str, content: str | None = None) -> Candidate:
    return Candidate(
        reference=ChunkReference("doc", identifier),
        content=content or identifier,
        source_partitions=(),
    )


def _ranking(stage: str, *items: tuple[str, float]) -> Ranking:
    return Ranking(
        stage,
        tuple(
            RankedCandidate(_candidate(identifier), score, rank)
            for rank, (identifier, score) in enumerate(items, start=1)
        ),
        {},
        0.0,
    )


def test_rrf_deduplicates_and_records_each_origin() -> None:
    lexical = _ranking("lexical", ("a", 8.0), ("b", 4.0))
    dense = _ranking("dense", ("b", 0.9), ("c", 0.8))

    fused = RrfFusion(rank_constant=10).fuse((lexical, dense), limit=2)

    assert [item.candidate.reference.chunk_identifier for item in fused.candidates] == [
        "b",
        "a",
    ]
    assert fused.candidates[0].score == pytest.approx(1 / 12 + 1 / 11)
    assert [(item.stage, item.rank) for item in fused.candidates[0].contributions] == [
        ("lexical", 2),
        ("dense", 1),
    ]


def test_weighted_fusion_normalizes_opposite_score_directions() -> None:
    bm25 = _ranking("bm25", ("a", -10.0), ("b", -1.0))
    dense = _ranking("dense", ("b", 0.9), ("a", 0.1))

    fused = WeightedScoreFusion((0.75, 0.25)).fuse((bm25, dense), limit=2)

    assert [item.candidate.reference.chunk_identifier for item in fused.candidates] == [
        "a",
        "b",
    ]
    assert [item.score for item in fused.candidates] == pytest.approx([0.75, 0.25])
    assert fused.configuration["normalized_weights"] == [0.75, 0.25]


def test_ties_use_best_source_rank_then_canonical_identity() -> None:
    first = _ranking("one", ("b", 1.0), ("c", 1.0))
    second = _ranking("two", ("a", 1.0), ("c", 1.0))

    fused = WeightedScoreFusion((1.0, 1.0)).fuse((first, second), limit=3)

    assert [item.candidate.reference.chunk_identifier for item in fused.candidates] == [
        "c",
        "a",
        "b",
    ]


def test_empty_rankings_and_invalid_inputs_are_handled() -> None:
    empty = Ranking("empty", (), {}, 0.0)

    assert RrfFusion().fuse((empty,), 5).candidates == ()
    with pytest.raises(FusionError, match="limite"):
        RrfFusion().fuse((empty,), 0)
    with pytest.raises(FusionError, match="peso per ogni"):
        WeightedScoreFusion((1.0,)).fuse((empty, empty), 5)
    with pytest.raises(FusionError, match="positiva"):
        RrfFusion(0)


def test_duplicate_and_conflicting_candidates_are_rejected() -> None:
    duplicate = _ranking("duplicate", ("a", 2.0), ("a", 1.0))
    original = _ranking("one", ("a", 1.0))
    changed_item = replace(
        original.candidates[0], candidate=_candidate("a", "contenuto diverso")
    )
    changed = Ranking("two", (changed_item,), {}, 0.0)

    with pytest.raises(FusionError, match="duplicato"):
        RrfFusion().fuse((duplicate,), 5)
    with pytest.raises(FusionError, match="discordante"):
        RrfFusion().fuse((original, changed), 5)


def test_contributions_survive_trace_round_trip(tmp_path: Path) -> None:
    fused = RrfFusion().fuse((_ranking("source", ("a", 1.0)),), 1)
    run = RetrievalRun("run", "case", "query", "f" * 64, (fused,))
    output = tmp_path / "trace.jsonl"

    write_trace((run,), output)

    assert read_trace(output) == (run,)

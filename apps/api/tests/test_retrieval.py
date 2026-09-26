"""Provider-independent retrieval contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
    RetrievalRun,
    RetrievalTraceError,
    read_trace,
    write_trace,
)


def candidate(identifier: str = "structural/art-1/1") -> Candidate:
    return Candidate(
        reference=ChunkReference("d-lgs-81-2008", identifier),
        content="Documento: D.Lgs. 81/2008\nIl datore di lavoro valuta i rischi.",
        source_partitions=(
            PartitionReference("d-lgs-81-2008", "documento/articolo-17"),
        ),
        parent=ChunkReference("d-lgs-81-2008", "parent/documento/articolo-17"),
    )


def test_score_and_rank_remain_distinct_across_rankings() -> None:
    shared = candidate()
    lexical = Ranking(
        stage="postgres-fts",
        candidates=(RankedCandidate(shared, score=0.42, rank=1),),
        configuration={"dictionary": "italian"},
        latency_ms=1.5,
    )
    reranked = Ranking(
        stage="reranker",
        candidates=(RankedCandidate(shared, score=-2.1, rank=1),),
        configuration={"model": "example"},
        latency_ms=4.0,
    )

    assert lexical.candidates[0].candidate is shared
    assert lexical.candidates[0].score == 0.42
    assert reranked.candidates[0].score == -2.1
    assert lexical.candidates[0].rank == reranked.candidates[0].rank == 1


def test_trace_round_trip_is_lossless(tmp_path: Path) -> None:
    run = RetrievalRun(
        run_id="run-1",
        case_id="silver-0001",
        query="Chi deve valutare i rischi?",
        chunk_set_fingerprint="a" * 64,
        rankings=(
            Ranking(
                stage="postgres-fts",
                candidates=(RankedCandidate(candidate(), score=0.42, rank=1),),
                configuration={"dictionary": "italian", "weights": [1.0, 0.5]},
                latency_ms=1.5,
            ),
        ),
    )
    output = tmp_path / "trace.jsonl"

    write_trace([run], output)

    assert read_trace(output) == (run,)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 1


def test_ranking_requires_contiguous_one_based_ranks() -> None:
    with pytest.raises(ValueError, match="contiguous 1-based rank"):
        Ranking(
            stage="dense",
            candidates=(RankedCandidate(candidate(), score=0.8, rank=2),),
            configuration={},
            latency_ms=1.0,
        )


def test_invalid_trace_identifies_the_line(tmp_path: Path) -> None:
    output = tmp_path / "trace.jsonl"
    output.write_text(json.dumps({"schema_version": 1}) + "\n", encoding="utf-8")

    with pytest.raises(RetrievalTraceError, match="line 1"):
        read_trace(output)

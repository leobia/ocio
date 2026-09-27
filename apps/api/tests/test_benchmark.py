"""Test del runner e delle metriche di benchmark."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from ocio.benchmark import (
    BenchmarkError,
    EvaluationCase,
    calculate_metrics,
    load_configuration,
)
from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
)


def _ranking(*partitions: tuple[PartitionReference, ...]) -> Ranking:
    return Ranking(
        stage="test",
        candidates=tuple(
            RankedCandidate(
                Candidate(
                    ChunkReference("doc", f"chunk-{rank}"),
                    "testo",
                    sources,
                ),
                score=1.0 / rank,
                rank=rank,
            )
            for rank, sources in enumerate(partitions, start=1)
        ),
        configuration={},
        latency_ms=0,
    )


def test_metrics_reward_each_evidence_only_once() -> None:
    first = PartitionReference("doc", "art-1")
    second = PartitionReference("doc", "art-2")
    case = EvaluationCase("case-1", "domanda", True, frozenset({first, second}))
    ranking = _ranking((first,), (first,), (second,))

    metrics = calculate_metrics(
        case,
        ranking,
        top_k=3,
        evidence_pool=(frozenset({first}), frozenset({second})),
    )

    assert metrics.evidence_recall_at_k == 1
    assert metrics.mrr_at_k == 1
    assert metrics.alpha_ndcg_at_k == pytest.approx(
        (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    )


def test_metrics_use_real_chunk_coverage_for_the_ideal_ranking() -> None:
    first = PartitionReference("doc", "art-1")
    second = PartitionReference("doc", "art-2")
    case = EvaluationCase("case-1", "domanda", True, frozenset({first, second}))
    ranking = _ranking((first, second),)

    metrics = calculate_metrics(
        case,
        ranking,
        top_k=2,
        evidence_pool=(frozenset({first, second}),),
    )

    assert metrics.alpha_ndcg_at_k == 1


def test_configuration_paths_are_relative_to_the_yaml(
    tmp_path: Path,
) -> None:
    source = tmp_path / "benchmark.yaml"
    source.write_text(
        """schema_version: 1
dataset: silver.jsonl
chunk_set_fingerprint: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
top_k: 10
output_directory: results
configurations:
  - name: fts
    retriever: postgres_fts
  - name: bm25
    retriever: bm25
""",
        encoding="utf-8",
    )

    configuration = load_configuration(source)

    assert configuration.dataset == tmp_path / "silver.jsonl"
    assert configuration.output_directory == tmp_path / "results"
    assert [item.name for item in configuration.configurations] == ["fts", "bm25"]


def test_configuration_rejects_duplicate_names(tmp_path: Path) -> None:
    source = tmp_path / "benchmark.yaml"
    source.write_text(
        """schema_version: 1
dataset: silver.jsonl
chunk_set_fingerprint: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
top_k: 10
output_directory: results
configurations:
  - name: lexical
    retriever: postgres_fts
  - name: lexical
    retriever: bm25
""",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkError, match="univoci"):
        load_configuration(source)

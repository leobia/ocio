"""Test del runner e delle metriche di benchmark."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from ocio.benchmark import (
    BenchmarkConfiguration,
    BenchmarkError,
    EvaluationCase,
    RerankerConfiguration,
    RetrieverConfiguration,
    _decision,
    calculate_metrics,
    execute_benchmark,
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


def test_paired_benchmark_retrieves_once_and_keeps_baseline_on_rerank_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = PartitionReference("doc", "art-1")
    cases = (
        EvaluationCase("ok", "query ok", True, frozenset({evidence})),
        EvaluationCase("failed", "query failed", True, frozenset({evidence})),
    )
    monkeypatch.setattr(
        "ocio.benchmark._load_cases", lambda _dataset, _connection: (cases, "f" * 64)
    )
    monkeypatch.setattr(
        "ocio.benchmark._load_evidence_pool",
        lambda _connection, _fingerprint: (frozenset({evidence}),),
    )

    class FakeRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def retrieve(self, query: str, limit: int) -> Ranking:
            self.calls.append((query, limit))
            return _ranking((evidence,), (), ())

    class FakeReranker:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Ranking, int]] = []

        def rerank(self, query: str, ranking: Ranking, limit: int) -> Ranking:
            self.calls.append((query, ranking, limit))
            if query == "query failed":
                raise RuntimeError("provider down")
            return Ranking(
                "cohere-rerank-v4.0-pro",
                tuple(
                    RankedCandidate(item.candidate, item.score, rank)
                    for rank, item in enumerate(
                        reversed(ranking.candidates[:2]), start=1
                    )
                ),
                {
                    "provider": "cohere",
                    "model": "rerank-v4.0-pro",
                    "input_candidate_count": len(ranking.candidates),
                    "output_candidate_count": 2,
                    "billed_search_units": 1.0,
                },
                7.0,
            )

    retriever = FakeRetriever()
    reranker = FakeReranker()
    configuration = BenchmarkConfiguration(
        dataset=tmp_path / "silver.jsonl",
        chunk_set_fingerprint="a" * 64,
        top_k=10,
        candidate_k=20,
        output_directory=tmp_path / "results",
        configurations=(RetrieverConfiguration("bm25", "bm25"),),
        reranker=RerankerConfiguration(),
    )

    artifacts = execute_benchmark(
        configuration,
        object(),  # type: ignore[arg-type]
        retriever_factory=lambda *_args: retriever,
        reranker=reranker,
    )

    assert retriever.calls == [("query ok", 20), ("query failed", 20)]
    assert [(query, limit) for query, _ranking, limit in reranker.calls] == [
        ("query ok", 10),
        ("query failed", 10),
    ]
    assert all(call[1] is not None for call in reranker.calls)
    report: dict[str, Any] = json.loads(artifacts.report.read_text(encoding="utf-8"))
    assert report["decision"] == "inconclusive"
    assert report["rerank"]["successes"] == 1
    assert report["rerank"]["failures"] == 1
    assert report["rerank"]["billed_search_units"] == 1.0
    assert report["rerank"]["estimated_cost_usd"] == 0.0025
    assert report["source"]["recall_at_candidate_k"] == 1.0
    assert len(artifacts.trace.read_text(encoding="utf-8").splitlines()) == 2


def test_decision_requires_a_complete_non_regressing_comparison() -> None:
    improved = {"recall": 0.1, "mrr": 0.2, "ndcg": 0.0}

    assert _decision(False, improved) == "inconclusive"
    assert _decision(True, improved) == "carry-forward-to-#15"
    assert _decision(True, {**improved, "ndcg": -0.01}) == "reject"

"""Offline tests for the Cohere second-stage adapter."""

from __future__ import annotations

from dataclasses import dataclass
from math import nan

import pytest

from ocio.cohere_reranker import (
    CohereReranker,
    CohereRerankError,
    reranker_from_environment,
)
from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
    Reranker,
)


@dataclass
class Result:
    index: int
    relevance_score: float


@dataclass
class BilledUnits:
    search_units: float


@dataclass
class Meta:
    billed_units: BilledUnits


@dataclass
class Response:
    results: list[Result]
    meta: Meta


class FakeClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def rerank(self, **request: object) -> object:
        self.calls.append(request)
        return self.response


def ranking(size: int = 3) -> Ranking:
    return Ranking(
        "pg-textsearch-bm25",
        tuple(
            RankedCandidate(
                Candidate(
                    ChunkReference("doc", f"chunk-{index}"),
                    f"contenuto {index}",
                    (PartitionReference("doc", f"art-{index}"),),
                    ChunkReference("doc", "parent"),
                ),
                score=-1.0 / index,
                rank=index,
            )
            for index in range(1, size + 1)
        ),
        {"engine": "pg_textsearch"},
        2.0,
    )


def test_reranks_by_provider_index_and_preserves_local_candidates() -> None:
    source = ranking()
    client = FakeClient(
        Response([Result(2, 0.9), Result(0, 0.7)], Meta(BilledUnits(1.0)))
    )
    reranker: Reranker = CohereReranker(client)

    result = reranker.rerank("domanda", source, 2)

    assert [item.candidate for item in result.candidates] == [
        source.candidates[2].candidate,
        source.candidates[0].candidate,
    ]
    assert [item.score for item in result.candidates] == [0.9, 0.7]
    assert [item.rank for item in result.candidates] == [1, 2]
    assert result.stage == "cohere-rerank-v4.0-pro"
    assert result.configuration["billed_search_units"] == 1.0
    assert client.calls == [
        {
            "model": "rerank-v4.0-pro",
            "query": "domanda",
            "documents": ["contenuto 1", "contenuto 2", "contenuto 3"],
            "top_n": 2,
        }
    ]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (Response([Result(0, 0.9), Result(0, 0.8)], Meta(BilledUnits(1))), "duplicato"),
        (
            Response([Result(3, 0.9), Result(1, 0.8)], Meta(BilledUnits(1))),
            "fuori intervallo",
        ),
        (Response([Result(0, nan), Result(1, 0.8)], Meta(BilledUnits(1))), "finito"),
        (
            Response([Result(0, 0.9), Result(1, 0.8)], Meta(BilledUnits(nan))),
            "search_units",
        ),
        (object(), "Risposta"),
    ],
)
def test_rejects_invalid_provider_responses(response: object, message: str) -> None:
    with pytest.raises(CohereRerankError, match=message):
        CohereReranker(FakeClient(response)).rerank("domanda", ranking(), 2)


def test_rejects_invalid_limit_without_calling_provider() -> None:
    client = FakeClient(Response([], Meta(BilledUnits(0))))

    with pytest.raises(CohereRerankError, match="limite"):
        CohereReranker(client).rerank("domanda", ranking(), 0)

    assert client.calls == []


def test_live_adapter_requires_explicit_cohere_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COHERE_API_KEY", raising=False)

    with pytest.raises(CohereRerankError, match="COHERE_API_KEY"):
        reranker_from_environment()

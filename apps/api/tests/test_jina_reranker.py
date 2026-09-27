"""Offline tests for the Jina second-stage adapter."""

from __future__ import annotations

from typing import Any

import pytest

from ocio.jina_reranker import JinaReranker, JinaRerankError
from ocio.retrieval import (
    Candidate,
    ChunkReference,
    RankedCandidate,
    Ranking,
    Reranker,
)


class FakeClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def rerank(self, **request: object) -> object:
        self.calls.append(request)
        return self.response


def ranking() -> Ranking:
    return Ranking(
        "bm25",
        tuple(
            RankedCandidate(
                Candidate(ChunkReference("doc", f"chunk-{index}"), text, ()),
                -float(index),
                index,
            )
            for index, text in enumerate(("uno", "due", "tre"), start=1)
        ),
        {},
        1.0,
    )


def test_reranks_with_jina_v35_and_records_token_usage() -> None:
    source = ranking()
    client = FakeClient(
        {
            "results": [
                {"index": 2, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.7},
            ],
            "usage": {"total_tokens": 42},
        }
    )
    reranker: Reranker = JinaReranker(client)

    result = reranker.rerank("domanda", source, 2)

    assert [item.candidate for item in result.candidates] == [
        source.candidates[2].candidate,
        source.candidates[0].candidate,
    ]
    assert result.configuration == {
        "provider": "jina",
        "model": "jina-reranker-v3.5",
        "input_candidate_count": 3,
        "output_candidate_count": 2,
        "total_tokens": 42,
    }
    assert client.calls == [
        {
            "model": "jina-reranker-v3.5",
            "query": "domanda",
            "documents": ["uno", "due", "tre"],
            "top_n": 2,
        }
    ]


@pytest.mark.parametrize(
    "response",
    [
        {"results": [{"index": 3, "relevance_score": 0.9}], "usage": {"total_tokens": 1}},
        {"results": [{"index": 0, "relevance_score": float("nan")}], "usage": {"total_tokens": 1}},
        {"results": [], "usage": {"total_tokens": -1}},
        {},
    ],
)
def test_rejects_invalid_jina_responses(response: dict[str, Any]) -> None:
    with pytest.raises(JinaRerankError):
        JinaReranker(FakeClient(response)).rerank("domanda", ranking(), 1)

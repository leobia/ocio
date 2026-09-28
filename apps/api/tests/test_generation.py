"""Tests for provider-independent grounded generation."""

from __future__ import annotations

from typing import Any

import pytest

from ocio.generation import (
    Citation,
    CitationSource,
    GenerationConfig,
    GenerationTrace,
    GroundedAnswerGenerator,
    InvalidGenerationOutput,
    ProviderGenerationError,
    ProviderRequest,
)
from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
)


class FakeResolver:
    def __init__(self, citations: tuple[Citation, ...]) -> None:
        self.citations = citations

    def resolve(self, ranking: Ranking) -> tuple[Citation, ...]:
        return self.citations


class FakeProvider:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> dict[str, Any]:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def source(partition: str) -> CitationSource:
    return CitationSource(
        partition, "articolo", None, {}, "2025-01-01", None,
        "Normattiva", "https://example.test", "2026-09-23T00:00:00+00:00",
        "a" * 64, {},
    )


def citation(number: int) -> Citation:
    return Citation(
        f"C{number}", ChunkReference("doc", f"chunk-{number}"),
        f"passaggio {number}", "Documento", "atto_normativo", "urn:test",
        "2025-01-01", None, (source(f"art-{number}"),),
    )


def ranking(size: int = 2) -> Ranking:
    return Ranking(
        "cohere-rerank", tuple(
            RankedCandidate(
                Candidate(
                    ChunkReference("doc", f"chunk-{index}"), f"passaggio {index}",
                    (PartitionReference("doc", f"art-{index}"),),
                ), 1.0 / index, index,
            )
            for index in range(1, size + 1)
        ), {"chunk_set_fingerprint": "fingerprint"}, 1.0,
    )


def generator(result: dict[str, Any] | Exception) -> tuple[GroundedAnswerGenerator, FakeProvider]:
    provider = FakeProvider(result)
    return (
        GroundedAnswerGenerator(
            FakeResolver((citation(1), citation(2))), provider,
            GenerationConfig("configured-model", provider_parameters={"temperature": 0}),
        ),
        provider,
    )


def test_generates_validated_answer_with_multiple_citations_and_trace() -> None:
    service, provider = generator({
        "claims": [{"text": "Obbligo applicabile.", "citation_ids": ["C2", "C1"]}],
        "conditions": ["Se sono presenti lavoratori."],
        "missing_data": ["Numero di lavoratori."],
    })

    result = service.generate("Quali obblighi si applicano?", ranking())

    assert result.answer.claims[0].citation_ids == ("C2", "C1")
    assert [item.citation_id for item in result.answer.citations] == ["C2", "C1"]
    assert result.answer.conditions == ("Se sono presenti lavoratori.",)
    assert result.answer.missing_data == ("Numero di lavoratori.",)
    assert provider.requests[0].evidence[0].citation_id == "C1"
    assert provider.requests[0].model == "configured-model"
    assert result.trace.error is None
    assert GenerationTrace.from_json(result.trace.to_json()) == result.trace


@pytest.mark.parametrize(
    "output",
    [
        {"claims": [], "conditions": [], "missing_data": []},
        {"claims": [{"text": "claim", "citation_ids": []}], "conditions": [], "missing_data": []},
        {"claims": [{"text": "claim", "citation_ids": ["unknown"]}], "conditions": [], "missing_data": []},
        {"claims": [{"text": "claim", "citation_ids": ["C1"]}], "conditions": []},
    ],
)
def test_rejects_malformed_uncited_and_unknown_outputs(output: dict[str, Any]) -> None:
    service, _ = generator(output)

    with pytest.raises(InvalidGenerationOutput) as raised:
        service.generate("domanda", ranking())

    assert raised.value.trace is not None
    assert raised.value.trace.validated_result is None
    assert raised.value.trace.error == {
        "type": "InvalidGenerationOutput", "message": str(raised.value)
    }


def test_provider_failure_is_typed_and_has_a_failure_trace() -> None:
    service, _ = generator(RuntimeError("down"))

    with pytest.raises(ProviderGenerationError, match="down") as raised:
        service.generate("domanda", ranking())

    assert raised.value.trace is not None
    assert raised.value.trace.raw_result is None
    assert raised.value.trace.evidence_ids == ("C1", "C2")


def test_rejects_unsafe_provider_parameters_before_generation() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        GenerationConfig("model", provider_parameters={"api_key": "secret"})

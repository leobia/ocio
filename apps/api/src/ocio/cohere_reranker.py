"""Cohere adapter for the provider-independent reranking contract."""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from time import perf_counter
from typing import Protocol, cast

from ocio.retrieval import RankedCandidate, Ranking

COHERE_MODEL = "rerank-v4.0-pro"


class CohereRerankError(Exception):
    """Cohere could not produce a valid reranking."""


class CohereClient(Protocol):
    def rerank(
        self, *, model: str, query: str, documents: Sequence[str], top_n: int
    ) -> object: ...


class CohereReranker:
    """Rerank local candidates while keeping their identity and provenance local."""

    def __init__(self, client: CohereClient, model: str = COHERE_MODEL) -> None:
        self.client = client
        self.model = model

    def rerank(self, query: str, ranking: Ranking, limit: int) -> Ranking:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise CohereRerankError("Il limite di reranking deve essere positivo.")
        output_count = min(limit, len(ranking.candidates))
        started_at = perf_counter()
        try:
            response = self.client.rerank(
                model=self.model,
                query=query,
                documents=[item.candidate.content for item in ranking.candidates],
                top_n=output_count,
            )
        except Exception as error:
            raise CohereRerankError(f"Chiamata Cohere fallita: {error}") from error
        latency_ms = (perf_counter() - started_at) * 1000
        results, search_units = _validate_response(
            response, len(ranking.candidates), output_count
        )
        candidates = tuple(
            RankedCandidate(
                candidate=ranking.candidates[index].candidate,
                score=score,
                rank=rank,
            )
            for rank, (index, score) in enumerate(results, start=1)
        )
        return Ranking(
            stage=f"cohere-{self.model}",
            candidates=candidates,
            configuration={
                "provider": "cohere",
                "model": self.model,
                "input_candidate_count": len(ranking.candidates),
                "output_candidate_count": len(candidates),
                "billed_search_units": search_units,
            },
            latency_ms=latency_ms,
        )


def reranker_from_environment() -> CohereReranker:
    """Build the live adapter without ever retaining the key in artifacts."""
    api_key = os.environ.get("COHERE_API_KEY")
    if not api_key:
        raise CohereRerankError(
            "COHERE_API_KEY non è impostata; configurarla prima del benchmark live."
        )
    try:
        import cohere
    except ImportError as error:  # pragma: no cover - packaging guards this path
        raise CohereRerankError("Il pacchetto cohere non è installato.") from error
    return CohereReranker(cast(CohereClient, cohere.ClientV2(api_key=api_key)))


def _validate_response(
    response: object, candidate_count: int, output_count: int
) -> tuple[tuple[tuple[int, float], ...], float]:
    try:
        raw_results = getattr(response, "results")
        meta = getattr(response, "meta")
        billed_units = getattr(meta, "billed_units")
        raw_search_units = getattr(billed_units, "search_units")
    except (AttributeError, TypeError) as error:
        raise CohereRerankError("Risposta Cohere priva dei campi richiesti.") from error
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
        raise CohereRerankError("Risposta Cohere results non valida.")
    if len(raw_results) != output_count:
        raise CohereRerankError(
            f"Risposta Cohere con {len(raw_results)} risultati, attesi {output_count}."
        )
    if isinstance(raw_search_units, bool) or not isinstance(
        raw_search_units, (int, float)
    ):
        raise CohereRerankError("Risposta Cohere con search_units non valide.")
    search_units = float(raw_search_units)
    if not math.isfinite(search_units) or search_units < 0:
        raise CohereRerankError("Risposta Cohere con search_units non finite.")

    validated: list[tuple[int, float]] = []
    seen: set[int] = set()
    for item in raw_results:
        try:
            raw_index = getattr(item, "index")
            raw_score = getattr(item, "relevance_score")
        except AttributeError as error:
            raise CohereRerankError("Risposta Cohere results non valida.") from error
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise CohereRerankError("Risposta Cohere con indice non valido.")
        if raw_index < 0 or raw_index >= candidate_count:
            raise CohereRerankError("Risposta Cohere con indice fuori intervallo.")
        if raw_index in seen:
            raise CohereRerankError("Risposta Cohere con indice duplicato.")
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise CohereRerankError("Risposta Cohere con score non valido.")
        score = float(raw_score)
        if not math.isfinite(score):
            raise CohereRerankError("Risposta Cohere con score non finito.")
        seen.add(raw_index)
        validated.append((raw_index, score))
    return tuple(validated), search_units

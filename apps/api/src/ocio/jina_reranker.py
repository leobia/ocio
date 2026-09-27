"""Jina adapter for the provider-independent reranking contract."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Protocol

from ocio.retrieval import RankedCandidate, Ranking

JINA_MODEL = "jina-reranker-v3.5"
JINA_ENDPOINT = "https://api.jina.ai/v1/rerank"


class JinaRerankError(Exception):
    """Jina could not produce a valid reranking."""


class JinaClient(Protocol):
    def rerank(
        self, *, model: str, query: str, documents: Sequence[str], top_n: int
    ) -> object: ...


class JinaHttpClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def rerank(
        self, *, model: str, query: str, documents: Sequence[str], top_n: int
    ) -> object:
        payload = json.dumps(
            {
                "model": model,
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
                "return_documents": False,
            }
        ).encode()
        request = urllib.request.Request(
            JINA_ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise JinaRerankError(f"Jina HTTP {error.code}.") from error
        except (OSError, json.JSONDecodeError) as error:
            raise JinaRerankError(f"Chiamata Jina fallita: {error}") from error


class JinaReranker:
    def __init__(self, client: JinaClient, model: str = JINA_MODEL) -> None:
        self.client = client
        self.model = model

    def rerank(self, query: str, ranking: Ranking, limit: int) -> Ranking:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise JinaRerankError("Il limite di reranking deve essere positivo.")
        output_count = min(limit, len(ranking.candidates))
        started_at = perf_counter()
        try:
            response = self.client.rerank(
                model=self.model,
                query=query,
                documents=[item.candidate.content for item in ranking.candidates],
                top_n=output_count,
            )
        except JinaRerankError:
            raise
        except Exception as error:
            raise JinaRerankError(f"Chiamata Jina fallita: {error}") from error
        latency_ms = (perf_counter() - started_at) * 1000
        results, total_tokens = _validate_response(
            response, len(ranking.candidates), output_count
        )
        return Ranking(
            stage=f"jina-{self.model}",
            candidates=tuple(
                RankedCandidate(
                    ranking.candidates[index].candidate, score, rank
                )
                for rank, (index, score) in enumerate(results, start=1)
            ),
            configuration={
                "provider": "jina",
                "model": self.model,
                "input_candidate_count": len(ranking.candidates),
                "output_candidate_count": len(results),
                "total_tokens": total_tokens,
            },
            latency_ms=latency_ms,
        )


def reranker_from_environment() -> JinaReranker:
    api_key = os.environ.get("JINA_API_KEY")
    if not api_key:
        raise JinaRerankError(
            "JINA_API_KEY non è impostata; configurarla prima del benchmark live."
        )
    return JinaReranker(JinaHttpClient(api_key))


def _validate_response(
    response: object, candidate_count: int, output_count: int
) -> tuple[tuple[tuple[int, float], ...], int]:
    if not isinstance(response, Mapping):
        raise JinaRerankError("Risposta Jina non valida.")
    results = response.get("results")
    usage = response.get("usage")
    if (
        not isinstance(results, Sequence)
        or isinstance(results, (str, bytes))
        or len(results) != output_count
        or not isinstance(usage, Mapping)
    ):
        raise JinaRerankError("Risposta Jina priva dei campi richiesti.")
    total_tokens = usage.get("total_tokens")
    if (
        isinstance(total_tokens, bool)
        or not isinstance(total_tokens, int)
        or total_tokens < 0
    ):
        raise JinaRerankError("Risposta Jina con total_tokens non validi.")
    validated: list[tuple[int, float]] = []
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, Mapping):
            raise JinaRerankError("Risultato Jina non valido.")
        index = item.get("index")
        raw_score = item.get("relevance_score")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= candidate_count
            or index in seen
        ):
            raise JinaRerankError("Risposta Jina con indice non valido.")
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise JinaRerankError("Risposta Jina con score non valido.")
        score = float(raw_score)
        if not math.isfinite(score):
            raise JinaRerankError("Risposta Jina con score non finito.")
        seen.add(index)
        validated.append((index, score))
    return tuple(validated), total_tokens

"""Fusione deterministica e spiegabile di graduatorie eterogenee."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from ocio.retrieval import (
    Candidate,
    ChunkReference,
    FusionContribution,
    RankedCandidate,
    Ranking,
)


class FusionError(Exception):
    """Le graduatorie non possono essere fuse."""


@dataclass(frozen=True, slots=True)
class RrfFusion:
    rank_constant: int = 60

    def __post_init__(self) -> None:
        if self.rank_constant < 1:
            raise FusionError("La costante RRF deve essere positiva.")

    def fuse(self, rankings: Sequence[Ranking], limit: int) -> Ranking:
        return _fuse(
            rankings,
            limit,
            stage="fusion-rrf",
            configuration={"rank_constant": self.rank_constant},
            scores=lambda ranking: tuple(
                1.0 / (self.rank_constant + item.rank)
                for item in ranking.candidates
            ),
        )


@dataclass(frozen=True, slots=True)
class WeightedScoreFusion:
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.weights:
            raise FusionError("È richiesto almeno un peso.")
        if any(not math.isfinite(weight) or weight < 0 for weight in self.weights):
            raise FusionError("I pesi devono essere finiti e non negativi.")
        if sum(self.weights) <= 0:
            raise FusionError("Almeno un peso deve essere positivo.")

    def fuse(self, rankings: Sequence[Ranking], limit: int) -> Ranking:
        if len(rankings) != len(self.weights):
            raise FusionError("Serve un peso per ogni graduatoria.")
        total = sum(self.weights)
        normalized_weights = tuple(weight / total for weight in self.weights)
        return _fuse(
            rankings,
            limit,
            stage="fusion-weighted-score",
            configuration={
                "weights": list(self.weights),
                "normalized_weights": list(normalized_weights),
                "normalization": "best-worst",
            },
            scores=lambda ranking: _normalized_scores(ranking),
            multipliers=normalized_weights,
        )


@dataclass(slots=True)
class _Aggregate:
    candidate: Candidate
    score: float
    best_rank: int
    contributions: list[FusionContribution]


def _fuse(
    rankings: Sequence[Ranking],
    limit: int,
    *,
    stage: str,
    configuration: dict[str, object],
    scores: Callable[[Ranking], tuple[float, ...]],
    multipliers: Sequence[float] | None = None,
) -> Ranking:
    if limit <= 0:
        raise FusionError("Il limite deve essere positivo.")
    started_at = perf_counter()
    aggregates: dict[ChunkReference, _Aggregate] = {}

    for source_index, ranking in enumerate(rankings):
        seen: set[ChunkReference] = set()
        multiplier = multipliers[source_index] if multipliers is not None else 1.0
        for item, value in zip(ranking.candidates, scores(ranking), strict=True):
            reference = item.candidate.reference
            if reference in seen:
                raise FusionError(
                    f"Chunk duplicato nella graduatoria {source_index}: {reference}."
                )
            seen.add(reference)
            contribution = value * multiplier
            origin = FusionContribution(
                source_index=source_index,
                stage=ranking.stage,
                rank=item.rank,
                original_score=item.score,
                contribution=contribution,
            )
            aggregate = aggregates.get(reference)
            if aggregate is None:
                aggregates[reference] = _Aggregate(
                    item.candidate, contribution, item.rank, [origin]
                )
            else:
                # La stessa identità non deve nascondere contenuti discordanti.
                if aggregate.candidate != item.candidate:
                    raise FusionError(f"Payload discordante per il chunk {reference}.")
                aggregate.score += contribution
                aggregate.best_rank = min(aggregate.best_rank, item.rank)
                aggregate.contributions.append(origin)

    ordered = sorted(
        aggregates.values(),
        key=lambda item: (
            -item.score,
            item.best_rank,
            item.candidate.reference.document_code,
            item.candidate.reference.chunk_identifier,
        ),
    )[:limit]
    candidates = tuple(
        RankedCandidate(
            item.candidate,
            score=item.score,
            rank=rank,
            contributions=tuple(item.contributions),
        )
        for rank, item in enumerate(ordered, start=1)
    )
    return Ranking(
        stage=stage,
        candidates=candidates,
        configuration={
            **configuration,
            "sources": [ranking.stage for ranking in rankings],
        },
        latency_ms=(perf_counter() - started_at) * 1000,
    )


def _normalized_scores(ranking: Ranking) -> tuple[float, ...]:
    if not ranking.candidates:
        return ()
    best = ranking.candidates[0].score
    worst = ranking.candidates[-1].score
    if best == worst:
        return (1.0,) * len(ranking.candidates)
    # Funziona anche con score decrescenti in valore assoluto, come BM25.
    return tuple((item.score - worst) / (best - worst) for item in ranking.candidates)

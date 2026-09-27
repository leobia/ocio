"""Provider-independent retrieval contracts and JSONL traces."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

TRACE_SCHEMA_VERSION = 2
SUPPORTED_TRACE_SCHEMA_VERSIONS = (1, TRACE_SCHEMA_VERSION)


class RetrievalTraceError(Exception):
    """A retrieval trace cannot be read or written."""


@dataclass(frozen=True, slots=True)
class PartitionReference:
    document_code: str
    partition_identifier: str


@dataclass(frozen=True, slots=True)
class ChunkReference:
    document_code: str
    chunk_identifier: str


@dataclass(frozen=True, slots=True)
class Candidate:
    reference: ChunkReference
    content: str
    source_partitions: tuple[PartitionReference, ...]
    parent: ChunkReference | None = None


@dataclass(frozen=True, slots=True)
class FusionContribution:
    source_index: int
    stage: str
    rank: int
    original_score: float
    contribution: float

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("source_index must be non-negative")
        if self.rank < 1:
            raise ValueError("rank must be positive")
        if not math.isfinite(self.original_score):
            raise ValueError("original_score must be finite")
        if not math.isfinite(self.contribution) or self.contribution < 0:
            raise ValueError("contribution must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: Candidate
    score: float
    rank: int
    contributions: tuple[FusionContribution, ...] = ()

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be positive")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")


@dataclass(frozen=True, slots=True)
class Ranking:
    stage: str
    candidates: tuple[RankedCandidate, ...]
    configuration: dict[str, Any]
    latency_ms: float

    def __post_init__(self) -> None:
        ranks = tuple(item.rank for item in self.candidates)
        expected = tuple(range(1, len(self.candidates) + 1))
        if ranks != expected:
            raise ValueError("candidates must be ordered by contiguous 1-based rank")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class RetrievalRun:
    run_id: str
    case_id: str
    query: str
    chunk_set_fingerprint: str
    rankings: tuple[Ranking, ...]
    rerank_error: str | None = None
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_TRACE_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported trace schema version: {self.schema_version}")


class Retriever(Protocol):
    def retrieve(self, query: str, limit: int) -> Ranking: ...


class Fusion(Protocol):
    def fuse(self, rankings: Sequence[Ranking], limit: int) -> Ranking: ...


class Reranker(Protocol):
    def rerank(self, query: str, ranking: Ranking, limit: int) -> Ranking: ...


def write_trace(runs: Iterable[RetrievalRun], output: Path) -> None:
    """Write one retrieval run per JSONL line."""
    try:
        serialized = "\n".join(
            json.dumps(asdict(run), ensure_ascii=False, separators=(",", ":"))
            for run in runs
        )
        output.write_text(serialized + ("\n" if serialized else ""), encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        raise RetrievalTraceError(str(error)) from error


def read_trace(source: Path) -> tuple[RetrievalRun, ...]:
    """Read retrieval runs previously written as JSONL."""
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RetrievalTraceError(str(error)) from error

    runs: list[RetrievalRun] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
            runs.append(_run_from_dict(value))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise RetrievalTraceError(f"line {line_number}: {error}") from error
    return tuple(runs)


def _run_from_dict(value: dict[str, Any]) -> RetrievalRun:
    return RetrievalRun(
        run_id=str(value["run_id"]),
        case_id=str(value["case_id"]),
        query=str(value["query"]),
        chunk_set_fingerprint=str(value["chunk_set_fingerprint"]),
        rankings=tuple(_ranking_from_dict(item) for item in value["rankings"]),
        rerank_error=(
            str(value["rerank_error"])
            if value.get("rerank_error") is not None
            else None
        ),
        schema_version=int(value["schema_version"]),
    )


def _ranking_from_dict(value: dict[str, Any]) -> Ranking:
    return Ranking(
        stage=str(value["stage"]),
        candidates=tuple(
            _ranked_candidate_from_dict(item) for item in value["candidates"]
        ),
        configuration=dict(value["configuration"]),
        latency_ms=float(value["latency_ms"]),
    )


def _ranked_candidate_from_dict(value: dict[str, Any]) -> RankedCandidate:
    candidate = value["candidate"]
    reference = candidate["reference"]
    parent = candidate["parent"]
    return RankedCandidate(
        candidate=Candidate(
            reference=ChunkReference(
                document_code=str(reference["document_code"]),
                chunk_identifier=str(reference["chunk_identifier"]),
            ),
            content=str(candidate["content"]),
            source_partitions=tuple(
                PartitionReference(
                    document_code=str(item["document_code"]),
                    partition_identifier=str(item["partition_identifier"]),
                )
                for item in candidate["source_partitions"]
            ),
            parent=(
                ChunkReference(
                    document_code=str(parent["document_code"]),
                    chunk_identifier=str(parent["chunk_identifier"]),
                )
                if parent is not None
                else None
            ),
        ),
        score=float(value["score"]),
        rank=int(value["rank"]),
        contributions=tuple(
            FusionContribution(
                source_index=int(item["source_index"]),
                stage=str(item["stage"]),
                rank=int(item["rank"]),
                original_score=float(item["original_score"]),
                contribution=float(item["contribution"]),
            )
            for item in value.get("contributions", ())
        ),
    )

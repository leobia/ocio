"""Grounded answer generation with server-owned citations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from time import perf_counter
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ocio.retrieval import ChunkReference, Ranking

TRACE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CitationSource:
    partition_identifier: str
    partition_kind: str
    rubric: str | None
    locator: dict[str, Any]
    valid_from: str | None
    valid_until: str | None
    provider: str
    url: str
    acquired_at: str
    acquisition_sha256: str
    acquisition_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    chunk: ChunkReference
    passage: str
    document_title: str
    document_type: str
    document_urn: str | None
    document_valid_from: str | None
    document_valid_until: str | None
    sources: tuple[CitationSource, ...]


@dataclass(frozen=True, slots=True)
class ProviderEvidence:
    citation_id: str
    passage: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    question: str
    evidence: tuple[ProviderEvidence, ...]
    model: str
    parameters: dict[str, Any]
    prompt_version: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class GroundedClaim:
    text: str
    citation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    claims: tuple[GroundedClaim, ...]
    conditions: tuple[str, ...]
    missing_data: tuple[str, ...]
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    model: str
    prompt_version: str = "grounded-answer-v1"
    provider_parameters: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.prompt_version.strip():
            raise ValueError("model and prompt_version must be non-empty")
        unsupported = set(self.provider_parameters or {}) - {
            "max_output_tokens",
            "reasoning",
            "temperature",
            "top_p",
        }
        if unsupported:
            raise ValueError(
                f"unsupported or unsafe provider parameters: {sorted(unsupported)}"
            )

    def parameters(self) -> dict[str, Any]:
        return dict(self.provider_parameters or {})


@dataclass(frozen=True, slots=True)
class GenerationTrace:
    question: str
    prompt_version: str
    output_schema_version: int
    model: str
    parameters: dict[str, Any]
    evidence_ids: tuple[str, ...]
    raw_result: dict[str, Any] | None
    validated_result: dict[str, Any] | None
    latency_ms: float
    error: dict[str, str] | None
    schema_version: int = TRACE_SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> GenerationTrace:
        raw = json.loads(value)
        if int(raw["schema_version"]) != TRACE_SCHEMA_VERSION:
            raise ValueError("unsupported generation trace schema version")
        return cls(
            question=str(raw["question"]),
            prompt_version=str(raw["prompt_version"]),
            output_schema_version=int(raw["output_schema_version"]),
            model=str(raw["model"]),
            parameters=dict(raw["parameters"]),
            evidence_ids=tuple(str(item) for item in raw["evidence_ids"]),
            raw_result=(dict(raw["raw_result"]) if raw["raw_result"] is not None else None),
            validated_result=(
                dict(raw["validated_result"])
                if raw["validated_result"] is not None
                else None
            ),
            latency_ms=float(raw["latency_ms"]),
            error=dict(raw["error"]) if raw["error"] is not None else None,
            schema_version=int(raw["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class GenerationResult:
    answer: GroundedAnswer
    trace: GenerationTrace


class GenerationError(Exception):
    """Generation failed atomically and produced no partial answer."""

    def __init__(self, message: str, trace: GenerationTrace | None = None) -> None:
        super().__init__(message)
        self.trace = trace


class CitationResolutionError(GenerationError):
    pass


class ProviderGenerationError(GenerationError):
    pass


class InvalidGenerationOutput(GenerationError):
    pass


class CitationResolver(Protocol):
    def resolve(self, ranking: Ranking) -> tuple[Citation, ...]: ...


class AnswerProvider(Protocol):
    def generate(self, request: ProviderRequest) -> Mapping[str, Any]: ...


class GroundedAnswerGenerator:
    """Hide citation resolution, provider calls, validation, and tracing."""

    def __init__(
        self,
        resolver: CitationResolver,
        provider: AnswerProvider,
        config: GenerationConfig,
    ) -> None:
        self.resolver = resolver
        self.provider = provider
        self.config = config

    def generate(self, question: str, ranking: Ranking) -> GenerationResult:
        if not question.strip():
            raise CitationResolutionError("La domanda non può essere vuota.")
        started_at = perf_counter()
        raw_result: dict[str, Any] | None = None
        citations: tuple[Citation, ...] = ()
        try:
            citations = self.resolver.resolve(ranking)
            _validate_catalogue(citations, len(ranking.candidates))
            request = ProviderRequest(
                question=question,
                evidence=tuple(
                    ProviderEvidence(item.citation_id, item.passage)
                    for item in citations
                ),
                model=self.config.model,
                parameters=self.config.parameters(),
                prompt_version=self.config.prompt_version,
                schema_version=1,
            )
            raw_result = dict(self.provider.generate(request))
            answer = _validate_answer(raw_result, citations)
            validated = _answer_dict(answer)
        except GenerationError as error:
            error.trace = self._trace(
                question, citations, raw_result, None, started_at, error
            )
            raise
        except Exception as error:
            wrapped = ProviderGenerationError(f"Generazione provider fallita: {error}")
            wrapped.trace = self._trace(
                question, citations, raw_result, None, started_at, wrapped
            )
            raise wrapped from error
        trace = self._trace(question, citations, raw_result, validated, started_at, None)
        return GenerationResult(answer, trace)

    def _trace(
        self,
        question: str,
        citations: tuple[Citation, ...],
        raw_result: dict[str, Any] | None,
        validated_result: dict[str, Any] | None,
        started_at: float,
        error: Exception | None,
    ) -> GenerationTrace:
        return GenerationTrace(
            question=question,
            prompt_version=self.config.prompt_version,
            output_schema_version=1,
            model=self.config.model,
            parameters=self.config.parameters(),
            evidence_ids=tuple(item.citation_id for item in citations),
            raw_result=raw_result,
            validated_result=validated_result,
            latency_ms=(perf_counter() - started_at) * 1000,
            error=(
                {"type": type(error).__name__, "message": str(error)}
                if error is not None
                else None
            ),
        )


class PostgresCitationResolver:
    """Resolve ranked chunks against the canonical corpus owned by the server."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def resolve(self, ranking: Ranking) -> tuple[Citation, ...]:
        fingerprint = ranking.configuration.get("chunk_set_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise CitationResolutionError(
                "Il ranking non identifica il proprio insieme di chunk."
            )
        citations = []
        for index, ranked in enumerate(ranking.candidates, start=1):
            rows = list(
                self.connection.execute(
                    text(_CITATION_SQL),
                    {
                        "fingerprint": fingerprint,
                        "document_code": ranked.candidate.reference.document_code,
                        "chunk_identifier": ranked.candidate.reference.chunk_identifier,
                    },
                ).mappings()
            )
            if not rows:
                raise CitationResolutionError(
                    f"Chunk non risolvibile: {ranked.candidate.reference}."
                )
            if str(rows[0]["passage"]) != ranked.candidate.content:
                raise CitationResolutionError("Il passaggio recuperato non coincide col corpus.")
            expected = tuple(
                (item.document_code, item.partition_identifier)
                for item in ranked.candidate.source_partitions
            )
            actual = tuple(
                (str(row["document_code"]), str(row["partition_identifier"]))
                for row in rows
            )
            if actual != expected:
                raise CitationResolutionError(
                    "Le partizioni sorgente del ranking non coincidono col corpus."
                )
            citations.append(
                _citation_from_rows(f"C{index}", [dict(row) for row in rows])
            )
        return tuple(citations)


def _validate_catalogue(citations: tuple[Citation, ...], expected: int) -> None:
    identifiers = tuple(item.citation_id for item in citations)
    if expected == 0:
        raise CitationResolutionError("Il ranking non contiene evidenze.")
    if len(citations) != expected or len(set(identifiers)) != len(identifiers):
        raise CitationResolutionError("Il catalogo delle citazioni non è valido.")
    if any(not item.citation_id or not item.passage.strip() or not item.sources for item in citations):
        raise CitationResolutionError("Una citazione è incompleta.")


def _validate_answer(raw: Mapping[str, Any], citations: tuple[Citation, ...]) -> GroundedAnswer:
    if set(raw) != {"claims", "conditions", "missing_data"}:
        raise InvalidGenerationOutput("Lo schema della risposta non è valido.")
    raw_claims = raw["claims"]
    if not isinstance(raw_claims, list) or not raw_claims:
        raise InvalidGenerationOutput("La risposta deve contenere almeno una claim.")
    known = {item.citation_id: item for item in citations}
    claims: list[GroundedClaim] = []
    used: list[str] = []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict) or set(raw_claim) != {"text", "citation_ids"}:
            raise InvalidGenerationOutput("Una claim non rispetta lo schema.")
        claim_text = raw_claim["text"]
        ids = raw_claim["citation_ids"]
        if not isinstance(claim_text, str) or not claim_text.strip():
            raise InvalidGenerationOutput("Una claim ha testo vuoto.")
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
            raise InvalidGenerationOutput("Una claim normativa non ha citazioni.")
        if unknown := set(ids) - set(known):
            raise InvalidGenerationOutput(f"Citation ID sconosciuti: {sorted(unknown)}.")
        if len(set(ids)) != len(ids):
            raise InvalidGenerationOutput("Una claim contiene citazioni duplicate.")
        claims.append(GroundedClaim(claim_text.strip(), tuple(ids)))
        used.extend(item for item in ids if item not in used)
    conditions = _string_list(raw["conditions"], "conditions")
    missing_data = _string_list(raw["missing_data"], "missing_data")
    return GroundedAnswer(
        tuple(claims), conditions, missing_data, tuple(known[item] for item in used)
    )


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise InvalidGenerationOutput(f"{field} non è una lista di testi validi.")
    return tuple(item.strip() for item in value)


def _answer_dict(answer: GroundedAnswer) -> dict[str, Any]:
    # Keep trace payloads in their JSON-native form so serialization round-trips
    # without tuple/list drift inside nested values.
    value = json.loads(json.dumps(asdict(answer), ensure_ascii=False))
    if not isinstance(value, dict):  # pragma: no cover - asdict always returns a dict
        raise TypeError("grounded answer is not serializable")
    return value


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _citation_from_rows(identifier: str, rows: Sequence[Mapping[str, Any]]) -> Citation:
    first = rows[0]
    sources = tuple(
        CitationSource(
            partition_identifier=str(row["partition_identifier"]),
            partition_kind=str(row["partition_kind"]),
            rubric=str(row["rubric"]) if row["rubric"] is not None else None,
            locator=dict(row["locator"]),
            valid_from=_iso(row["partition_valid_from"]),
            valid_until=_iso(row["partition_valid_until"]),
            provider=str(row["provider"]),
            url=str(row["url"]),
            acquired_at=_iso(row["acquired_at"]) or "",
            acquisition_sha256=str(row["acquisition_sha256"]),
            acquisition_metadata=dict(row["acquisition_metadata"]),
        )
        for row in rows
    )
    return Citation(
        citation_id=identifier,
        chunk=ChunkReference(str(first["document_code"]), str(first["chunk_identifier"])),
        passage=str(first["passage"]),
        document_title=str(first["document_title"]),
        document_type=str(first["document_type"]),
        document_urn=str(first["document_urn"]) if first["document_urn"] is not None else None,
        document_valid_from=_iso(first["document_valid_from"]),
        document_valid_until=_iso(first["document_valid_until"]),
        sources=sources,
    )


_CITATION_SQL = """
SELECT d.codice AS document_code, d.titolo AS document_title,
       d.tipo_documento AS document_type, d.urn AS document_urn,
       d.vigente_dal AS document_valid_from, d.vigente_al AS document_valid_until,
       c.identificatore AS chunk_identifier, c.contenuto AS passage,
       cp.identificatore_partizione AS partition_identifier,
       p.tipo AS partition_kind, p.rubrica AS rubric, p.localizzatore AS locator,
       p.vigente_dal AS partition_valid_from, p.vigente_al AS partition_valid_until,
       a.fonte AS provider, a.url, a.acquisita_il AS acquired_at,
       a.sha256 AS acquisition_sha256, a.metadati AS acquisition_metadata
FROM chunk AS c
JOIN insiemi_chunk AS i ON i.id = c.insieme_chunk_id
JOIN documenti AS d ON d.id = c.documento_id
JOIN chunk_partizioni AS cp ON cp.chunk_id = c.id
LEFT JOIN partizioni_documentali AS p ON p.id = cp.partizione_documentale_id
JOIN acquisizioni_fonti AS a ON a.id = cp.acquisizione_fonte_id
WHERE i.fingerprint = :fingerprint
  AND d.codice = :document_code
  AND c.identificatore = :chunk_identifier
  AND p.id IS NOT NULL
ORDER BY cp.posizione
"""

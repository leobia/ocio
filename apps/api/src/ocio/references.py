"""Lookup dei riferimenti normativi ed espansione del glossario."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
    Retriever,
)


class ReferenceLookupError(Exception):
    """Il lookup dei riferimenti non può essere eseguito."""


@dataclass(frozen=True, slots=True)
class Glossary:
    version: int
    documents: Mapping[str, tuple[str, ...]]
    terms: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class LegalReference:
    document_code: str
    article: str | None
    paragraph: str | None
    letter: str | None


@dataclass(frozen=True, slots=True)
class QueryExpansion:
    enabled: bool
    glossary_version: int
    original_query: str
    effective_query: str
    expansions: tuple[tuple[str, str], ...]


def load_glossary(source: Path | None = None) -> Glossary:
    """Carica il glossario versionato distribuito con OCIO."""
    path = source or Path(__file__).with_name("glossary-v1.yaml")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        version = int(value["version"])
        documents = {
            str(code): tuple(str(alias) for alias in aliases)
            for code, aliases in value["documents"].items()
        }
        terms = {
            str(term): str(expansion) for term, expansion in value["terms"].items()
        }
    except (OSError, TypeError, ValueError, KeyError, AttributeError) as error:
        raise ReferenceLookupError(f"Glossario non valido: {error}") from error
    if version < 1 or any(not aliases for aliases in documents.values()):
        raise ReferenceLookupError("Glossario non valido: versione o alias mancanti.")
    alias_owners: dict[str, str] = {}
    for code, aliases in documents.items():
        for alias in aliases:
            normalized = _normalize(alias)
            owner = alias_owners.setdefault(normalized, code)
            if owner != code:
                raise ReferenceLookupError(
                    f"Glossario non valido: alias {alias!r} assegnato a più atti."
                )
    return Glossary(version, documents, terms)


def parse_legal_reference(query: str, glossary: Glossary) -> LegalReference | None:
    """Riconosce un atto e gli eventuali articolo, comma e lettera."""
    normalized_query = f" {_normalize(query)} "
    matches = [
        (len(normalized), code)
        for code, aliases in glossary.documents.items()
        for alias in aliases
        if (normalized := _normalize(alias)) and f" {normalized} " in normalized_query
    ]
    if not matches:
        return None
    _, document_code = max(matches)
    return LegalReference(
        document_code=document_code,
        article=_match_marker(
            query, r"\bart(?:icolo)?\.?\s*(\d+(?:\s*-?\s*(?:bis|ter|quater))?)\b"
        ),
        paragraph=_match_marker(
            query, r"\bcomma\s+(\d+(?:\s*-?\s*(?:bis|ter|quater))?)\b"
        ),
        letter=_match_marker(query, r"\blett(?:era)?\.?\s*([a-z])(?:\)|\b)"),
    )


def expand_query(query: str, glossary: Glossary, *, enabled: bool) -> QueryExpansion:
    """Aggiunge una sola volta le espansioni presenti nella query."""
    expansions: list[tuple[str, str]] = []
    if enabled:
        for term, expansion in glossary.terms.items():
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", query, re.IGNORECASE):
                if _normalize(expansion) not in _normalize(query):
                    expansions.append((term, expansion))
    suffix = "; ".join(expansion for _, expansion in expansions)
    effective = f"{query} ({suffix})" if suffix else query
    return QueryExpansion(
        enabled, glossary.version, query, effective, tuple(expansions)
    )


class GlossaryRetriever:
    """Applica e traccia il glossario senza modificare i singoli retriever."""

    def __init__(
        self, retriever: Retriever, glossary: Glossary, *, enabled: bool
    ) -> None:
        self.retriever = retriever
        self.glossary = glossary
        self.enabled = enabled

    def retrieve(self, query: str, limit: int) -> Ranking:
        started_at = perf_counter()
        expansion = expand_query(query, self.glossary, enabled=self.enabled)
        ranking = self.retriever.retrieve(expansion.effective_query, limit)
        return Ranking(
            stage=ranking.stage,
            candidates=ranking.candidates,
            configuration={
                **ranking.configuration,
                "query_expansion": asdict(expansion),
            },
            latency_ms=(perf_counter() - started_at) * 1000,
        )


class ReferenceLookupRetriever:
    def __init__(
        self,
        connection: Connection,
        chunk_set_fingerprint: str,
        glossary: Glossary,
    ) -> None:
        self.connection = connection
        self.chunk_set_fingerprint = chunk_set_fingerprint
        self.glossary = glossary

    def retrieve(self, query: str, limit: int) -> Ranking:
        if limit <= 0:
            raise ReferenceLookupError("Il limite deve essere positivo.")
        started_at = perf_counter()
        exists = self.connection.execute(
            text("SELECT 1 FROM insiemi_chunk WHERE fingerprint = :fingerprint"),
            {"fingerprint": self.chunk_set_fingerprint},
        ).scalar_one_or_none()
        if exists is None:
            raise ReferenceLookupError(
                f"Insieme di chunk inesistente: {self.chunk_set_fingerprint}."
            )

        reference = parse_legal_reference(query, self.glossary)
        rows: list[Mapping[str, Any]] = []
        if reference and reference.article:
            rows = list(
                self.connection.execute(
                    text(_LOOKUP_SQL),
                    {
                        "fingerprint": self.chunk_set_fingerprint,
                        "document_code": reference.document_code,
                        "article": reference.article,
                        "paragraph": reference.paragraph,
                        "letter": reference.letter,
                        "has_paragraph": reference.paragraph is not None,
                        "has_letter": reference.letter is not None,
                        "limit": limit,
                    },
                ).mappings()
            )
        candidates = tuple(
            _ranked_candidate(row, rank) for rank, row in enumerate(rows, start=1)
        )
        return Ranking(
            stage="reference-lookup",
            candidates=candidates,
            configuration={
                "chunk_set_fingerprint": self.chunk_set_fingerprint,
                "glossary_version": self.glossary.version,
                "reference": asdict(reference) if reference else None,
                "resolved": bool(candidates),
            },
            latency_ms=(perf_counter() - started_at) * 1000,
        )


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    without_dots = without_marks.replace(".", "")
    return " ".join(re.sub(r"[^a-z0-9/]+", " ", without_dots).split())


def _match_marker(query: str, pattern: str) -> str | None:
    match = re.search(pattern, query, re.IGNORECASE)
    return (
        re.sub(r"\s*-?\s*(bis|ter|quater)$", r"-\1", match.group(1).casefold())
        if match
        else None
    )


def _ranked_candidate(row: Mapping[str, Any], rank: int) -> RankedCandidate:
    return RankedCandidate(
        candidate=Candidate(
            reference=ChunkReference(
                str(row["document_code"]), str(row["chunk_identifier"])
            ),
            content=str(row["content"]),
            source_partitions=tuple(
                PartitionReference(
                    str(source["document_code"]),
                    str(source["partition_identifier"]),
                )
                for source in row["source_partitions"]
            ),
            parent=(
                ChunkReference(str(row["document_code"]), str(row["parent_identifier"]))
                if row["parent_identifier"] is not None
                else None
            ),
        ),
        score=1.0 / (int(row["distance"]) + 1),
        rank=rank,
    )


_LOOKUP_SQL = """
WITH RECURSIVE selected AS (
    SELECT COALESCE(letter.id, paragraph.id, article.id) AS id
    FROM documenti AS document
    JOIN partizioni_documentali AS article
      ON article.documento_id = document.id
     AND article.tipo = 'articolo'
     AND article.marcatore = :article
    LEFT JOIN partizioni_documentali AS paragraph
      ON paragraph.partizione_genitore_id = article.id
     AND paragraph.tipo = 'comma'
     AND paragraph.marcatore = :paragraph
    LEFT JOIN partizioni_documentali AS letter
      ON letter.partizione_genitore_id = paragraph.id
     AND letter.tipo = 'lettera'
     AND letter.marcatore = :letter
    WHERE document.codice = :document_code
      AND document.abilitato_per_agente
      AND (NOT :has_paragraph OR paragraph.id IS NOT NULL)
      AND (NOT :has_letter OR letter.id IS NOT NULL)
    ORDER BY article.id, paragraph.id, letter.id
    LIMIT 1
), descendants AS (
    SELECT id, 0 AS distance FROM selected
    UNION ALL
    SELECT child.id, descendants.distance + 1
    FROM partizioni_documentali AS child
    JOIN descendants ON child.partizione_genitore_id = descendants.id
), matching AS (
    SELECT chunk.id, min(descendants.distance) AS distance
    FROM descendants
    JOIN chunk_partizioni AS source
      ON source.partizione_documentale_id = descendants.id
    JOIN chunk ON chunk.id = source.chunk_id
    JOIN insiemi_chunk AS chunk_set ON chunk_set.id = chunk.insieme_chunk_id
    JOIN documenti AS document ON document.id = chunk.documento_id
    WHERE chunk_set.fingerprint = :fingerprint
      AND chunk.ruolo = 'ricercabile'
      AND document.abilitato_per_agente
    GROUP BY chunk.id
)
SELECT document.codice AS document_code,
       chunk.identificatore AS chunk_identifier,
       chunk.contenuto AS content,
       parent.identificatore AS parent_identifier,
       matching.distance,
       (SELECT jsonb_agg(jsonb_build_object(
            'document_code', document.codice,
            'partition_identifier', source.identificatore_partizione
        ) ORDER BY source.posizione)
        FROM chunk_partizioni AS source
        WHERE source.chunk_id = chunk.id) AS source_partitions
FROM matching
JOIN chunk ON chunk.id = matching.id
JOIN documenti AS document ON document.id = chunk.documento_id
LEFT JOIN chunk AS parent ON parent.id = chunk.chunk_genitore_id
ORDER BY matching.distance, chunk.ordine, document.codice, chunk.identificatore
LIMIT :limit
"""

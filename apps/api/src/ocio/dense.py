"""Retrieval dense sui chunk tramite embedding OpenAI e pgvector."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ocio.embeddings import LARGE, SMALL, EmbeddingClient, EmbeddingConfig
from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
)

LARGE_SHORTLIST_FACTOR = 10


class DenseError(Exception):
    """La ricerca dense non può essere eseguita."""


class DenseRetriever:
    def __init__(
        self,
        connection: Connection,
        chunk_set_fingerprint: str,
        config: EmbeddingConfig,
        client: EmbeddingClient,
    ) -> None:
        if config not in (SMALL, LARGE):
            raise DenseError("Configurazione embedding non supportata.")
        self.connection = connection
        self.chunk_set_fingerprint = chunk_set_fingerprint
        self.config = config
        self.client = client

    def retrieve(self, query: str, limit: int) -> Ranking:
        if limit <= 0:
            raise DenseError("Il limite deve essere positivo.")

        started_at = perf_counter()
        exists = self.connection.execute(
            text("SELECT 1 FROM insiemi_chunk WHERE fingerprint = :fingerprint"),
            {"fingerprint": self.chunk_set_fingerprint},
        ).scalar_one_or_none()
        if exists is None:
            raise DenseError(
                f"Insieme di chunk inesistente: {self.chunk_set_fingerprint}."
            )
        extension_version = self.connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        if extension_version is None:
            raise DenseError("L'estensione pgvector non è abilitata.")

        self.connection.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))

        vectors = self.client.embed([query], self.config.model)
        if len(vectors) != 1:
            raise DenseError("Il provider non ha restituito un embedding per la query.")
        query_vector = tuple(float(value) for value in vectors[0])
        if len(query_vector) != self.config.dimension or not all(
            math.isfinite(value) for value in query_vector
        ):
            raise DenseError(
                f"Embedding query non valido per {self.config.model}: "
                f"attese {self.config.dimension} dimensioni finite."
            )

        parameters = {
            "fingerprint": self.chunk_set_fingerprint,
            "embedding": _vector_literal(query_vector),
            "limit": limit,
            "shortlist_limit": limit * LARGE_SHORTLIST_FACTOR,
        }
        rows = self.connection.execute(
            text(_small_query() if self.config == SMALL else _large_query()),
            parameters,
        ).mappings().all()
        exact_fallback = len(rows) < limit
        if exact_fallback:
            rows = self.connection.execute(
                text(
                    _small_exact_query()
                    if self.config == SMALL
                    else _large_exact_query()
                ),
                parameters,
            ).mappings().all()
        candidates = tuple(
            _ranked_candidate(row, rank) for rank, row in enumerate(rows, start=1)
        )
        index = (
            "hnsw/vector_ip_ops"
            if self.config == SMALL
            else "hnsw/halfvec_ip_ops con riordino vector esatto"
        )
        return Ranking(
            stage="openai-dense",
            candidates=candidates,
            configuration={
                "chunk_set_fingerprint": self.chunk_set_fingerprint,
                "model": self.config.model,
                "dimension": self.config.dimension,
                "metric": "inner_product",
                "index": index,
                "iterative_scan": "strict_order",
                "exact_fallback": exact_fallback,
                "pgvector_version": str(extension_version),
                **(
                    {"shortlist_factor": LARGE_SHORTLIST_FACTOR}
                    if self.config == LARGE
                    else {}
                ),
            },
            latency_ms=(perf_counter() - started_at) * 1000,
        )


def _ranked_candidate(row: Mapping[str, Any], rank: int) -> RankedCandidate:
    return RankedCandidate(
        candidate=Candidate(
            reference=ChunkReference(
                document_code=str(row["documento_codice"]),
                chunk_identifier=str(row["identificatore"]),
            ),
            content=str(row["contenuto"]),
            source_partitions=tuple(
                PartitionReference(
                    document_code=str(source["document_code"]),
                    partition_identifier=str(source["partition_identifier"]),
                )
                for source in row["partizioni_sorgente"]
            ),
            parent=(
                ChunkReference(
                    document_code=str(row["documento_codice"]),
                    chunk_identifier=str(row["identificatore_genitore"]),
                )
                if row["identificatore_genitore"] is not None
                else None
            ),
        ),
        score=float(row["score"]),
        rank=rank,
    )


def _small_query() -> str:
    return (
        "WITH query AS ("
        "  SELECT CAST(:embedding AS vector(1536)) AS value"
        "), top_chunks AS ("
        "  SELECT chunk.id, documento.codice AS documento_codice, "
        "         chunk.identificatore, chunk.contenuto, "
        "         genitore.identificatore AS identificatore_genitore, "
        "         -(embedding.embedding_small <#> query.value) AS score "
        "  FROM embedding_contenuti AS embedding "
        "  JOIN chunk ON chunk.sha256 = embedding.sha256_contenuto "
        "  JOIN insiemi_chunk AS insieme ON insieme.id = chunk.insieme_chunk_id "
        "  JOIN documenti AS documento ON documento.id = chunk.documento_id "
        "  LEFT JOIN chunk AS genitore ON genitore.id = chunk.chunk_genitore_id "
        "  CROSS JOIN query "
        "  WHERE insieme.fingerprint = :fingerprint "
        "    AND chunk.ruolo = 'ricercabile' "
        "    AND documento.abilitato_per_agente "
        "    AND embedding.embedding_small IS NOT NULL "
        "  ORDER BY embedding.embedding_small <#> query.value, "
        "           documento.codice, chunk.identificatore "
        "  LIMIT :limit"
        ") " + _final_select("top_chunks")
    )


def _large_query() -> str:
    return (
        "WITH shortlist AS ("
        "  SELECT chunk.id, documento.codice AS documento_codice, "
        "         chunk.identificatore, chunk.contenuto, "
        "         genitore.identificatore AS identificatore_genitore, "
        "         embedding.embedding_large "
        "  FROM embedding_contenuti AS embedding "
        "  JOIN chunk ON chunk.sha256 = embedding.sha256_contenuto "
        "  JOIN insiemi_chunk AS insieme ON insieme.id = chunk.insieme_chunk_id "
        "  JOIN documenti AS documento ON documento.id = chunk.documento_id "
        "  LEFT JOIN chunk AS genitore ON genitore.id = chunk.chunk_genitore_id "
        "  WHERE insieme.fingerprint = :fingerprint "
        "    AND chunk.ruolo = 'ricercabile' "
        "    AND documento.abilitato_per_agente "
        "    AND embedding.embedding_large IS NOT NULL "
        "  ORDER BY (embedding.embedding_large::halfvec(3072)) "
        "             <#> CAST(:embedding AS halfvec(3072)), "
        "           documento.codice, chunk.identificatore "
        "  LIMIT :shortlist_limit"
        "), top_chunks AS ("
        "  SELECT shortlist.id, shortlist.documento_codice, "
        "         shortlist.identificatore, shortlist.contenuto, "
        "         shortlist.identificatore_genitore, "
        "         -(shortlist.embedding_large "
        "           <#> CAST(:embedding AS vector(3072))) AS score "
        "  FROM shortlist "
        "  ORDER BY score DESC, shortlist.documento_codice, "
        "           shortlist.identificatore "
        "  LIMIT :limit"
        ") " + _final_select("top_chunks")
    )


def _small_exact_query() -> str:
    return _exact_query("embedding_small", 1536)


def _large_exact_query() -> str:
    return _exact_query("embedding_large", 3072)


def _exact_query(column: str, dimension: int) -> str:
    return (
        "WITH eligible AS MATERIALIZED ("
        "  SELECT chunk.id, documento.codice AS documento_codice, "
        "         chunk.identificatore, chunk.contenuto, "
        "         genitore.identificatore AS identificatore_genitore, "
        f"         embedding.{column} AS embedding_value "
        "  FROM embedding_contenuti AS embedding "
        "  JOIN chunk ON chunk.sha256 = embedding.sha256_contenuto "
        "  JOIN insiemi_chunk AS insieme ON insieme.id = chunk.insieme_chunk_id "
        "  JOIN documenti AS documento ON documento.id = chunk.documento_id "
        "  LEFT JOIN chunk AS genitore ON genitore.id = chunk.chunk_genitore_id "
        "  WHERE insieme.fingerprint = :fingerprint "
        "    AND chunk.ruolo = 'ricercabile' "
        "    AND documento.abilitato_per_agente "
        f"    AND embedding.{column} IS NOT NULL"
        "), top_chunks AS ("
        "  SELECT eligible.id, eligible.documento_codice, "
        "         eligible.identificatore, eligible.contenuto, "
        "         eligible.identificatore_genitore, "
        "         -(eligible.embedding_value "
        f"           <#> CAST(:embedding AS vector({dimension}))) AS score "
        "  FROM eligible "
        "  ORDER BY score DESC, eligible.documento_codice, "
        "           eligible.identificatore "
        "  LIMIT :limit"
        ") "
        + _final_select("top_chunks")
    )


def _final_select(source: str) -> str:
    return (
        f"SELECT {source}.id, {source}.documento_codice, "
        f"       {source}.identificatore, {source}.contenuto, "
        f"       {source}.identificatore_genitore, {source}.score, "
        "       jsonb_agg(jsonb_build_object("
        f"           'document_code', {source}.documento_codice, "
        "           'partition_identifier', fonte.identificatore_partizione"
        "       ) ORDER BY fonte.posizione) AS partizioni_sorgente "
        f"FROM {source} "
        f"JOIN chunk_partizioni AS fonte ON fonte.chunk_id = {source}.id "
        f"GROUP BY {source}.id, {source}.documento_codice, "
        f"         {source}.identificatore, {source}.contenuto, "
        f"         {source}.identificatore_genitore, {source}.score "
        f"ORDER BY {source}.score DESC, {source}.documento_codice, "
        f"         {source}.identificatore"
    )


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"

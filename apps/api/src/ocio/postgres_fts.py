"""Retrieval full-text italiano sui chunk PostgreSQL."""

from __future__ import annotations

from time import perf_counter

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ocio.retrieval import (
    Candidate,
    ChunkReference,
    PartitionReference,
    RankedCandidate,
    Ranking,
)


class PostgresFtsError(Exception):
    """La ricerca full-text non può essere eseguita."""


class PostgresFtsRetriever:
    def __init__(self, connection: Connection, chunk_set_fingerprint: str) -> None:
        self.connection = connection
        self.chunk_set_fingerprint = chunk_set_fingerprint

    def retrieve(self, query: str, limit: int) -> Ranking:
        if limit <= 0:
            raise PostgresFtsError("Il limite deve essere positivo.")

        started_at = perf_counter()
        chunk_set_exists = self.connection.execute(
            text("SELECT 1 FROM insiemi_chunk WHERE fingerprint = :fingerprint"),
            {"fingerprint": self.chunk_set_fingerprint},
        ).scalar_one_or_none()
        if chunk_set_exists is None:
            raise PostgresFtsError(
                f"Insieme di chunk inesistente: {self.chunk_set_fingerprint}."
            )

        rows = self.connection.execute(
            text(
                "WITH query AS ("
                "  SELECT websearch_to_tsquery('italian'::regconfig, :query) AS value"
                "), top_chunks AS ("
                "  SELECT chunk.id, documento.codice AS documento_codice, "
                "         chunk.identificatore, chunk.contenuto, "
                "         genitore.identificatore AS identificatore_genitore, "
                "         ts_rank_cd(chunk.vettore_ricerca, query.value) AS score "
                "  FROM chunk "
                "  JOIN insiemi_chunk AS insieme ON insieme.id = chunk.insieme_chunk_id "
                "  JOIN documenti AS documento ON documento.id = chunk.documento_id "
                "  LEFT JOIN chunk AS genitore ON genitore.id = chunk.chunk_genitore_id "
                "  CROSS JOIN query "
                "  WHERE insieme.fingerprint = :fingerprint "
                "    AND chunk.ruolo = 'ricercabile' "
                "    AND documento.abilitato_per_agente "
                "    AND chunk.vettore_ricerca @@ query.value "
                "  ORDER BY score DESC, documento.codice, chunk.identificatore "
                "  LIMIT :limit"
                ") "
                "SELECT top_chunks.id, top_chunks.documento_codice, "
                "       top_chunks.identificatore, top_chunks.contenuto, "
                "       top_chunks.identificatore_genitore, top_chunks.score, "
                "       jsonb_agg(jsonb_build_object("
                "           'document_code', top_chunks.documento_codice, "
                "           'partition_identifier', fonte.identificatore_partizione"
                "       ) ORDER BY fonte.posizione) AS partizioni_sorgente "
                "FROM top_chunks "
                "JOIN chunk_partizioni AS fonte ON fonte.chunk_id = top_chunks.id "
                "GROUP BY top_chunks.id, top_chunks.documento_codice, "
                "         top_chunks.identificatore, top_chunks.contenuto, "
                "         top_chunks.identificatore_genitore, top_chunks.score "
                "ORDER BY top_chunks.score DESC, top_chunks.documento_codice, "
                "         top_chunks.identificatore"
            ),
            {
                "fingerprint": self.chunk_set_fingerprint,
                "query": query,
                "limit": limit,
            },
        ).mappings()

        candidates = tuple(
            RankedCandidate(
                candidate=Candidate(
                    reference=ChunkReference(
                        document_code=str(row["documento_codice"]),
                        chunk_identifier=str(row["identificatore"]),
                    ),
                    content=str(row["contenuto"]),
                    source_partitions=tuple(
                        PartitionReference(
                            document_code=str(source["document_code"]),
                            partition_identifier=str(
                                source["partition_identifier"]
                            ),
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
            for rank, row in enumerate(rows, start=1)
        )
        latency_ms = (perf_counter() - started_at) * 1000
        return Ranking(
            stage="postgres-fts",
            candidates=candidates,
            configuration={
                "chunk_set_fingerprint": self.chunk_set_fingerprint,
                "dictionary": "italian",
                "query_function": "websearch_to_tsquery",
                "ranking_function": "ts_rank_cd",
            },
            latency_ms=latency_ms,
        )

"""Retrieval BM25 italiano sui chunk tramite pg_textsearch."""

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

BM25_K1 = 1.2
BM25_B = 0.75
BM25_TEXT_CONFIG = "italian"


class Bm25Error(Exception):
    """La ricerca BM25 non può essere eseguita."""


def bm25_index_name(chunk_set_id: int) -> str:
    """Return the deterministic BM25 index name for one chunk set."""
    if chunk_set_id <= 0:
        raise ValueError("chunk_set_id must be positive")
    return f"ix_chunk_contenuto_bm25_insieme_{chunk_set_id}"


def ensure_bm25_index(connection: Connection, chunk_set_id: int) -> str:
    """Create the partial BM25 index for a chunk set when absent."""
    index_name = bm25_index_name(chunk_set_id)
    connection.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            "ON chunk USING bm25 (contenuto) "
            f"WITH (text_config = '{BM25_TEXT_CONFIG}', "
            f"k1 = {BM25_K1}, b = {BM25_B}) "
            f"WHERE insieme_chunk_id = {chunk_set_id} AND ruolo = 'ricercabile'"
        )
    )
    return index_name


class Bm25Retriever:
    def __init__(self, connection: Connection, chunk_set_fingerprint: str) -> None:
        self.connection = connection
        self.chunk_set_fingerprint = chunk_set_fingerprint

    def retrieve(self, query: str, limit: int) -> Ranking:
        if limit <= 0:
            raise Bm25Error("Il limite deve essere positivo.")

        started_at = perf_counter()
        chunk_set_id = self.connection.execute(
            text("SELECT id FROM insiemi_chunk WHERE fingerprint = :fingerprint"),
            {"fingerprint": self.chunk_set_fingerprint},
        ).scalar_one_or_none()
        if chunk_set_id is None:
            raise Bm25Error(
                f"Insieme di chunk inesistente: {self.chunk_set_fingerprint}."
            )

        index_name = bm25_index_name(int(chunk_set_id))
        index_exists = self.connection.execute(
            text(
                "SELECT 1 FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'chunk' AND indexname = :index_name"
            ),
            {"index_name": index_name},
        ).scalar_one_or_none()
        if index_exists is None:
            raise Bm25Error(
                f"Indice BM25 inesistente per l'insieme "
                f"{self.chunk_set_fingerprint}: {index_name}."
            )

        extension_version = self.connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'pg_textsearch'")
        ).scalar_one_or_none()
        if extension_version is None:
            raise Bm25Error("L'estensione pg_textsearch non è abilitata.")

        rows = self.connection.execute(
            text(
                "WITH query AS ("
                "  SELECT to_bm25query(:query, :index_name) AS bm25"
                "), top_chunks AS ("
                "  SELECT chunk.id, documento.codice AS documento_codice, "
                "         chunk.identificatore, chunk.contenuto, "
                "         genitore.identificatore AS identificatore_genitore, "
                "         chunk.contenuto <@> query.bm25 AS score "
                "  FROM chunk "
                "  JOIN documenti AS documento ON documento.id = chunk.documento_id "
                "  LEFT JOIN chunk AS genitore ON genitore.id = chunk.chunk_genitore_id "
                "  CROSS JOIN query "
                "  WHERE chunk.insieme_chunk_id = :set_id "
                "    AND chunk.ruolo = 'ricercabile' "
                "    AND documento.abilitato_per_agente "
                "  ORDER BY score, documento.codice, chunk.identificatore "
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
                "ORDER BY top_chunks.score, top_chunks.documento_codice, "
                "         top_chunks.identificatore"
            ),
            {
                "set_id": int(chunk_set_id),
                "index_name": index_name,
                "query": query,
                "limit": limit,
            },
        ).mappings()

        matching_rows = (row for row in rows if float(row["score"]) < 0)
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
            for rank, row in enumerate(matching_rows, start=1)
        )
        latency_ms = (perf_counter() - started_at) * 1000
        return Ranking(
            stage="pg-textsearch-bm25",
            candidates=candidates,
            configuration={
                "chunk_set_fingerprint": self.chunk_set_fingerprint,
                "engine": "pg_textsearch",
                "extension_version": str(extension_version),
                "text_config": BM25_TEXT_CONFIG,
                "k1": BM25_K1,
                "b": BM25_B,
                "query_function": "to_bm25query",
            },
            latency_ms=latency_ms,
        )

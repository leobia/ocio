"""Test del retriever dense OpenAI/pgvector."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from ocio.database import database_url
from ocio.dense import DenseError, DenseRetriever
from ocio.embeddings import (
    LARGE,
    SMALL,
    EmbeddingClient,
    EmbeddingConfig,
    EmbeddingError,
    generate_cache,
    generate_embeddings,
    import_embeddings,
)


class FixedClient:
    def __init__(self, vector: Sequence[float]) -> None:
        self.vector = vector

    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        return [self.vector for _ in texts]


class ContentClient:
    def __init__(self, config: EmbeddingConfig, best: str) -> None:
        self.config = config
        self.best = best

    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        vectors: list[list[float]] = []
        for value in texts:
            vector = [0.0] * self.config.dimension
            vector[0 if value == self.best else 1] = 1.0
            vectors.append(vector)
        return vectors


class NoCallClient:
    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        raise AssertionError("Il provider non deve essere chiamato")


@pytest.fixture
def engine() -> Iterator[Engine]:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")
    current = create_engine(url)
    try:
        yield current
    finally:
        current.dispose()


def _insert(connection: Connection, sql: str, values: dict[str, Any]) -> int:
    return int(connection.execute(text(sql), values).scalar_one())


def _seed(engine: Engine) -> tuple[str, list[int], list[int], int, list[str]]:
    suffix = uuid4().hex
    fingerprint = ("d" + suffix).ljust(64, "0")
    hashes: list[str] = []
    with engine.begin() as connection:
        acquisition_id = _insert(
            connection,
            "INSERT INTO acquisizioni_fonti "
            "(fonte, url, contenuto, sha256, metadati) "
            "VALUES (:source, :url, 'fixture', :digest, '{}'::jsonb) RETURNING id",
            {
                "source": f"dense-{suffix}",
                "url": f"https://example.test/{suffix}",
                "digest": suffix.ljust(64, "0"),
            },
        )
        enabled = _insert(
            connection,
            "INSERT INTO documenti "
            "(codice, titolo, tipo_documento, abilitato_per_agente) "
            "VALUES (:code, 'Dense', 'atto_normativo', true) RETURNING id",
            {"code": f"a-dense-{suffix}"},
        )
        disabled = _insert(
            connection,
            "INSERT INTO documenti "
            "(codice, titolo, tipo_documento, abilitato_per_agente) "
            "VALUES (:code, 'Dense escluso', 'atto_normativo', false) RETURNING id",
            {"code": f"z-dense-{suffix}"},
        )
        set_id = _insert(
            connection,
            "INSERT INTO insiemi_chunk "
            "(strategia, revisione, configurazione, fingerprint) "
            "VALUES ('structural', 1, '{}'::jsonb, :fingerprint) RETURNING id",
            {"fingerprint": fingerprint},
        )
        parent_id = _insert_chunk(
            connection,
            set_id,
            enabled,
            acquisition_id,
            "parent/articolo",
            "parent",
            "parent",
        )
        _insert_chunk(
            connection,
            set_id,
            enabled,
            acquisition_id,
            "chunk-a",
            "ricercabile",
            "secondo",
        )
        _insert_chunk(
            connection,
            set_id,
            enabled,
            acquisition_id,
            "chunk-b",
            "ricercabile",
            "migliore",
            parent_id,
            ("articolo/comma-2", "articolo/comma-1"),
        )
        _insert_chunk(
            connection,
            set_id,
            disabled,
            acquisition_id,
            "chunk-disabilitato",
            "ricercabile",
            "escluso",
        )
        hashes.extend(
            hashlib.sha256(value.encode()).hexdigest()
            for value in ("parent", "secondo", "migliore", "escluso")
        )
    return fingerprint, [set_id], [enabled, disabled], acquisition_id, hashes


def _insert_chunk(
    connection: Connection,
    set_id: int,
    document_id: int,
    acquisition_id: int,
    identifier: str,
    role: str,
    content: str,
    parent_id: int | None = None,
    partitions: tuple[str, ...] = ("articolo",),
) -> int:
    digest = hashlib.sha256(content.encode()).hexdigest()
    chunk_id = _insert(
        connection,
        "INSERT INTO chunk "
        "(insieme_chunk_id, documento_id, chunk_genitore_id, identificatore, "
        " ruolo, ordine, contenuto, sha256) "
        "VALUES (:set_id, :document_id, :parent_id, :identifier, :role, 1, "
        "        :content, :digest) RETURNING id",
        {
            "set_id": set_id,
            "document_id": document_id,
            "parent_id": parent_id,
            "identifier": identifier,
            "role": role,
            "content": content,
            "digest": digest,
        },
    )
    for position, partition in enumerate(partitions):
        connection.execute(
            text(
                "INSERT INTO chunk_partizioni "
                "(chunk_id, posizione, acquisizione_fonte_id, "
                " identificatore_partizione, sha256_contenuto) "
                "VALUES (:chunk, :position, :acquisition, :identifier, :digest)"
            ),
            {
                "chunk": chunk_id,
                "position": position,
                "acquisition": acquisition_id,
                "identifier": partition,
                "digest": digest,
            },
        )
    return chunk_id


def _insert_distractor_embeddings(
    engine: Engine, config: EmbeddingConfig, hashes: list[str]
) -> None:
    vector = [0.0] * config.dimension
    vector[0] = 1.0
    literal = "[" + ",".join(repr(value) for value in vector) + "]"
    column = "embedding_small" if config == SMALL else "embedding_large"
    suffix = uuid4().hex
    distractors = [
        hashlib.sha256(f"distrattore-{suffix}-{index}".encode()).hexdigest()
        for index in range(128)
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO embedding_contenuti (sha256_contenuto, "
                f"{column}) VALUES (:digest, CAST(:vector AS vector))"
            ),
            [{"digest": digest, "vector": literal} for digest in distractors],
        )
    hashes.extend(distractors)


def test_non_positive_limit_is_rejected_before_embedding_the_query() -> None:
    retriever = DenseRetriever(
        cast(Connection, None),
        "fingerprint",
        SMALL,
        cast(EmbeddingClient, None),
    )

    with pytest.raises(DenseError, match="limite deve essere positivo"):
        retriever.retrieve("sicurezza", 0)


@pytest.mark.integration
@pytest.mark.parametrize("config", [SMALL, LARGE], ids=["small", "large"])
def test_import_and_retrieval_map_rank_provenance_parent_and_configuration(
    engine: Engine, tmp_path: Path, config: EmbeddingConfig
) -> None:
    fingerprint, set_ids, document_ids, acquisition_id, hashes = _seed(engine)
    cache = tmp_path / f"{config.key}.jsonl.gz"
    contents = {
        hashlib.sha256(value.encode()).hexdigest(): value
        for value in ("parent", "secondo", "migliore", "escluso")
    }
    generate_cache(
        contents,
        searchable_chunks=3,
        config=config,
        path=cache,
        client=ContentClient(config, "migliore"),
    )
    try:
        report = import_embeddings(cache)
        assert report.imported_embeddings == 4
        _insert_distractor_embeddings(engine, config, hashes)
        query = [0.0] * config.dimension
        query[0] = 1.0
        with engine.connect() as connection:
            ranking = DenseRetriever(
                connection, fingerprint, config, FixedClient(query)
            ).retrieve("query", 10)

        assert ranking.stage == "openai-dense"
        assert [candidate.rank for candidate in ranking.candidates] == [1, 2]
        assert ranking.candidates[0].candidate.reference.chunk_identifier == "chunk-b"
        assert ranking.candidates[0].candidate.parent is not None
        assert (
            ranking.candidates[0].candidate.parent.chunk_identifier == "parent/articolo"
        )
        assert [
            source.partition_identifier
            for source in ranking.candidates[0].candidate.source_partitions
        ] == ["articolo/comma-2", "articolo/comma-1"]
        assert ranking.configuration["model"] == config.model
        assert ranking.configuration["dimension"] == config.dimension
        assert ranking.configuration["metric"] == "inner_product"
        assert ranking.configuration["iterative_scan"] == "strict_order"
        assert ranking.configuration["exact_fallback"] is True
        assert ranking.configuration["pgvector_version"]
        assert math.isfinite(ranking.latency_ms)

        if config == LARGE:
            vector_literal = "[" + ",".join(repr(value) for value in query) + "]"
            with engine.connect() as connection:
                exact = connection.execute(
                    text(
                        "SELECT chunk.identificatore FROM chunk "
                        "JOIN insiemi_chunk AS insieme "
                        "  ON insieme.id = chunk.insieme_chunk_id "
                        "JOIN documenti AS documento ON documento.id = chunk.documento_id "
                        "JOIN embedding_contenuti AS embedding "
                        "  ON embedding.sha256_contenuto = chunk.sha256 "
                        "WHERE insieme.fingerprint = :fingerprint "
                        "  AND chunk.ruolo = 'ricercabile' "
                        "  AND documento.abilitato_per_agente "
                        "ORDER BY embedding.embedding_large "
                        "         <#> CAST(:vector AS vector(3072)), "
                        "         documento.codice, chunk.identificatore"
                    ),
                    {"fingerprint": fingerprint, "vector": vector_literal},
                ).scalars()
                assert [
                    item.candidate.reference.chunk_identifier
                    for item in ranking.candidates
                ] == list(exact)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM embedding_contenuti "
                    "WHERE sha256_contenuto = ANY(:hashes)"
                ),
                {"hashes": hashes},
            )
        import_embeddings(cache)
        with engine.connect() as connection:
            rebuilt = DenseRetriever(
                connection, fingerprint, config, FixedClient(query)
            ).retrieve("query", 10)
        assert [item.candidate.reference for item in rebuilt.candidates] == [
            item.candidate.reference for item in ranking.candidates
        ]
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM insiemi_chunk WHERE id = ANY(:ids)"),
                {"ids": set_ids},
            )
            connection.execute(
                text("DELETE FROM documenti WHERE id = ANY(:ids)"),
                {"ids": document_ids},
            )
            connection.execute(
                text("DELETE FROM acquisizioni_fonti WHERE id = :id"),
                {"id": acquisition_id},
            )
            connection.execute(
                text(
                    "DELETE FROM embedding_contenuti WHERE sha256_contenuto = ANY(:hashes)"
                ),
                {"hashes": hashes},
            )


@pytest.mark.integration
def test_hnsw_indexes_are_available_to_the_query_planner(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        small_plan = "\n".join(
            connection.execute(
                text(
                    "EXPLAIN SELECT sha256_contenuto FROM embedding_contenuti "
                    "WHERE embedding_small IS NOT NULL "
                    "ORDER BY embedding_small <#> "
                    "(array_fill(0::real, ARRAY[1536]))::vector(1536) LIMIT 5"
                )
            ).scalars()
        )
        large_plan = "\n".join(
            connection.execute(
                text(
                    "EXPLAIN SELECT sha256_contenuto FROM embedding_contenuti "
                    "WHERE embedding_large IS NOT NULL "
                    "ORDER BY (embedding_large::halfvec(3072)) <#> "
                    "(array_fill(0::real, ARRAY[3072]))::halfvec(3072) LIMIT 5"
                )
            ).scalars()
        )

    assert "ix_embedding_contenuti_small_hnsw" in small_plan
    assert "ix_embedding_contenuti_large_halfvec_hnsw" in large_plan


@pytest.mark.integration
def test_generation_includes_disabled_documents_and_reuses_across_sets(
    engine: Engine, tmp_path: Path
) -> None:
    fingerprint, set_ids, document_ids, acquisition_id, hashes = _seed(engine)
    cache = tmp_path / "small.jsonl.gz"
    try:
        first = generate_embeddings(
            fingerprint,
            SMALL,
            path=cache,
            client=ContentClient(SMALL, "migliore"),
        )
        assert (first.searchable_chunks, first.unique_contents) == (3, 3)
        assert (first.reused_embeddings, first.created_embeddings) == (0, 3)

        other_fingerprint = ("e" + uuid4().hex).ljust(64, "0")
        with engine.begin() as connection:
            other_set = _insert(
                connection,
                "INSERT INTO insiemi_chunk "
                "(strategia, revisione, configurazione, fingerprint) "
                "VALUES ('structural', 1, '{}'::jsonb, :fingerprint) RETURNING id",
                {"fingerprint": other_fingerprint},
            )
            set_ids.append(other_set)
            _insert_chunk(
                connection,
                other_set,
                document_ids[0],
                acquisition_id,
                "chunk-riusato",
                "ricercabile",
                "migliore",
            )

        reused = generate_embeddings(
            other_fingerprint,
            SMALL,
            path=cache,
            client=NoCallClient(),
        )
        assert (reused.searchable_chunks, reused.unique_contents) == (1, 1)
        assert (reused.reused_embeddings, reused.created_embeddings) == (1, 0)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM insiemi_chunk WHERE id = ANY(:ids)"),
                {"ids": set_ids},
            )
            connection.execute(
                text("DELETE FROM documenti WHERE id = ANY(:ids)"),
                {"ids": document_ids},
            )
            connection.execute(
                text("DELETE FROM acquisizioni_fonti WHERE id = :id"),
                {"id": acquisition_id},
            )
            connection.execute(
                text(
                    "DELETE FROM embedding_contenuti "
                    "WHERE sha256_contenuto = ANY(:hashes)"
                ),
                {"hashes": hashes},
            )


@pytest.mark.integration
def test_import_rejects_a_different_vector_for_the_same_model(
    engine: Engine, tmp_path: Path
) -> None:
    content = "immutabile"
    digest = hashlib.sha256(content.encode()).hexdigest()
    first = tmp_path / "first.jsonl.gz"
    different = tmp_path / "different.jsonl.gz"
    generate_cache(
        {digest: content},
        searchable_chunks=1,
        config=SMALL,
        path=first,
        client=ContentClient(SMALL, content),
    )
    generate_cache(
        {digest: content},
        searchable_chunks=1,
        config=SMALL,
        path=different,
        client=ContentClient(SMALL, "altro"),
    )
    try:
        import_embeddings(first)
        with pytest.raises(EmbeddingError, match="vettore diverso"):
            import_embeddings(different)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM embedding_contenuti WHERE sha256_contenuto = :digest"
                ),
                {"digest": digest},
            )

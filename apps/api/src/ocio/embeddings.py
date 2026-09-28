"""Generazione, validazione e importazione degli embedding OpenAI."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from openai import OpenAI, OpenAIError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.database import database_url

CACHE_SCHEMA_VERSION = 1


class EmbeddingError(Exception):
    """La cache o la generazione degli embedding non è valida."""


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    key: str
    model: str
    dimension: int


SMALL = EmbeddingConfig("small", "text-embedding-3-small", 1536)
LARGE = EmbeddingConfig("large", "text-embedding-3-large", 3072)
CONFIGS = {config.key: config for config in (SMALL, LARGE)}


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    sha256: str
    model: str
    dimension: int
    vector: tuple[float, ...]
    schema_version: int = CACHE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class EmbeddingReport:
    searchable_chunks: int
    unique_contents: int
    reused_embeddings: int
    created_embeddings: int
    cache_path: Path


@dataclass(frozen=True, slots=True)
class EmbeddingImportReport:
    model: str
    dimension: int
    imported_embeddings: int


class EmbeddingClient(Protocol):
    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]: ...


class OpenAIEmbeddingClient:
    """Adapter minimo per l'endpoint Embeddings di OpenAI."""

    def __init__(self, *, timeout: float | None = None, max_retries: int = 2) -> None:
        self._client = OpenAI(timeout=timeout, max_retries=max_retries)

    def embed(self, texts: Sequence[str], model: str) -> Sequence[Sequence[float]]:
        try:
            response = self._client.embeddings.create(
                input=list(texts), model=model, encoding_format="float"
            )
        except OpenAIError as error:
            raise EmbeddingError(f"Generazione OpenAI fallita: {error}") from error
        return [
            item.embedding
            for item in sorted(response.data, key=lambda item: item.index)
        ]


def default_cache_path(config: EmbeddingConfig) -> Path:
    """Restituisce il percorso portabile predefinito per modello e dimensione."""
    repository = Path(__file__).resolve().parents[4]
    return (
        repository
        / "artifacts"
        / "embeddings"
        / f"{config.model}-{config.dimension}.jsonl.gz"
    )


def load_cache(path: Path, config: EmbeddingConfig) -> dict[str, EmbeddingRecord]:
    """Legge e valida tutti i record di una cache, se presente."""
    if not path.exists():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            lines = source.read().splitlines()
    except (OSError, EOFError) as error:
        raise EmbeddingError(f"Cache non leggibile: {path}: {error}") from error

    records: dict[str, EmbeddingRecord] = {}
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
            record = EmbeddingRecord(
                schema_version=int(value["schema_version"]),
                sha256=str(value["sha256"]),
                model=str(value["model"]),
                dimension=int(value["dimension"]),
                vector=tuple(float(item) for item in value["vector"]),
            )
            _validate_record(record, config)
            if record.sha256 in records:
                raise ValueError(f"SHA-256 duplicato: {record.sha256}")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise EmbeddingError(
                f"Cache non valida alla riga {line_number}: {error}"
            ) from error
        records[record.sha256] = record
    return records


def generate_cache(
    contents: Mapping[str, str],
    *,
    searchable_chunks: int,
    config: EmbeddingConfig,
    path: Path,
    client: EmbeddingClient,
    batch_size: int = 100,
) -> EmbeddingReport:
    """Aggiunge alla cache soltanto gli embedding mancanti."""
    if batch_size <= 0:
        raise EmbeddingError("La dimensione del batch deve essere positiva.")
    _validate_contents(contents)
    records = load_cache(path, config)
    missing = sorted(set(contents) - set(records))
    for start in range(0, len(missing), batch_size):
        batch_hashes = missing[start : start + batch_size]
        vectors = client.embed(
            [contents[digest] for digest in batch_hashes], config.model
        )
        if len(vectors) != len(batch_hashes):
            raise EmbeddingError(
                "Il provider ha restituito un numero errato di vettori."
            )
        for digest, vector in zip(batch_hashes, vectors, strict=True):
            record = EmbeddingRecord(
                sha256=digest,
                model=config.model,
                dimension=config.dimension,
                vector=tuple(float(value) for value in vector),
            )
            try:
                _validate_record(record, config)
            except ValueError as error:
                raise EmbeddingError(
                    f"Il provider ha restituito un vettore non valido: {error}"
                ) from error
            records[digest] = record
    if missing or not path.exists():
        _write_cache(path, records.values())
    return EmbeddingReport(
        searchable_chunks=searchable_chunks,
        unique_contents=len(contents),
        reused_embeddings=len(contents) - len(missing),
        created_embeddings=len(missing),
        cache_path=path,
    )


def generate_embeddings(
    fingerprint: str,
    config: EmbeddingConfig,
    *,
    client: EmbeddingClient | None = None,
    path: Path | None = None,
    batch_size: int = 100,
) -> EmbeddingReport:
    """Genera la cache per i chunk ricercabili di un insieme esistente."""
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise EmbeddingError(str(error)) from error
    try:
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT chunk.sha256, chunk.contenuto "
                        "FROM chunk "
                        "JOIN insiemi_chunk AS insieme "
                        "  ON insieme.id = chunk.insieme_chunk_id "
                        "WHERE insieme.fingerprint = :fingerprint "
                        "  AND chunk.ruolo = 'ricercabile' "
                        "ORDER BY chunk.sha256"
                    ),
                    {"fingerprint": fingerprint},
                )
                .mappings()
                .all()
            )
            exists = connection.execute(
                text("SELECT 1 FROM insiemi_chunk WHERE fingerprint = :fingerprint"),
                {"fingerprint": fingerprint},
            ).scalar_one_or_none()
        if exists is None:
            raise EmbeddingError(f"Insieme di chunk inesistente: {fingerprint}.")
        contents: dict[str, str] = {}
        for row in rows:
            digest = str(row["sha256"])
            content = str(row["contenuto"])
            previous = contents.setdefault(digest, content)
            if previous != content:
                raise EmbeddingError(
                    f"Contenuti diversi condividono lo SHA-256 {digest}."
                )
        return generate_cache(
            contents,
            searchable_chunks=len(rows),
            config=config,
            path=path or default_cache_path(config),
            client=client or OpenAIEmbeddingClient(),
            batch_size=batch_size,
        )
    finally:
        engine.dispose()


def import_embeddings(path: Path) -> EmbeddingImportReport:
    """Importa una cache validata senza creare un client OpenAI."""
    config = identify_cache(path)
    records = load_cache(path, config)
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise EmbeddingError(str(error)) from error
    try:
        with engine.begin() as connection:
            _import_records(connection, records.values(), config)
    finally:
        engine.dispose()
    return EmbeddingImportReport(config.model, config.dimension, len(records))


def identify_cache(path: Path) -> EmbeddingConfig:
    """Identifica una cache tramite modello e dimensione del primo record."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            first_line = source.readline()
        if not first_line:
            raise EmbeddingError(f"La cache è vuota: {path}.")
        value = json.loads(first_line)
        model = str(value["model"])
        dimension = int(value["dimension"])
    except EmbeddingError:
        raise
    except (
        OSError,
        EOFError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise EmbeddingError(f"Cache non identificabile: {path}: {error}") from error
    for config in CONFIGS.values():
        if (model, dimension) == (config.model, config.dimension):
            return config
    raise EmbeddingError(
        f"Modello o dimensione della cache non supportati: {model}/{dimension}."
    )


def _import_records(
    connection: Connection,
    records: Iterable[EmbeddingRecord],
    config: EmbeddingConfig,
) -> None:
    column = "embedding_small" if config == SMALL else "embedding_large"
    for record in records:
        result = connection.execute(
            text(
                "INSERT INTO embedding_contenuti (sha256_contenuto, "
                f"{column}) VALUES (:sha256, CAST(:vector AS vector)) "
                "ON CONFLICT (sha256_contenuto) DO UPDATE SET "
                f"{column} = EXCLUDED.{column} "
                f"WHERE embedding_contenuti.{column} IS NULL "
                f"   OR embedding_contenuti.{column} = EXCLUDED.{column} "
                "RETURNING sha256_contenuto"
            ),
            {"sha256": record.sha256, "vector": _vector_literal(record.vector)},
        ).scalar_one_or_none()
        if result is None:
            raise EmbeddingError(
                "Il database contiene un vettore diverso per "
                f"{record.sha256} e {config.model}."
            )


def _validate_contents(contents: Mapping[str, str]) -> None:
    for digest, content in contents.items():
        actual = hashlib.sha256(content.encode()).hexdigest()
        if digest != actual:
            raise EmbeddingError(f"SHA-256 non coerente col contenuto: {digest}.")


def _validate_record(record: EmbeddingRecord, config: EmbeddingConfig) -> None:
    if record.schema_version != CACHE_SCHEMA_VERSION:
        raise ValueError(f"versione schema non supportata: {record.schema_version}")
    if len(record.sha256) != 64 or any(
        character not in "0123456789abcdef" for character in record.sha256
    ):
        raise ValueError(f"SHA-256 non valido: {record.sha256}")
    if record.model != config.model or record.dimension != config.dimension:
        raise ValueError("modello o dimensione non corrispondono alla cache")
    if len(record.vector) != config.dimension:
        raise ValueError(
            f"il vettore deve avere {config.dimension} dimensioni, "
            f"non {len(record.vector)}"
        )
    if not all(math.isfinite(value) for value in record.vector):
        raise ValueError("il vettore contiene valori non finiti")


def _write_cache(path: Path, records: Iterable[EmbeddingRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record.sha256)
    payload = "".join(
        json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in ordered
    ).encode()
    compressed = gzip.compress(payload, mtime=0)
    temporary_path: Path | None = None
    try:
        # Il file temporaneo è nello stesso filesystem per rendere atomico os.replace.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(compressed)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise EmbeddingError(f"Cache non scrivibile: {path}: {error}") from error


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"

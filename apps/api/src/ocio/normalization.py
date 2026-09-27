"""Coordina i parser e salva documenti e partizioni in modo idempotente."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.acquisition import (
    AcquisitionError,
    SourceAcquisition,
    read_source_acquisitions,
)
from ocio.database import database_url
from ocio.parsers.akn import parse_akn
from ocio.parsers.html import parse_html
from ocio.parsers.pdf import parse_pdf
from ocio.parsing import ParseAnomaly, ParsedDocument


class NormalizationError(Exception):
    """The local corpus cannot be normalized or stored completely."""


@dataclass(frozen=True, slots=True)
class NormalizationReport:
    documenti: int
    acquisizioni: int
    partizioni: int
    non_classificate: int
    anomalie: tuple[ParseAnomaly, ...]


def parse_acquisitions(
    acquisitions: tuple[SourceAcquisition, ...],
) -> tuple[ParsedDocument, ...]:
    grouped_html: defaultdict[str, list[SourceAcquisition]] = defaultdict(list)
    parsed: list[ParsedDocument] = []
    for acquisition in acquisitions:
        metadata = json.loads(acquisition.metadata)
        if not isinstance(metadata, dict):
            raise NormalizationError(
                f"{acquisition.local_path}: metadati di acquisizione non validi."
            )
        try:
            if acquisition.format == "akn_xml":
                parsed.append(parse_akn(acquisition, metadata))
            elif acquisition.format == "html":
                grouped_html[acquisition.document_id].append(acquisition)
            elif acquisition.format == "pdf":
                parsed.extend(parse_pdf(acquisition, metadata))
            else:
                raise NormalizationError(
                    f"{acquisition.local_path}: formato non supportato "
                    f"{acquisition.format!r}."
                )
        except (ValueError, TypeError, KeyError) as error:
            raise NormalizationError(str(error)) from error

    for group in grouped_html.values():
        try:
            parsed.append(parse_html(group))
        except (ValueError, TypeError, KeyError) as error:
            raise NormalizationError(str(error)) from error

    document_codes = [document.codice for document in parsed]
    if len(set(document_codes)) != len(document_codes):
        raise NormalizationError("Il parsing ha prodotto codici documento duplicati.")
    for document in parsed:
        identifiers = [partition.identifier for partition in document.partizioni]
        if len(set(identifiers)) != len(identifiers):
            raise NormalizationError(
                f"{document.codice}: il parsing ha prodotto identificatori di partizione duplicati."
            )
    return tuple(parsed)


def _imported_acquisition_ids(
    connection: Connection,
    acquisitions: tuple[SourceAcquisition, ...],
) -> dict[str, int]:
    ids: dict[str, int] = {}
    for acquisition in acquisitions:
        row = connection.execute(
            text(
                "SELECT id, contenuto FROM acquisizioni_fonti "
                "WHERE fonte = :provider AND sha256 = :digest"
            ),
            {"provider": acquisition.provider, "digest": acquisition.digest},
        ).one_or_none()
        if row is None:
            raise NormalizationError(
                f"Acquisizione non importata: {acquisition.local_path}. "
                "Esegui prima `ocio importa-corpus`."
            )
        stored_digest = hashlib.sha256(bytes(row.contenuto)).hexdigest()
        if stored_digest != acquisition.digest:
            raise NormalizationError(
                f"{acquisition.local_path}: il contenuto dell'acquisizione nel "
                "database non corrisponde al suo SHA-256."
            )
        ids[acquisition.local_path] = int(row.id)
    return ids


def _upsert_document(connection: Connection, document: ParsedDocument) -> int:
    result = connection.execute(
        text(
            "INSERT INTO documenti "
            "(codice, tipo_documento, titolo, urn, vigente_dal, vigente_al, "
            " snapshot_al, pubblicato_il) "
            "VALUES (:codice, :tipo, :titolo, :urn, :vigente_dal, :vigente_al, "
            " :snapshot_al, :pubblicato_il) "
            "ON CONFLICT (codice) DO UPDATE SET "
            "tipo_documento = EXCLUDED.tipo_documento, "
            "titolo = EXCLUDED.titolo, urn = EXCLUDED.urn, "
            "vigente_dal = EXCLUDED.vigente_dal, vigente_al = EXCLUDED.vigente_al, "
            "snapshot_al = EXCLUDED.snapshot_al, pubblicato_il = EXCLUDED.pubblicato_il "
            "RETURNING id"
        ),
        {
            "codice": document.codice,
            "tipo": document.tipo_documento,
            "titolo": document.titolo,
            "urn": document.urn,
            "vigente_dal": document.vigente_dal,
            "vigente_al": document.vigente_al,
            "snapshot_al": document.snapshot_al,
            "pubblicato_il": document.pubblicato_il,
        },
    )
    return int(result.scalar_one())


def _store_document(
    connection: Connection,
    document: ParsedDocument,
    acquisition_ids: dict[str, int],
) -> None:
    document_id = _upsert_document(connection, document)
    seen: set[str] = set()
    partition_ids: dict[str, int] = {}
    for partition in document.partizioni:
        source_path = partition.localizzatore.get("local_path")
        if not isinstance(source_path, str) or source_path not in acquisition_ids:
            raise NormalizationError(
                f"{document.codice}/{partition.identifier}: acquisizione di origine "
                "non determinabile dal localizzatore."
            )
        parent_id = (
            partition_ids.get(partition.genitore) if partition.genitore else None
        )
        if partition.genitore and parent_id is None:
            raise NormalizationError(
                f"{document.codice}/{partition.identifier}: genitore "
                f"{partition.genitore!r} non ancora inserito."
            )
        result = connection.execute(
            text(
                "INSERT INTO partizioni_documentali "
                "(documento_id, partizione_genitore_id, acquisizione_fonte_id, "
                " identificatore, tipo, marcatore, rubrica, ordine, contenuto, localizzatore, "
                " vigente_dal, vigente_al) "
                "VALUES (:documento_id, :parent_id, :acquisition_id, :identifier, "
                " :tipo, :marcatore, :rubrica, :ordine, :contenuto, "
                " CAST(:localizzatore AS jsonb), "
                " :vigente_dal, :vigente_al) "
                "ON CONFLICT (documento_id, identificatore) DO UPDATE SET "
                "partizione_genitore_id = EXCLUDED.partizione_genitore_id, "
                "acquisizione_fonte_id = EXCLUDED.acquisizione_fonte_id, "
                "tipo = EXCLUDED.tipo, marcatore = EXCLUDED.marcatore, "
                "rubrica = EXCLUDED.rubrica, "
                "ordine = EXCLUDED.ordine, contenuto = EXCLUDED.contenuto, "
                "localizzatore = EXCLUDED.localizzatore, "
                "vigente_dal = EXCLUDED.vigente_dal, vigente_al = EXCLUDED.vigente_al "
                "RETURNING id"
            ),
            {
                "documento_id": document_id,
                "parent_id": parent_id,
                "acquisition_id": acquisition_ids[source_path],
                "identifier": partition.identifier,
                "tipo": partition.tipo,
                "marcatore": partition.marcatore,
                "rubrica": partition.rubrica,
                "ordine": partition.ordine,
                "contenuto": partition.contenuto,
                "localizzatore": json.dumps(
                    partition.localizzatore, ensure_ascii=False
                ),
                "vigente_dal": partition.vigente_dal,
                "vigente_al": partition.vigente_al,
            },
        )
        partition_ids[partition.identifier] = int(result.scalar_one())
        seen.add(partition.identifier)

    old_identifiers: Sequence[str] = (
        connection.execute(
            text(
                "SELECT identificatore FROM partizioni_documentali "
                "WHERE documento_id = :documento_id"
            ),
            {"documento_id": document_id},
        )
        .scalars()
        .all()
    )
    for old_identifier in old_identifiers:
        if old_identifier not in seen:
            connection.execute(
                text(
                    "DELETE FROM partizioni_documentali "
                    "WHERE documento_id = :documento_id AND identificatore = :identifier"
                ),
                {"documento_id": document_id, "identifier": old_identifier},
            )


def normalize_corpus(sources: Path) -> NormalizationReport:
    """Parse local sources and atomically upsert their current document structures."""
    try:
        acquisitions = read_source_acquisitions(sources)
        documents = parse_acquisitions(acquisitions)
        engine = create_engine(database_url())
    except (AcquisitionError, RuntimeError) as error:
        raise NormalizationError(str(error)) from error

    try:
        with engine.begin() as connection:
            acquisition_ids = _imported_acquisition_ids(connection, acquisitions)
            for document in documents:
                _store_document(connection, document, acquisition_ids)
    finally:
        engine.dispose()

    partitions = tuple(
        partition for document in documents for partition in document.partizioni
    )
    anomalies = tuple(
        anomaly for document in documents for anomaly in document.anomalie
    )
    return NormalizationReport(
        documenti=len(documents),
        acquisizioni=len(acquisitions),
        partizioni=len(partitions),
        non_classificate=sum(
            partition.tipo == "non_classificata" for partition in partitions
        ),
        anomalie=anomalies,
    )


def format_report(report: NormalizationReport) -> str:
    """Render concise counts followed by every known parsing degradation."""
    lines = [
        f"Corpus normalizzato: {report.documenti} documenti, "
        f"{report.acquisizioni} acquisizioni, {report.partizioni} partizioni.",
        f"Partizioni non classificate: {report.non_classificate}; anomalie: {len(report.anomalie)}.",
    ]
    for anomaly in report.anomalie:
        location = f" pagina {anomaly.page}" if anomaly.page is not None else ""
        lines.append(f"- {anomaly.source}{location}: {anomaly.message}")
    return "\n".join(lines)

"""Import verified, versioned source files from the local corpus."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import yaml
from sqlalchemy import create_engine, text

from ocio.database import database_url

AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
PROVIDER_NAMES = {
    "normattiva": "Normattiva",
    "gazzetta": "Gazzetta Ufficiale",
    "mlps": "Ministero del Lavoro",
    "vvf": "Vigili del Fuoco",
    "stato_regioni": "Conferenza Stato-Regioni",
}


class AcquisitionError(Exception):
    """A local source acquisition cannot be safely imported."""


@dataclass(frozen=True, slots=True)
class SourceAcquisition:
    """A verified repository file and metadata ready to be copied into the database."""

    document_id: str
    provider: str
    source_url: str
    local_path: str
    format: str
    acquired_on: date
    digest: str
    content: bytes
    metadata: str


def _validate_format(document_id: str, source_format: str, payload: bytes) -> None:
    if source_format == "akn_xml":
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as error:
            raise AcquisitionError(
                f"{document_id}: il file dichiarato AKN XML non è XML valido."
            ) from error
        if root.tag != f"{AKN}akomaNtoso":
            raise AcquisitionError(f"{document_id}: formato inatteso, atteso AKN XML.")
        return

    if source_format == "html":
        try:
            content = payload.decode("utf-8-sig").lower()
        except UnicodeDecodeError as error:
            raise AcquisitionError(
                f"{document_id}: il file dichiarato HTML non è UTF-8 valido."
            ) from error
        if "<html" not in content[:8192]:
            raise AcquisitionError(f"{document_id}: formato inatteso, atteso HTML.")
        return

    if source_format == "pdf":
        if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-1024:]:
            raise AcquisitionError(f"{document_id}: formato inatteso, atteso PDF.")
        return

    raise AcquisitionError(f"{document_id}: formato non supportato: {source_format!r}.")


def read_source_acquisitions(sources: Path) -> tuple[SourceAcquisition, ...]:
    """Read and verify all seed documents without accessing the network."""
    try:
        registry = yaml.safe_load(sources.read_text(encoding="utf-8"))
        documents = registry["seed_documents"]
        if not isinstance(documents, list) or not documents:
            raise AcquisitionError(
                "ocio_sources.yaml non contiene seed_documents validi."
            )
        root = sources.resolve().parent
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError) as error:
        raise AcquisitionError(f"Registro fonti non valido: {sources}") from error

    acquisitions: list[SourceAcquisition] = []
    seen_ids: set[str] = set()
    for document in documents:
        try:
            document_id = document["id"]
            provider = document["primary_provider"]
        except (KeyError, TypeError, ValueError) as error:
            raise AcquisitionError(
                "Metadati di un seed document mancanti o non validi."
            ) from error

        if (
            not isinstance(document_id, str)
            or not document_id
            or document_id in seen_ids
        ):
            raise AcquisitionError(
                f"Identificatore di documento mancante o duplicato: {document_id!r}."
            )
        seen_ids.add(document_id)
        if not isinstance(provider, str) or provider not in PROVIDER_NAMES:
            raise AcquisitionError(
                f"{document_id}: provider non riconosciuto: {provider!r}."
            )
        declared_acquisitions = document.get("acquisitions")
        if declared_acquisitions is None:
            declared_acquisitions = [document]
        if not isinstance(declared_acquisitions, list) or not declared_acquisitions:
            raise AcquisitionError(
                f"{document_id}: acquisitions deve contenere almeno un file."
            )

        for declared_acquisition in declared_acquisitions:
            if not isinstance(declared_acquisition, dict):
                raise AcquisitionError(
                    f"{document_id}: metadati di acquisizione non validi."
                )
            entry = {
                key: value for key, value in document.items() if key != "acquisitions"
            }
            entry.update(declared_acquisition)
            try:
                source_url = entry["source"]
                configured_path = Path(entry["local_path"])
                source_format = entry["format"]
                acquired_on = date.fromisoformat(entry["acquired_on"])
                expected_digest = entry["sha256"]
            except (KeyError, TypeError, ValueError) as error:
                raise AcquisitionError(
                    f"{document_id}: metadati di acquisizione mancanti o non validi."
                ) from error

            try:
                valid_source_url = isinstance(source_url, str) and urlsplit(
                    source_url
                ).scheme in ("http", "https")
            except ValueError:
                valid_source_url = False
            if not valid_source_url:
                raise AcquisitionError(f"{document_id}: URL della fonte non valido.")
            if not isinstance(configured_path, Path) or configured_path.is_absolute():
                raise AcquisitionError(
                    f"{document_id}: local_path deve essere relativo al registro."
                )
            if not isinstance(source_format, str):
                raise AcquisitionError(
                    f"{document_id}: formato della fonte non valido."
                )
            if (
                not isinstance(expected_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
            ):
                raise AcquisitionError(
                    f"{document_id}: SHA-256 non valido in ocio_sources.yaml."
                )

            source_path = (root / configured_path).resolve()
            try:
                source_path.relative_to(root)
            except ValueError as error:
                raise AcquisitionError(
                    f"{document_id}: local_path deve restare sotto {root}."
                ) from error
            try:
                payload = source_path.read_bytes()
            except OSError as error:
                raise AcquisitionError(
                    f"{document_id}: file locale mancante o non leggibile: {configured_path}."
                ) from error

            actual_digest = hashlib.sha256(payload).hexdigest()
            if actual_digest != expected_digest:
                raise AcquisitionError(
                    f"{document_id}: SHA-256 diverso da ocio_sources.yaml "
                    f"(atteso {expected_digest}, trovato {actual_digest})."
                )
            _validate_format(document_id, source_format, payload)
            for validity_field in ("vigente_dal", "vigente_al"):
                value = entry.get(validity_field)
                if value is not None and (
                    not isinstance(value, str) or _isodate(value) is None
                ):
                    raise AcquisitionError(
                        f"{document_id}: {validity_field} deve essere una data ISO."
                    )

            if entry.get("vigente_dal") and entry.get("vigente_al"):
                if date.fromisoformat(entry["vigente_al"]) <= date.fromisoformat(
                    entry["vigente_dal"]
                ):
                    raise AcquisitionError(
                        f"{document_id}: intervallo di vigenza non valido."
                    )

            metadata = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            acquisitions.append(
                SourceAcquisition(
                    document_id=document_id,
                    provider=PROVIDER_NAMES[provider],
                    source_url=source_url,
                    local_path=configured_path.as_posix(),
                    format=source_format,
                    acquired_on=acquired_on,
                    digest=actual_digest,
                    content=payload,
                    metadata=metadata,
                )
            )

    return tuple(acquisitions)


def _isodate(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def import_source_acquisitions(sources: Path) -> int:
    """Store verified local files in the database, keyed by provider and hash."""
    acquisitions = read_source_acquisitions(sources)
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise AcquisitionError(str(error)) from error

    try:
        with engine.begin() as connection:
            for acquisition in acquisitions:
                acquired_at = datetime.combine(
                    acquisition.acquired_on, datetime.min.time(), tzinfo=UTC
                )
                connection.execute(
                    text(
                        "INSERT INTO acquisizioni_fonti "
                        "(fonte, url, contenuto, sha256, acquisita_il, metadati) "
                        "VALUES (:provider, :url, :content, :digest, :acquired_at, "
                        "CAST(:metadata AS jsonb)) "
                        "ON CONFLICT (fonte, sha256) DO NOTHING"
                    ),
                    {
                        "provider": acquisition.provider,
                        "url": acquisition.source_url,
                        "content": acquisition.content,
                        "digest": acquisition.digest,
                        "acquired_at": acquired_at,
                        "metadata": acquisition.metadata,
                    },
                )
    finally:
        engine.dispose()
    return len(acquisitions)

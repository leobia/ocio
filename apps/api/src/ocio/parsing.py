"""Definisce modelli e funzioni condivisi dai parser del corpus."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedPartition:
    """One current, addressable unit in a document's structure."""

    identifier: str
    tipo: str
    ordine: int
    contenuto: str
    marcatore: str | None = None
    genitore: str | None = None
    rubrica: str | None = None
    localizzatore: dict[str, Any] = field(default_factory=dict)
    vigente_dal: date | None = None
    vigente_al: date | None = None


def legal_marker(kind: str, label: str) -> str | None:
    """Estrae il marcatore giuridico senza dipendere dal formato della fonte."""
    patterns = {
        "articolo": r"(?:art(?:icolo)?)[._\s-]*(\d+(?:-(?:bis|ter|quater))?)",
        "comma": r"(?:comma|para)[._\s-]*(\d+(?:-(?:bis|ter|quater))?)",
        "lettera": r"(?:lettera|point)[._\s-]*([a-z])",
    }
    pattern = patterns.get(kind)
    if pattern:
        match = re.search(pattern, label, re.IGNORECASE)
        if match:
            return match.group(1).casefold()

    cleaned = label.casefold().strip().strip("(). ")
    if kind == "articolo" and re.fullmatch(r"\d+(?:-(?:bis|ter|quater))?", cleaned):
        return cleaned
    if kind == "comma" and re.fullmatch(r"\d+(?:-(?:bis|ter|quater))?", cleaned):
        return cleaned
    if kind == "lettera" and re.fullmatch(r"[a-z]", cleaned):
        return cleaned
    return None


@dataclass(frozen=True, slots=True)
class ParseAnomaly:
    """A recoverable parsing degradation with a source location."""

    message: str
    source: str
    page: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """The current parsed representation of one logical source document."""

    codice: str
    titolo: str
    tipo_documento: str
    urn: str | None
    vigente_dal: date | None
    vigente_al: date | None
    snapshot_al: date | None
    pubblicato_il: date | None
    partizioni: tuple[ParsedPartition, ...]
    anomalie: tuple[ParseAnomaly, ...] = ()


def normalize_whitespace(value: str) -> str:
    """Normalize spacing while retaining paragraph boundaries."""
    paragraphs = [
        " ".join(" ".join(line.split()) for line in block.splitlines())
        for block in value.split("\n\n")
    ]
    return "\n\n".join(
        paragraph.strip() for paragraph in paragraphs if paragraph.strip()
    )


def parse_iso_date(value: object) -> date | None:
    """Read an optional ISO date from source metadata."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def document_from_metadata(
    document_id: str,
    metadata: dict[str, object],
    partizioni: tuple[ParsedPartition, ...],
    *,
    codice: str | None = None,
    titolo: str | None = None,
    tipo_documento: str = "atto_normativo",
    urn: str | None = None,
    vigenza: str | None = None,
    anomalie: tuple[ParseAnomaly, ...] = (),
) -> ParsedDocument:
    """Build a parsed document from the registry metadata shared by all formats."""
    configured_title = titolo or metadata.get("title")
    validity_metadata = metadata.get("vigenza_per_decreto")
    effective_from = (
        validity_metadata.get(vigenza)
        if vigenza and isinstance(validity_metadata, dict)
        else metadata.get("vigente_dal")
    )
    return ParsedDocument(
        codice=codice or document_id,
        titolo=configured_title if isinstance(configured_title, str) else document_id,
        tipo_documento=tipo_documento,
        urn=urn,
        vigente_dal=parse_iso_date(effective_from),
        vigente_al=parse_iso_date(metadata.get("vigente_al")),
        snapshot_al=parse_iso_date(metadata.get("snapshot_as_of")),
        pubblicato_il=parse_iso_date(metadata.get("published_on")),
        partizioni=partizioni,
        anomalie=anomalie,
    )

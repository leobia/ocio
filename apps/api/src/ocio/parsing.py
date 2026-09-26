"""Shared data contracts for local corpus parsers."""

from __future__ import annotations

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
    genitore: str | None = None
    rubrica: str | None = None
    localizzatore: dict[str, Any] = field(default_factory=dict)
    vigente_dal: date | None = None
    vigente_al: date | None = None


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

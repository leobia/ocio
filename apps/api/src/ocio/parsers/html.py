"""Parse the acquisizioni HTML exported by the Gazzetta Ufficiale."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from html.parser import HTMLParser

from ocio.acquisition import SourceAcquisition
from ocio.parsing import (
    ParseAnomaly,
    ParsedDocument,
    ParsedPartition,
    normalize_whitespace,
    parse_iso_date,
)


class _AttoTextParser(HTMLParser):
    """Collect only the preformatted text inside the act's content span."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool, bool]] = []
        self._detail_depth = 0
        self._pre_depth = 0
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        is_detail = tag == "span" and "dettaglio_atto_testo" in classes
        is_pre = tag == "pre" and self._detail_depth > 0
        if is_detail:
            self._detail_depth += 1
        if is_pre:
            self._pre_depth += 1
        self._stack.append((tag, is_detail, is_pre))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                closing = self._stack[index:]
                del self._stack[index:]
                self._detail_depth -= sum(int(item[1]) for item in closing)
                self._pre_depth -= sum(int(item[2]) for item in closing)
                return

    def handle_data(self, data: str) -> None:
        if self._pre_depth:
            self.fragments.append(data)


def _split_article(
    text: str, label: str
) -> tuple[str, str, str | None, str, str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    number_match = re.search(r"(\d+)", label)
    identifier = (
        f"art-{number_match.group(1)}" if number_match else "articolo-non-identificato"
    )
    article_line = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^Art(?:icolo)?\.?\s*\d+", line, re.IGNORECASE)
        ),
        None,
    )
    if article_line is None:
        return (
            identifier,
            "",
            None,
            normalize_whitespace(text),
            (f"Intestazione {label!r} dichiarata ma non trovata nel testo HTML."),
        )

    preamble = normalize_whitespace("\n".join(lines[:article_line]))
    after_heading = lines[article_line + 1 :]
    rubric_lines: list[str] = []
    body_index = 0
    for index, line in enumerate(after_heading):
        if re.match(r"^(?:[0-9Il]{1,3}[.)]|\([a-z0-9]+\))\s", line, re.IGNORECASE):
            body_index = index
            break
        if line.casefold().startswith(("decreta:", "determina:", "dispone:")):
            continue
        rubric_lines.append(line)
        body_index = index + 1
    else:
        body_index = len(after_heading)

    has_body_marker = body_index < len(after_heading) and bool(
        re.match(
            r"^(?:[0-9Il]{1,3}[.)]|\([a-z0-9]+\))\s",
            after_heading[body_index],
            re.IGNORECASE,
        )
    )
    rubric = normalize_whitespace("\n".join(rubric_lines)) or None
    if not has_body_marker:
        rubric = None
        body_index = 0
    body = normalize_whitespace("\n".join(after_heading[body_index:]))
    issue = None if body else "Il testo dell'articolo è vuoto dopo l'intestazione."
    return identifier, preamble, rubric, body, issue


def parse_html(
    acquisitions: Sequence[SourceAcquisition],
) -> ParsedDocument:
    """Parse all Gazzetta HTML fragments belonging to the same document."""
    if not acquisitions:
        raise ValueError("Nessuna acquisizione HTML da analizzare.")
    metadata = json.loads(acquisitions[0].metadata)
    if not isinstance(metadata, dict):
        raise ValueError(f"{acquisitions[0].document_id}: metadati HTML non validi.")

    ordered: list[tuple[int, SourceAcquisition, dict[str, object]]] = []
    for index, acquisition in enumerate(acquisitions, start=1):
        source_metadata = json.loads(acquisition.metadata)
        if not isinstance(source_metadata, dict):
            raise ValueError(f"{acquisition.local_path}: metadati HTML non validi.")
        part = source_metadata.get("part")
        part_name = part if isinstance(part, str) else f"Parte {index}"
        ordered.append((index, acquisition, source_metadata))

    partitions: list[ParsedPartition] = []
    anomalies: list[ParseAnomaly] = []
    sibling_order = 0
    for fallback_order, acquisition, source_metadata in ordered:
        part = source_metadata.get("part")
        part_name = part if isinstance(part, str) else f"Parte {fallback_order}"
        collector = _AttoTextParser()
        try:
            collector.feed(acquisition.content.decode("utf-8-sig"))
        except UnicodeDecodeError as error:
            raise ValueError(f"{acquisition.local_path}: HTML non UTF-8.") from error
        raw_text = "".join(collector.fragments)
        if not raw_text.strip():
            raise ValueError(
                f"{acquisition.local_path}: contenuto dell'atto non trovato nel DOM."
            )

        locator: dict[str, object] = {
            "formato": "html",
            "local_path": acquisition.local_path,
            "part": part_name,
        }
        lower_part = part_name.casefold()
        if lower_part.startswith("art"):
            identifier, preamble, rubric, content, issue = _split_article(
                raw_text, part_name
            )
            if preamble:
                sibling_order += 1
                partitions.append(
                    ParsedPartition(
                        identifier="preambolo",
                        tipo="premessa",
                        ordine=sibling_order,
                        contenuto=preamble,
                        localizzatore=locator,
                    )
                )
            sibling_order += 1
            partitions.append(
                ParsedPartition(
                    identifier=identifier,
                    tipo="articolo",
                    ordine=sibling_order,
                    contenuto=content,
                    rubrica=rubric,
                    localizzatore=locator,
                )
            )
            if issue:
                anomalies.append(ParseAnomaly(issue, acquisition.local_path))
            continue

        annex_match = re.search(r"([IVXLCDM]+|\d+)", part_name)
        suffix = annex_match.group(1).casefold() if annex_match else str(fallback_order)
        annex_validity = source_metadata.get("vigenza_per_allegato")
        if isinstance(annex_validity, dict):
            effective_from = annex_validity.get(suffix.upper())
        else:
            effective_from = source_metadata.get("vigente_dal")
        sibling_order += 1
        partitions.append(
            ParsedPartition(
                identifier=f"allegato-{suffix}",
                tipo="allegato",
                ordine=sibling_order,
                contenuto=normalize_whitespace(raw_text),
                rubrica=part_name,
                localizzatore=locator,
                vigente_dal=parse_iso_date(effective_from),
                vigente_al=parse_iso_date(source_metadata.get("vigente_al")),
            )
        )
        if not (lower_part.startswith("allegato")):
            anomalies.append(
                ParseAnomaly(
                    f"Parte HTML non classificata dal registry: {part_name!r}.",
                    acquisition.local_path,
                )
            )

    if not partitions:
        raise ValueError(
            f"{acquisitions[0].document_id}: nessuna partizione HTML trovata."
        )

    document_id = acquisitions[0].document_id
    title = metadata.get("title")
    return ParsedDocument(
        codice=document_id,
        titolo=title if isinstance(title, str) else document_id,
        tipo_documento="atto_normativo",
        urn=None,
        vigente_dal=parse_iso_date(metadata.get("vigente_dal")),
        vigente_al=parse_iso_date(metadata.get("vigente_al")),
        snapshot_al=parse_iso_date(metadata.get("snapshot_as_of")),
        pubblicato_il=parse_iso_date(metadata.get("published_on")),
        partizioni=tuple(partitions),
        anomalie=tuple(anomalies),
    )

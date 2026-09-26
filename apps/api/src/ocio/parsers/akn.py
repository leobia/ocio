"""Converte XML Akoma Ntoso nelle partizioni documentali correnti."""

from __future__ import annotations

import re
from collections import defaultdict
from xml.etree import ElementTree

from ocio.acquisition import AKN, SourceAcquisition
from ocio.parsing import (
    ParseAnomaly,
    ParsedDocument,
    ParsedPartition,
    document_from_metadata,
    normalize_whitespace,
)

LABEL_RE = re.compile(r"\b(Titolo|Capo|Sezione)\s+([IVXLCDM]+|\d+)\b", re.IGNORECASE)
ROMAN_OR_NUMERIC_RE = re.compile(r"^[IVXLCDM]+$|^\d+$", re.IGNORECASE)
STRUCTURAL_TAGS = {
    "part",
    "chapter",
    "section",
    "subsection",
    "article",
    "paragraph",
    "subparagraph",
    "point",
    "alinea",
    "list",
    "item",
    "attachment",
    "table",
    "authorialNote",
}
SKIPPED_TEXT_TAGS = {"num", "heading", "authorialNote", *STRUCTURAL_TAGS}
TAG_TYPES = {
    "part": "parte",
    "section": "sezione",
    "subsection": "sottosezione",
    "article": "articolo",
    "subparagraph": "sottoparagrafo",
    "alinea": "capoverso",
    "list": "elenco",
    "item": "voce_elenco",
    "attachment": "allegato",
    "table": "tabella",
    "authorialNote": "nota",
}


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str:
    child = element.find(f"{AKN}{name}")
    return normalize_whitespace("".join(child.itertext())) if child is not None else ""


def _body_text(element: ElementTree.Element) -> str:
    """Collect readable inline text without copying child partitions."""
    fragments: list[str] = []

    def collect(node: ElementTree.Element) -> None:
        if node.text:
            fragments.append(node.text)
        for child in node:
            name = _local_name(child)
            if name in SKIPPED_TEXT_TAGS:
                if child.tail:
                    fragments.append(child.tail)
                continue
            if name not in {"num", "heading"}:
                collect(child)
            if child.tail:
                fragments.append(child.tail)

    collect(element)
    return normalize_whitespace("".join(fragments))


def _slug(value: str) -> str:
    normalized = value.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized or "struttura"


def _partition_identifier(
    element: ElementTree.Element,
    parent_identifier: str | None,
    kind: str,
    order: int,
    label: str,
) -> str:
    e_id = element.get("eId")
    if e_id:
        return e_id
    base = _slug(label) if label else f"{kind}_{order}"
    return f"{parent_identifier}/{base}" if parent_identifier else base


def _chapter_parts(
    element: ElementTree.Element,
) -> tuple[tuple[str, str, str | None], ...]:
    """Split Normattiva chapter headings that combine title/capo/sezione labels."""
    number = _child_text(element, "num")
    heading = _child_text(element, "heading")
    number_match = LABEL_RE.search(number)
    if number_match is None:
        return (("capo", heading or number or "Capo", element.get("eId")),)

    primary_name = number_match.group(1).casefold()
    primary_label = f"{number_match.group(1)} {number_match.group(2)}"
    heading_matches = list(LABEL_RE.finditer(heading))
    preceding_heading = (
        heading[: heading_matches[0].start()].strip() if heading_matches else heading
    )
    parts: list[tuple[str, str, str | None]] = [
        (primary_name.casefold(), primary_label, element.get("eId"))
    ]
    if preceding_heading:
        parts[0] = (parts[0][0], f"{primary_label}\t{preceding_heading}", parts[0][2])

    for index, match in enumerate(heading_matches):
        label = f"{match.group(1)} {match.group(2)}"
        end = (
            heading_matches[index + 1].start()
            if index + 1 < len(heading_matches)
            else len(heading)
        )
        rubric = heading[match.end() : end].strip()
        if label.casefold() == primary_label.casefold():
            continue
        parts.append((match.group(1).casefold(), f"{label}\t{rubric}", None))

    return tuple(parts)


def _kind_for_point(number: str) -> str:
    label = number.strip().strip("().")
    if label and label[0].isalpha() and label.isalpha():
        return "lettera"
    return "punto"


def _urn(root: ElementTree.Element) -> str | None:
    for alias in root.findall(f".//{AKN}FRBRalias"):
        if alias.get("name") == "urn:nir":
            return alias.get("value")
    return None


def parse_akn(
    acquisition: SourceAcquisition, metadata: dict[str, object]
) -> ParsedDocument:
    """Parse an AKN source using its document structure."""
    try:
        root = ElementTree.fromstring(acquisition.content)
    except ElementTree.ParseError as error:
        raise ValueError(f"{acquisition.local_path}: XML AKN non valido.") from error
    if root.tag != f"{AKN}akomaNtoso":
        raise ValueError(f"{acquisition.local_path}: namespace AKN inatteso.")

    partitions: list[ParsedPartition] = []
    sibling_orders: defaultdict[str | None, int] = defaultdict(int)
    active_levels: dict[int, str] = {}
    anomalies: list[str] = []
    seen_identifiers: set[str] = set()

    def add(
        element: ElementTree.Element,
        kind: str,
        parent: str | None,
        label: str,
        rubric: str | None = None,
        content: str | None = None,
        *,
        identifier: str | None = None,
    ) -> str:
        sibling_orders[parent] += 1
        order = sibling_orders[parent]
        stable_id = identifier or _partition_identifier(
            element, parent, kind, order, label
        )
        if stable_id in seen_identifiers:
            if element.get("eId") == stable_id:
                raise ValueError(
                    f"{acquisition.local_path}: eId AKN duplicato {stable_id!r}."
                )
            stable_id = f"{stable_id}__{order}"
            while stable_id in seen_identifiers:
                stable_id = f"{stable_id}_2"
        seen_identifiers.add(stable_id)
        locator: dict[str, object] = {
            "formato": "akn_xml",
            "local_path": acquisition.local_path,
        }
        if element.get("eId"):
            locator["eId"] = element.get("eId")
        partitions.append(
            ParsedPartition(
                identifier=stable_id,
                tipo=kind,
                ordine=order,
                contenuto=content if content is not None else _body_text(element),
                genitore=parent,
                rubrica=rubric or None,
                localizzatore=locator,
            )
        )
        return stable_id

    def walk(element: ElementTree.Element, parent: str | None) -> None:
        for child in element:
            visit(child, parent)

    def visit(element: ElementTree.Element, parent: str | None) -> None:
        name = _local_name(element)
        if name == "chapter":
            chapter_parent = parent
            for marker_index, (chapter_name, raw_label, e_id) in enumerate(
                _chapter_parts(element)
            ):
                label, separator, rubric = raw_label.partition("\t")
                level = {"titolo": 0, "capo": 1, "sezione": 2}.get(chapter_name, 1)
                parent_id = next(
                    (
                        active_levels[previous_level]
                        for previous_level in range(level - 1, -1, -1)
                        if previous_level in active_levels
                    ),
                    parent,
                )
                if marker_index == 0 and e_id:
                    stable_id = e_id
                else:
                    stable_id = (
                        f"{parent_id}/{_slug(label)}" if parent_id else _slug(label)
                    )
                chapter_parent = add(
                    element,
                    chapter_name,
                    parent_id,
                    label,
                    rubric if separator else None,
                    "",
                    identifier=stable_id,
                )
                for previous_level in tuple(active_levels):
                    if previous_level >= level:
                        del active_levels[previous_level]
                active_levels[level] = chapter_parent
            walk_nonchapter_children(element, chapter_parent)
            return

        if name in {
            "akomaNtoso",
            "act",
            "body",
            "mainBody",
            "attachments",
            "doc",
            "preface",
        }:
            walk(element, parent)
            return
        if name == "meta":
            return
        if name == "preamble":
            text = _body_text(element)
            if text:
                partition_id = add(
                    element, "premessa", parent, "Premessa", content=text
                )
                walk_nonchapter_children(element, partition_id)
            return
        if name == "conclusions":
            text = _body_text(element)
            if text:
                add(element, "conclusioni", parent, "Conclusioni", content=text)
            return

        if name == "list":
            # AKN uses list as a container for lettered points. Keep the legal
            # parent chain article → comma → letter instead of exposing a wrapper.
            walk_nonchapter_children(element, parent)
            return

        if name in STRUCTURAL_TAGS:
            number = _child_text(element, "num")
            heading = _child_text(element, "heading")
            kind = TAG_TYPES.get(name, name)
            if name == "paragraph":
                parent_is_article = any(
                    partition.identifier == parent and partition.tipo == "articolo"
                    for partition in partitions
                )
                kind = "comma" if parent_is_article and number else "paragrafo"
            elif name == "point":
                kind = _kind_for_point(number)
            elif name == "attachment":
                attachment_text = normalize_whitespace("".join(element.itertext()))
                match = re.search(
                    r"\bAllegato\s+([A-Z0-9IVXLCDM]+(?:[-–][A-Z0-9]+)?)",
                    attachment_text,
                    re.IGNORECASE,
                )
                label = (
                    number
                    or heading
                    or (f"Allegato {match.group(1)}" if match else "Allegato")
                )
                partition_id = add(
                    element, "allegato", parent, label, heading or label, ""
                )
                walk_nonchapter_children(element, partition_id)
                return
            article_rubric = heading or None
            if name == "article" and not article_rubric:
                unnumbered_paragraph = next(
                    (
                        child
                        for child in element
                        if _local_name(child) == "paragraph"
                        and not _child_text(child, "num")
                        and _body_text(child)
                    ),
                    None,
                )
                if unnumbered_paragraph is not None:
                    article_rubric = _body_text(unnumbered_paragraph)
            label = number or article_rubric or kind
            partition_id = add(element, kind, parent, label, article_rubric)
            walk_nonchapter_children(element, partition_id)
            return

        if name in {"p", "intro", "content", "text"}:
            # These containers contribute text to their closest parent partition.
            for nested in element:
                if _local_name(nested) in STRUCTURAL_TAGS:
                    visit(nested, parent)
            return

        if name not in {
            "num",
            "heading",
            "docType",
            "docDate",
            "docNumber",
            "docTitle",
        }:
            text = _body_text(element)
            if text and len(text) > 20:
                anomalies.append(
                    f"Elemento AKN non classificato {name!r} in {acquisition.local_path}."
                )
                add(element, "non_classificata", parent, name, content=text)

    def walk_nonchapter_children(
        element: ElementTree.Element, parent: str | None
    ) -> None:
        rubric_paragraph: ElementTree.Element | None = None
        if _local_name(element) == "article" and not _child_text(element, "heading"):
            rubric_paragraph = next(
                (
                    child
                    for child in element
                    if _local_name(child) == "paragraph"
                    and not _child_text(child, "num")
                    and _body_text(child)
                ),
                None,
            )
        for child in element:
            if child is rubric_paragraph:
                continue
            name = _local_name(child)
            if name in STRUCTURAL_TAGS or name in {
                "body",
                "mainBody",
                "attachments",
                "doc",
                "preface",
                "preamble",
                "conclusions",
            }:
                visit(child, parent)
            elif name in {"content", "p", "intro", "text"}:
                visit(child, parent)

    walk(root, None)

    if not partitions:
        raise ValueError(
            f"{acquisition.local_path}: nessuna partizione documentale AKN trovata."
        )

    title = metadata.get("title")
    if not isinstance(title, str):
        title = _child_text(root, "docTitle") or acquisition.document_id

    return document_from_metadata(
        acquisition.document_id,
        metadata,
        tuple(partitions),
        titolo=title,
        urn=_urn(root),
        anomalie=tuple(
            ParseAnomaly(message, acquisition.local_path) for message in anomalies
        ),
    )

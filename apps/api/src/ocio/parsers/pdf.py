"""Ricostruisce le partizioni PDF conservando layout, pagine e coordinate."""

from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pdfplumber

from ocio.acquisition import SourceAcquisition
from ocio.parsing import (
    ParseAnomaly,
    ParsedDocument,
    ParsedPartition,
    document_from_metadata,
    legal_marker,
    normalize_whitespace,
)


@dataclass(frozen=True, slots=True)
class _Table:
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    index: int
    issue: str | None = None


@dataclass(frozen=True, slots=True)
class _Block:
    text: str
    page: int
    top: float
    bottom: float
    x0: float
    x1: float = 0.0
    kind: str = "line"
    bold: bool = False
    font_size: float = 0.0
    table_index: int = 0
    issue: str | None = None


def _extract_blocks(
    acquisition: SourceAcquisition,
) -> tuple[list[_Block], list[ParseAnomaly], int]:
    """Extract positioned text and reconstruct table cells where possible."""
    blocks: list[_Block] = []
    anomalies: list[ParseAnomaly] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(acquisition.content))
    except Exception as error:  # pdfplumber wraps several parser-specific errors
        raise ValueError(f"{acquisition.local_path}: PDF non leggibile.") from error

    with pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            raw_lines = page.extract_text_lines(return_chars=True) or []
            tables: list[_Table] = []
            try:
                candidates = page.find_tables()
            except Exception as error:
                candidates = []
                anomalies.append(
                    ParseAnomaly(
                        f"Ricostruzione delle tabelle non riuscita: {error}",
                        acquisition.local_path,
                        page_number,
                    )
                )

            for index, candidate in enumerate(candidates, start=1):
                extracted = candidate.extract() or []
                rows = [
                    [normalize_whitespace(cell or "") for cell in row]
                    for row in extracted
                ]
                nonempty_rows = [row for row in rows if any(row)]
                if (
                    len(nonempty_rows) < 2
                    or max(map(len, nonempty_rows), default=0) < 2
                ):
                    continue
                text = "\n".join(" | ".join(row) for row in nonempty_rows)
                issue = None
                if any(not any(row) for row in rows):
                    issue = "La tabella contiene righe non ricostruite integralmente."
                bbox = candidate.bbox
                table = _Table(
                    text,
                    page_number,
                    (
                        float(bbox[0]),
                        float(bbox[1]),
                        float(bbox[2]),
                        float(bbox[3]),
                    ),
                    index,
                    issue,
                )
                tables.append(table)

            for line in raw_lines:
                text = normalize_whitespace(str(line.get("text", "")))
                if not text:
                    continue
                line_top = float(line.get("top", 0.0))
                line_bottom = float(line.get("bottom", line_top))
                if any(
                    line_top >= table.bbox[1] - 1
                    and line_bottom <= table.bbox[3] + 1
                    and float(line.get("x0", 0.0)) >= table.bbox[0] - 2
                    and float(line.get("x1", 0.0)) <= table.bbox[2] + 2
                    for table in tables
                ):
                    continue
                chars = line.get("chars", [])
                font_names = [str(char.get("fontname", "")) for char in chars]
                font_sizes = [float(char.get("size", 0.0)) for char in chars]
                blocks.append(
                    _Block(
                        text=text,
                        page=page_number,
                        top=line_top,
                        bottom=line_bottom,
                        x0=float(line.get("x0", 0.0)),
                        x1=float(line.get("x1", 0.0)),
                        bold=any(
                            "bold" in name.casefold() or "black" in name.casefold()
                            for name in font_names
                        ),
                        font_size=max(font_sizes, default=0.0),
                    )
                )

            for table in tables:
                blocks.append(
                    _Block(
                        text=table.text,
                        page=table.page,
                        top=table.bbox[1],
                        bottom=table.bbox[3],
                        x0=table.bbox[0],
                        x1=table.bbox[2],
                        kind="table",
                        table_index=table.index,
                        issue=table.issue,
                    )
                )
                if table.issue:
                    anomalies.append(
                        ParseAnomaly(table.issue, acquisition.local_path, page_number)
                    )

            if not raw_lines and not tables:
                anomalies.append(
                    ParseAnomaly(
                        "Pagina senza testo estraibile.",
                        acquisition.local_path,
                        page_number,
                    )
                )

    blocks.sort(key=lambda block: (block.page, block.top, block.x0))
    return blocks, anomalies, len(pdf.pages)


def _locator(
    acquisition: SourceAcquisition,
    spans: list[dict[str, float | int]],
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, Any]:
    pages = [int(span["page"]) for span in spans]
    locator: dict[str, Any] = {
        "formato": "pdf",
        "local_path": acquisition.local_path,
        "pagina_da": min(pages) if pages else None,
        "pagina_a": max(pages) if pages else None,
        "spans": spans,
    }
    if extra:
        locator.update(extra)
    return locator


def _spans(blocks: list[_Block]) -> list[dict[str, float | int]]:
    by_page: dict[int, tuple[float, float, float, float]] = {}
    for block in blocks:
        if block.page in by_page:
            left, top, right, bottom = by_page[block.page]
            by_page[block.page] = (
                min(left, block.x0),
                min(top, block.top),
                max(right, block.x1),
                max(bottom, block.bottom),
            )
        else:
            by_page[block.page] = (block.x0, block.top, block.x1, block.bottom)
    return [
        {"page": page, "x0": left, "top": top, "x1": right, "bottom": bottom}
        for page, (left, top, right, bottom) in sorted(by_page.items())
    ]


def _slug(value: str) -> str:
    value = value.casefold().replace("’", "'")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "struttura"


def _number_heading(text: str) -> re.Match[str] | None:
    return re.match(r"^\s*(\d+(?:\.\d+){0,4})[.)]?\s+(.+?)\s*$", text)


def _is_page_number(block: _Block, page_height: float) -> bool:
    return bool(re.fullmatch(r"\d{1,3}", block.text)) and block.top > page_height * 0.92


class _DocumentBuilder:
    def __init__(self, acquisition: SourceAcquisition) -> None:
        self.acquisition = acquisition
        self.partitions: list[ParsedPartition] = []
        self.orders: defaultdict[str | None, int] = defaultdict(int)
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.identifiers: set[str] = set()

    def add(
        self,
        identifier: str,
        kind: str,
        parent: str | None,
        content: str,
        spans: list[dict[str, float | int]],
        rubric: str | None = None,
        *,
        localizer: dict[str, Any] | None = None,
        vigente_dal: Any = None,
        vigente_al: Any = None,
    ) -> str:
        self.orders[parent] += 1
        if identifier in self.identifiers:
            page = spans[0]["page"] if spans else "unknown"
            base = f"{identifier}-p{page}"
            identifier = base
            suffix = 2
            while identifier in self.identifiers:
                identifier = f"{base}-{suffix}"
                suffix += 1
        self.identifiers.add(identifier)
        locator = localizer or _locator(self.acquisition, spans)
        self.partitions.append(
            ParsedPartition(
                identifier=identifier,
                tipo=kind,
                ordine=self.orders[parent],
                contenuto=content,
                marcatore=legal_marker(kind, identifier),
                genitore=parent,
                rubrica=rubric,
                localizzatore=locator,
                vigente_dal=vigente_dal,
                vigente_al=vigente_al,
            )
        )
        return identifier

    def append_text(
        self,
        parent: str,
        chunks: list[str],
        blocks: list[_Block],
        *,
        kind: str = "paragrafo",
    ) -> None:
        content = normalize_whitespace("\n".join(chunks))
        if not content:
            return
        self.counters[parent] += 1
        identifier = f"{parent}/testo-{self.counters[parent]}"
        self.add(identifier, kind, parent, content, _spans(blocks))


def _is_boilerplate(block: _Block, page_height: float) -> bool:
    if _is_page_number(block, page_height):
        return True
    folded = block.text.casefold()
    return folded.startswith(
        (
            "ministero dell'interno",
            "ministero dell’interno",
            "dipartimento dei vigili del fuoco",
            "direzione centrale per la prevenzione",
        )
    )


def _join_wrapped_faq_headings(blocks: list[_Block]) -> list[_Block]:
    """Join uppercase category headings split across adjacent PDF lines."""
    result: list[_Block] = []
    index = 0
    connectors = (
        " DI",
        " DEL",
        " DELLA",
        " DELLE",
        " DEI",
        " DEGLI",
        " DELL'",
        " N.",
        " CHE",
    )
    continuation_starts = ("CUI ", "CON ", "OPERANO ", "81/")
    while index < len(blocks):
        first = blocks[index]
        if (
            not first.bold
            or not first.text.isupper()
            or first.text.casefold() in {"risposta"}
        ):
            result.append(first)
            index += 1
            continue
        text = first.text
        last = first
        index += 1
        while index < len(blocks):
            candidate = blocks[index]
            candidate_text = candidate.text.strip()
            previous_incomplete = text.rstrip().endswith(connectors)
            next_continues = candidate_text.startswith(continuation_starts)
            close_line = (
                candidate.page == last.page
                and candidate.bold
                and candidate.top - last.bottom <= 5
                and candidate.x0 <= last.x0 + 4
                and candidate_text.casefold() != "risposta"
                and not candidate_text.casefold().startswith("quesito")
            )
            if not close_line or not (previous_incomplete or next_continues):
                break
            text = f"{text} {candidate_text}"
            last = candidate
            index += 1
        if last is first:
            result.append(first)
        else:
            result.append(
                _Block(
                    text=text,
                    page=first.page,
                    top=first.top,
                    bottom=last.bottom,
                    x0=first.x0,
                    x1=last.x1,
                    bold=True,
                    font_size=first.font_size,
                )
            )
    return result


def _parse_faq(
    acquisition: SourceAcquisition,
    metadata: dict[str, object],
    blocks: list[_Block],
    anomalies: list[ParseAnomaly],
) -> ParsedDocument:
    builder = _DocumentBuilder(acquisition)
    category: str | None = None
    question: str | None = None
    active: str | None = None
    body: list[str] = []
    body_blocks: list[_Block] = []
    question_text: list[str] = []
    question_blocks: list[_Block] = []
    question_created = False
    seen_categories: set[str] = set()

    def flush_body() -> None:
        nonlocal body, body_blocks
        if active and body:
            builder.append_text(active, body, body_blocks)
        body = []
        body_blocks = []

    def flush_question() -> None:
        nonlocal question, question_text, question_blocks, active, question_created
        flush_body()
        if question and question_text and not question_created:
            content = normalize_whitespace("\n".join(question_text))
            question_spans = _spans(question_blocks)
            builder.add(question, "domanda", category, content, question_spans)
            anomalies.append(
                ParseAnomaly(
                    "Il quesito non ha un'etichetta Risposta riconosciuta.",
                    acquisition.local_path,
                    question_blocks[0].page if question_blocks else None,
                )
            )
        question = None
        question_text = []
        question_blocks = []
        question_created = False
        active = None

    for block in _join_wrapped_faq_headings(blocks):
        text = block.text.strip()
        if not text:
            continue
        if _is_boilerplate(block, 800.0):
            continue
        if re.match(r"^Quesito\s+n\.?\s*\d+", text, re.IGNORECASE):
            flush_question()
            number = re.search(r"\d+", text)
            if number is None:
                anomalies.append(
                    ParseAnomaly(
                        "Numero del quesito non leggibile.",
                        acquisition.local_path,
                        block.page,
                    )
                )
                continue
            question = f"{category or 'faq'}/quesito-{number.group(0)}"
            active = None
            question_text = []
            question_blocks = [block]
            continue
        if text.casefold() == "risposta":
            if question is None:
                anomalies.append(
                    ParseAnomaly(
                        "Etichetta Risposta senza quesito associato.",
                        acquisition.local_path,
                        block.page,
                    )
                )
                continue
            flush_body()
            if not question_created:
                builder.add(
                    question,
                    "domanda",
                    category,
                    normalize_whitespace("\n".join(question_text)),
                    _spans(question_blocks),
                )
                question_created = True
            active = f"{question}/risposta"
            builder.add(
                active,
                "risposta",
                question,
                "",
                _spans([block]),
                rubric="Risposta",
            )
            continue
        if block.bold and text.isupper() and len(text) < 100:
            flush_question()
            category = f"categoria-{_slug(text)}"
            if category not in seen_categories:
                builder.add(category, "sezione", None, "", _spans([block]), rubric=text)
                seen_categories.add(category)
            active = None
            continue
        if question is not None and active is None:
            question_text.append(text)
            question_blocks.append(block)
        elif active is not None:
            body.append(text)
            body_blocks.append(block)
        else:
            anomalies.append(
                ParseAnomaly(
                    "Testo FAQ esterno a una categoria o a un quesito.",
                    acquisition.local_path,
                    block.page,
                )
            )

    flush_question()
    if not builder.partitions:
        raise ValueError(f"{acquisition.local_path}: nessun quesito FAQ trovato.")
    return document_from_metadata(
        acquisition.document_id,
        metadata,
        tuple(builder.partitions),
        tipo_documento="faq",
        anomalie=tuple(anomalies),
    )


def _heading_kind(
    text: str, bold: bool, x0: float, format_name: str
) -> tuple[str, str, str] | None:
    if (
        bold
        and text == text.upper()
        and re.match(r"^PARTE\s+[IVXLCDM0-9]+\b", text, re.IGNORECASE)
    ):
        return "parte", _slug(text.split("–", 1)[0]), text
    if re.match(r"^ALLEGATO\s+[A-Z0-9IVXLCDM]+\b", text, re.IGNORECASE):
        match = re.match(r"^ALLEGATO\s+([A-Z0-9IVXLCDM]+)\s*(.*)$", text, re.IGNORECASE)
        if match:
            rubric = match.group(2).strip() or text
            return "allegato", f"allegato-{match.group(1).casefold()}", rubric
    article = re.match(
        r"^Art(?:icolo)?\.?\s*(\d+(?:-bis|-ter)?)\.?\s*(.*)$", text, re.IGNORECASE
    )
    if article:
        return (
            "articolo",
            f"art-{article.group(1).casefold()}",
            article.group(2).strip(),
        )
    number = _number_heading(text)
    if number and bold:
        label = number.group(1).rstrip(".")
        return "sezione", f"punto-{label}", number.group(2).strip()
    heading_length = 300 if format_name == "accordo_59_csr_2025" else 140
    if bold and x0 < 125 and text.isupper() and len(text) < heading_length:
        return "sezione", _slug(text)[:80], text
    if format_name == "di_30_11_2012" and text.strip() in {"I", "II"}:
        marker = text.strip().lower()
        return "parte", f"parte-{marker}", text
    if format_name == "di_30_11_2012" and re.match(r"^(?:I|II)\.\s+", text):
        marker = text.split(".", 1)[0].lower()
        return "parte", f"parte-{marker}", text.split(".", 1)[1].strip()
    return None


def _join_wrapped_section_headings(
    blocks: list[_Block], format_name: str
) -> list[_Block]:
    """Join consecutive lines belonging to one unnumbered PDF heading."""
    if format_name != "accordo_59_csr_2025":
        return blocks

    joined: list[_Block] = []
    index = 0
    while index < len(blocks):
        first = blocks[index]
        heading = _heading_kind(first.text.strip(), first.bold, first.x0, format_name)
        if heading is None or heading[0] != "sezione" or _number_heading(first.text):
            joined.append(first)
            index += 1
            continue

        lines = [first]
        next_index = index + 1
        while next_index < len(blocks):
            candidate = blocks[next_index]
            candidate_heading = _heading_kind(
                candidate.text.strip(), candidate.bold, candidate.x0, format_name
            )
            if (
                candidate.page != first.page
                or candidate.kind != "line"
                or candidate_heading is None
                or candidate_heading[0] != "sezione"
                or _number_heading(candidate.text)
                or abs(candidate.x0 - first.x0) > 2
                or abs(candidate.font_size - first.font_size) > 0.1
                or candidate.top - lines[-1].bottom > 8
            ):
                break
            lines.append(candidate)
            next_index += 1

        if len(lines) == 1:
            joined.append(first)
        else:
            joined.append(
                _Block(
                    text=" ".join(line.text.strip() for line in lines),
                    page=first.page,
                    top=first.top,
                    bottom=lines[-1].bottom,
                    x0=min(line.x0 for line in lines),
                    x1=max(line.x1 for line in lines),
                    bold=True,
                    font_size=first.font_size,
                )
            )
        index = next_index
    return joined


def _parse_structured_pdf(
    acquisition: SourceAcquisition,
    metadata: dict[str, object],
    blocks: list[_Block],
    anomalies: list[ParseAnomaly],
    *,
    code: str | None = None,
    title: str | None = None,
    kind: str = "atto_normativo",
    validity: str | None = None,
    format_name: str,
) -> ParsedDocument:
    blocks = _join_wrapped_section_headings(blocks, format_name)
    builder = _DocumentBuilder(acquisition)
    root = "documento"
    builder.add(root, "documento", None, "", [])
    active = root
    hierarchy: dict[tuple[str, ...], str] = {}
    current_part = root
    current_article: str | None = None
    current_comma: str | None = None
    item_occurrences: defaultdict[tuple[str, str], int] = defaultdict(int)
    text_chunks: list[str] = []
    text_blocks: list[_Block] = []
    has_content = False

    def flush_text() -> None:
        nonlocal text_chunks, text_blocks
        if text_chunks and text_blocks:
            builder.append_text(active, text_chunks, text_blocks)
        text_chunks = []
        text_blocks = []

    skip_blocks: set[int] = set()
    for block_index, block in enumerate(blocks):
        if block_index in skip_blocks:
            continue
        text = block.text.strip()
        if not text:
            continue
        if block.kind == "table":
            flush_text()
            parent = active
            identifier = f"{parent}/tabella-p{block.page}-{block.table_index}"
            builder.add(
                identifier,
                "tabella",
                parent,
                text,
                _spans([block]),
                localizer=_locator(
                    acquisition,
                    _spans([block]),
                    extra={"tabella": block.table_index},
                ),
            )
            has_content = True
            continue

        # Recurring institutional headers and physical page numbers are not source text.
        if _is_boilerplate(block, 800.0):
            continue

        heading = _heading_kind(text, block.bold, block.x0, format_name)
        if heading is not None:
            flush_text()
            unit_kind, stable, rubric = heading
            heading_blocks = [block]
            if unit_kind == "articolo" and block_index + 1 < len(blocks):
                possible_rubric = blocks[block_index + 1]
                rubric_text = possible_rubric.text.strip()
                if (
                    possible_rubric.page == block.page
                    and possible_rubric.kind == "line"
                    and possible_rubric.x0 >= 140
                    and not _number_heading(rubric_text)
                    and not re.match(
                        r"^Art(?:icolo)?\.?\s*\d+", rubric_text, re.IGNORECASE
                    )
                    and len(rubric_text) < 180
                ):
                    rubric = rubric_text
                    heading_blocks.append(possible_rubric)
                    skip_blocks.add(block_index + 1)
            number = _number_heading(text)
            path: tuple[str, ...] = ()
            if number and unit_kind == "sezione":
                path = tuple(number.group(1).rstrip(".").split("."))
                parent_key = path[:-1]
                parent_id = hierarchy.get(parent_key, current_part)
                identifier = f"{parent_id}/{stable}"
                for key in tuple(hierarchy):
                    if len(key) >= len(path):
                        del hierarchy[key]
            elif unit_kind == "articolo" or unit_kind == "allegato":
                parent_id = root
                path = ()
                identifier = f"{root}/{stable}"
                hierarchy.clear()
                current_part = identifier if unit_kind == "allegato" else root
            elif unit_kind == "parte":
                parent_id = root
                path = ()
                hierarchy.clear()
                identifier = f"{root}/{stable}"
                if format_name == "di_30_11_2012" and block_index + 1 < len(blocks):
                    possible_title = blocks[block_index + 1]
                    title_text = possible_title.text.strip()
                    if (
                        possible_title.page == block.page
                        and possible_title.x0 >= 120
                        and possible_title.kind == "line"
                        and not re.match(r"^(?:[0-9]+\.|Art\.)", title_text)
                    ):
                        rubric = title_text
                        heading_blocks.append(possible_title)
                        skip_blocks.add(block_index + 1)
            else:
                parent_id = (
                    max(hierarchy.items(), key=lambda item: len(item[0]))[1]
                    if hierarchy
                    else current_part
                )
                identifier = f"{parent_id}/{stable}"
            identifier = builder.add(
                identifier,
                unit_kind,
                parent_id,
                "",
                _spans(heading_blocks),
                rubric=rubric or text,
            )
            if number and unit_kind == "sezione":
                hierarchy[path] = identifier
            elif unit_kind == "allegato":
                current_part = identifier
            elif unit_kind == "parte":
                current_part = identifier
            active = identifier
            if unit_kind == "articolo":
                current_article = identifier
                current_comma = None
            elif unit_kind == "allegato":
                current_article = None
                current_comma = None
            elif unit_kind == "parte":
                current_article = None
                current_comma = None
            has_content = True
            continue

        if block.bold and text.casefold().startswith("quesito n"):
            anomalies.append(
                ParseAnomaly(
                    "Quesito non classificato come FAQ.",
                    acquisition.local_path,
                    block.page,
                )
            )

        list_match = re.match(
            r"^\s*((?:\([a-z0-9ivxlcdm]+\))|(?:[a-z]\)|\d+[.)]))\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if list_match and block.x0 >= 70:
            flush_text()
            marker = list_match.group(1)
            marker_value = _slug(marker)
            is_numeric = marker[0].isdigit()
            if is_numeric and current_article:
                parent = current_article
                unit_kind = "comma"
                current_comma = None
            elif not is_numeric and current_comma:
                parent = current_comma
                unit_kind = "lettera"
            else:
                parent = active
                unit_kind = "voce_elenco"
            occurrence_key = (parent, marker_value)
            item_occurrences[occurrence_key] += 1
            occurrence = item_occurrences[occurrence_key]
            identifier = f"{parent}/{unit_kind}-{marker_value}"
            if occurrence > 1:
                identifier = f"{identifier}-{occurrence}"
            item_chunks = [list_match.group(2)]
            item_blocks = [block]
            next_index = block_index + 1
            while next_index < len(blocks):
                following = blocks[next_index]
                following_text = following.text.strip()
                if (
                    following.kind == "table"
                    or _heading_kind(
                        following_text, following.bold, following.x0, format_name
                    )
                    is not None
                ):
                    break
                if _is_boilerplate(following, 800.0):
                    next_index += 1
                    continue
                next_marker = re.match(
                    r"^\s*((?:\([a-z0-9ivxlcdm]+\))|(?:[a-z]\)|\d+[.)]))\s+(.+)$",
                    following_text,
                    re.IGNORECASE,
                )
                if next_marker and following.x0 >= 70:
                    break
                item_chunks.append(following_text)
                item_blocks.append(following)
                skip_blocks.add(next_index)
                next_index += 1
            builder.add(
                identifier,
                unit_kind,
                parent,
                normalize_whitespace("\n".join(item_chunks)),
                _spans(item_blocks),
                rubric=marker,
            )
            if unit_kind == "comma":
                current_comma = identifier
            has_content = True
            continue

        text_chunks.append(text)
        text_blocks.append(block)
        has_content = True

    flush_text()
    if not has_content:
        raise ValueError(
            f"{acquisition.local_path}: nessun testo PDF strutturale trovato."
        )
    return document_from_metadata(
        acquisition.document_id,
        metadata,
        tuple(builder.partitions),
        codice=code,
        titolo=title,
        tipo_documento=kind,
        vigenza=validity,
        anomalie=tuple(anomalies),
    )


def _parse_composite_fire_pdf(
    acquisition: SourceAcquisition,
    metadata: dict[str, object],
    blocks: list[_Block],
    anomalies: list[ParseAnomaly],
) -> tuple[ParsedDocument, ...]:
    starts: dict[int, int] = {}
    for index, block in enumerate(blocks):
        match = re.match(
            r"^DM\s+0?([123])\s+settembre\s+2021\b", block.text, re.IGNORECASE
        )
        if match and block.bold and block.page >= 4:
            starts.setdefault(int(match.group(1)), index)
    if set(starts) != {1, 2, 3}:
        raise ValueError(
            f"{acquisition.local_path}: non trovo i tre confini dei decreti DM 1/2/3 settembre 2021."
        )
    ordered = sorted((position, number) for number, position in starts.items())
    output: list[ParsedDocument] = []
    codes = {
        1: "dm_1_settembre_2021",
        2: "dm_2_settembre_2021",
        3: "dm_3_settembre_2021",
    }
    titles = {
        1: "D.M. 1 settembre 2021 - controllo e manutenzione antincendio",
        2: "D.M. 2 settembre 2021 - gestione antincendio in esercizio ed emergenza",
        3: "D.M. 3 settembre 2021 - criteri generali di sicurezza antincendio",
    }
    for offset, (start, number) in enumerate(ordered):
        end = ordered[offset + 1][0] if offset + 1 < len(ordered) else len(blocks)
        segment = blocks[start:end]
        first_page = segment[0].page
        last_page = segment[-1].page
        code = codes[number]
        validity = code
        title = titles[number]
        section_anomalies = [
            anomaly
            for anomaly in anomalies
            if anomaly.page is None or first_page <= anomaly.page <= last_page
        ]
        if offset == 0:
            section_anomalies.append(
                ParseAnomaly(
                    "Frontespizio, sommario e nota generale sul testo coordinato precedono i tre decreti e sono esclusi dalle partizioni documentali.",
                    acquisition.local_path,
                    3,
                )
            )
        output.append(
            _parse_structured_pdf(
                acquisition,
                metadata,
                segment,
                section_anomalies,
                code=code,
                title=title,
                validity=validity,
                format_name=code,
            )
        )
    return tuple(output)


def parse_pdf(
    acquisition: SourceAcquisition, metadata: dict[str, object]
) -> tuple[ParsedDocument, ...]:
    """Parse a PDF acquisition into one or more logical documents."""
    blocks, anomalies, page_count = _extract_blocks(acquisition)

    if acquisition.document_id == "faq_accordo_59_2025":
        return (_parse_faq(acquisition, metadata, blocks, anomalies),)
    if acquisition.document_id == "dm_1_2_3_settembre_2021":
        return _parse_composite_fire_pdf(acquisition, metadata, blocks, anomalies)

    if acquisition.document_id == "accordo_59_csr_2025":
        # The first page is the agreement's preamble; pages 2-5 are its table of contents.
        body_start = next(
            (
                index
                for index, block in enumerate(blocks)
                if block.page >= 6
                and block.text.upper().startswith("PARTE I – ORGANIZZAZIONE GENERALE")
            ),
            None,
        )
        if body_start is not None:
            toc_blocks = [block for block in blocks if 2 <= block.page <= 5]
            if toc_blocks:
                anomalies.append(
                    ParseAnomaly(
                        "Il sommario alle pagine 2-5 è navigazione duplicata dei contenuti e non viene trattato come testo normativo.",
                        acquisition.local_path,
                        2,
                    )
                )
            preamble_blocks = [
                block for block in blocks[:body_start] if block.page == 1
            ]
            source_blocks = preamble_blocks + blocks[body_start:]
        else:
            source_blocks = blocks
            anomalies.append(
                ParseAnomaly(
                    "Inizio della struttura per parti non riconosciuto.",
                    acquisition.local_path,
                )
            )
        return (
            _parse_structured_pdf(
                acquisition,
                metadata,
                source_blocks,
                anomalies,
                kind="accordo",
                format_name=acquisition.document_id,
            ),
        )

    if acquisition.document_id == "di_30_11_2012":
        # Keep the cover and diagrams; exclude only the duplicate index page.
        source_blocks = [block for block in blocks if block.page != 2]
        if any(block.page == 2 for block in blocks):
            anomalies.append(
                ParseAnomaly(
                    "La pagina 2 contiene soltanto l'indice del PDF e viene esclusa.",
                    acquisition.local_path,
                    2,
                )
            )
        return (
            _parse_structured_pdf(
                acquisition,
                metadata,
                source_blocks,
                anomalies,
                format_name=acquisition.document_id,
            ),
        )

    anomalies.append(
        ParseAnomaly(
            f"Documento PDF con {page_count} pagine senza regole specifiche; applicata la struttura tipografica generica.",
            acquisition.local_path,
        )
    )
    return (
        _parse_structured_pdf(
            acquisition,
            metadata,
            blocks,
            anomalies,
            format_name=acquisition.document_id,
        ),
    )

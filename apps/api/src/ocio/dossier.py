"""Small, deterministic operations for Markdown dossier templates."""

from __future__ import annotations

import difflib
import re

SECTION = re.compile(r"(?m)^## (.+)$")


def _section_matches(markdown: str) -> list[re.Match[str]]:
    # Headings inside fenced examples are content, not dossier sections.
    matches = []
    fence = ""
    offset = 0
    for line in markdown.splitlines(keepends=True):
        delimiter = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if delimiter:
            marker = delimiter.group(1)
            if not fence:
                fence = marker
            elif (
                marker[0] == fence[0] and len(marker) >= len(fence)
                and not line[delimiter.end():].strip()
            ):
                fence = ""
        elif not fence:
            match = SECTION.match(markdown, offset)
            if match:
                matches.append(match)
        offset += len(line)
    return matches


def section_titles(markdown: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in _section_matches(markdown))


def replace_section_body(markdown: str, title: str, body: str) -> str:
    """Replace exactly one section while retaining every other section verbatim."""
    matches = _section_matches(markdown)
    selected = [index for index, match in enumerate(matches) if match.group(1).strip() == title]
    if len(selected) != 1:
        raise ValueError("La sezione deve esistere una sola volta nel fascicolo.")
    index = selected[0]
    start = matches[index].end()
    end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
    return markdown[:start] + "\n\n" + body.strip() + "\n\n" + markdown[end:]


def exportable_dossier(markdown: str, excluded: set[str]) -> str:
    """Keep excluded sections in the working draft but omit them from export material."""
    prefix, sections = _split(markdown)
    return prefix + "".join(block for title, block in sections if title not in excluded)


def validate_instructions(markdown: str, instructions: dict[str, str]) -> None:
    unknown = set(instructions) - set(section_titles(markdown))
    if unknown:
        raise ValueError(f"Indicazioni associate a sezioni inesistenti: {', '.join(sorted(unknown))}")


def migration(current: str, new_template: str) -> tuple[str, str]:
    """Preserve existing section blocks, add new ones and retain removed ones."""
    current_prefix, current_sections = _split(current)
    new_prefix, new_sections = _split(new_template)
    proposed = [current_prefix or new_prefix]
    existing: dict[str, list[str]] = {}
    for title, block in current_sections:
        existing.setdefault(title, []).append(block)
    for title, template_block in new_sections:
        proposed.extend(existing.pop(title, [template_block]))
    removed = [block for title, block in current_sections if title in existing]
    if removed:
        proposed.extend(["## Sezioni conservate dalla revisione precedente\n", *removed])
    result = "\n".join(part.strip("\n") for part in proposed if part.strip()).strip() + "\n"
    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True), result.splitlines(keepends=True),
        fromfile="fascicolo corrente", tofile="migrazione proposta",
    ))
    return result, diff


def _split(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    matches = list(_section_matches(markdown))
    if not matches:
        return markdown, []
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[match.start():end]))
    return markdown[:matches[0].start()], sections

"""Small, deterministic operations for Markdown dossier templates."""

from __future__ import annotations

import difflib
import re

SECTION = re.compile(r"(?m)^## (.+)$")


def section_titles(markdown: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in SECTION.finditer(markdown))


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
    matches = list(SECTION.finditer(markdown))
    if not matches:
        return markdown, []
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[match.start():end]))
    return markdown[:matches[0].start()], sections

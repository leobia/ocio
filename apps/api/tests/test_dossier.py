import pytest

from ocio.dossier import migration, section_titles, validate_instructions


def test_migration_preserves_existing_and_removed_sections() -> None:
    current = """# Fascicolo

## Identità

Testo scritto dall'operatore.

## Sezione rimossa

Evidenza approvata.
"""
    template = """# Fascicolo aggiornato

## Identità

## Nuova sezione

Indicazione iniziale.
"""

    proposed, diff = migration(current, template)

    assert "Testo scritto dall'operatore." in proposed
    assert "## Nuova sezione" in proposed
    assert "## Sezioni conservate dalla revisione precedente" in proposed
    assert "Evidenza approvata." in proposed
    assert "migrazione proposta" in diff


def test_instructions_must_reference_markdown_sections() -> None:
    assert section_titles("# X\n\n## A\n\n## B") == ("A", "B")
    with pytest.raises(ValueError, match="sezioni inesistenti"):
        validate_instructions("## A", {"B": "Compila"})

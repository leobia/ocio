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


def test_migration_preserves_manual_preamble_and_repeated_section_content() -> None:
    current = "# Fascicolo\n\nNota manuale approvata.\n\n## Rischi\nPrima evidenza.\n\n## Rischi\nSeconda evidenza.\n"
    template = "# Nuovo modello\n\n## Rischi\n\n## Formazione\n"

    proposed, _ = migration(current, template)

    assert "Nota manuale approvata." in proposed
    assert "Prima evidenza." in proposed
    assert "Seconda evidenza." in proposed
    assert "## Formazione" in proposed

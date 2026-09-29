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


def test_migration_keeps_long_form_content_and_fenced_headings() -> None:
    narrative = "Descrizione dettagliata dell'attività.\n\n" * 40
    body = (
        narrative + "### Operazioni\n\n- Ricezione\n- Assemblaggio\n\n"
        "| Attrezzatura | Impiego |\n| --- | --- |\n| Banco | Assemblaggio |\n\n"
        "```markdown\n## Titolo di esempio, non una sezione\n```\n"
    )
    current = "# Fascicolo\n\n## Attività\n\n" + body + "\n## Ambienti\n\nNota manuale.\n"
    template = "## Attività\n\n## Emergenze\n"
    proposed, _ = migration(current, template)
    assert section_titles(current) == ("Attività", "Ambienti")
    assert body.strip() in proposed
    assert "## Emergenze" in proposed
    assert "## Ambienti\n\nNota manuale." in proposed


def test_longer_fences_do_not_end_at_shorter_delimiters() -> None:
    markdown = "## A\n````markdown\n```\n## Example\n````\n## B\n"
    assert section_titles(markdown) == ("A", "B")

import json

import pytest

from ocio.dossier_prompt import writing_context


def test_custom_templates_change_context_without_changing_application_rules() -> None:
    first = writing_context('## Ambienti\n\n### Layout\n', {"Ambienti": "Descrizione degli spazi."})
    second = writing_context('## Lavorazioni\n', {"Lavorazioni": "Fasi, turni e compresenze."})
    assert first.instructions == second.instructions
    assert first.version == second.version
    assert "Descrizione degli spazi." not in first.instructions
    assert json.loads(first.template) == {
        "schema": '## Ambienti\n\n### Layout\n',
        "section_descriptions": {"Ambienti": "Descrizione degli spazi."},
    }
    assert json.loads(second.template)["section_descriptions"] == {
        "Lavorazioni": "Fasi, turni e compresenze.",
    }


def test_descriptions_must_belong_to_the_supplied_schema() -> None:
    with pytest.raises(ValueError, match="sezioni inesistenti"):
        writing_context('## Ambienti\n', {"Lavorazioni": "Fasi di lavoro."})

"""End-to-end current-corpus normalization contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from ocio.acquisition import import_source_acquisitions, read_source_acquisitions
from ocio.database import database_url
from ocio.normalization import normalize_corpus


@pytest.mark.integration
def test_normalization_is_idempotent_and_preserves_the_agent_flag() -> None:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")

    repository = Path(__file__).resolve().parents[3]
    registry = repository / "ocio_sources.yaml"
    acquisitions = read_source_acquisitions(registry)
    import_source_acquisitions(registry)
    document_codes = [
        "dlgs_81_2008",
        "accordo_59_csr_2025",
        "faq_accordo_59_2025",
        "dm_388_2003",
        "dpr_462_2001",
        "dpr_177_2011",
        "dm_11_04_2011",
        "dm_3_settembre_2021",
        "dm_2_settembre_2021",
        "dm_1_settembre_2021",
        "dm_13_09_2024",
        "di_30_11_2012",
        "dm_132_2024",
    ]

    first = normalize_corpus(registry)
    assert first.documenti == 13
    assert first.acquisizioni == len(acquisitions) == 22
    assert first.partizioni > 3000

    engine = create_engine(url)
    previous_flag: bool | None = None
    try:
        with engine.connect() as connection:
            previous_flag = connection.execute(
                text(
                    "SELECT abilitato_per_agente FROM documenti "
                    "WHERE codice = 'faq_accordo_59_2025'"
                )
            ).scalar_one()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE documenti SET abilitato_per_agente = false "
                    "WHERE codice = 'faq_accordo_59_2025'"
                )
            )
        second = normalize_corpus(registry)
        with engine.connect() as connection:
            counts = (
                connection.execute(
                    text(
                        "SELECT count(DISTINCT documento.id) AS documents, "
                        "       count(partizione.id) AS partitions "
                        "FROM documenti AS documento "
                        "LEFT JOIN partizioni_documentali AS partizione "
                        "  ON partizione.documento_id = documento.id "
                        "WHERE documento.codice = ANY(:codes)"
                    ),
                    {"codes": document_codes},
                )
                .mappings()
                .one()
            )
            disabled = connection.execute(
                text(
                    "SELECT abilitato_per_agente FROM documenti "
                    "WHERE codice = 'faq_accordo_59_2025'"
                )
            ).scalar_one()
            provenance = {
                row["identificatore"]: row["sha256"]
                for row in connection.execute(
                    text(
                        "SELECT partizione.identificatore, acquisizione.sha256 "
                        "FROM partizioni_documentali AS partizione "
                        "JOIN documenti AS documento "
                        "  ON documento.id = partizione.documento_id "
                        "JOIN acquisizioni_fonti AS acquisizione "
                        "  ON acquisizione.id = partizione.acquisizione_fonte_id "
                        "WHERE documento.codice = 'dm_11_04_2011' "
                        "  AND partizione.identificatore IN ('art-1', 'art-2', 'allegato-i')"
                    )
                ).mappings()
            }
            assert disabled is False
            assert counts["documents"] == second.documenti
            assert counts["partitions"] == second.partizioni
            assert second.partizioni == first.partizioni
            html_digests = {
                json.loads(acquisition.metadata)["part"]: acquisition.digest
                for acquisition in acquisitions
                if acquisition.document_id == "dm_11_04_2011"
            }
            assert provenance == {
                "art-1": html_digests["Art. 1"],
                "art-2": html_digests["Art. 2"],
                "allegato-i": html_digests["Allegato I"],
            }
    finally:
        if previous_flag is not None:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE documenti SET abilitato_per_agente = :enabled "
                        "WHERE codice = 'faq_accordo_59_2025'"
                    ),
                    {"enabled": previous_flag},
                )
        engine.dispose()

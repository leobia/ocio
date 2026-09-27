"""Verifica la struttura prodotta dai parser sui file reali del corpus V1."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from ocio.acquisition import read_source_acquisitions
from ocio.normalization import parse_acquisitions
from ocio.parsing import ParsedDocument, ParsedPartition


@cache
def corpus_documents() -> dict[str, ParsedDocument]:
    repository = Path(__file__).resolve().parents[3]
    sources = read_source_acquisitions(repository / "ocio_sources.yaml")
    return {document.codice: document for document in parse_acquisitions(sources)}


def partition_by_id(document: ParsedDocument, identifier: str) -> ParsedPartition:
    return next(
        partition
        for partition in document.partizioni
        if partition.identifier == identifier
    )


def test_akn_fixture_reconstructs_article_comma_and_letter() -> None:
    document = corpus_documents()["dlgs_81_2008"]
    article = partition_by_id(document, "art_11")
    comma = partition_by_id(document, "art_11__para_1")
    letter = partition_by_id(document, "art_11__para_1.__point_a")

    assert article.tipo == "articolo"
    assert article.marcatore == "11"
    assert comma.tipo == "comma"
    assert comma.marcatore == "1"
    assert letter.tipo == "lettera"
    assert letter.marcatore == "a"
    assert comma.genitore == article.identifier
    assert letter.genitore == comma.identifier
    assert "finanziamento" in letter.contenuto.casefold()
    assert comma.ordine < partition_by_id(document, "art_11__para_2").ordine
    assert document.snapshot_al.isoformat() == "2026-09-23"


def test_gazzetta_html_preserves_articles_annexes_and_source_paths() -> None:
    document = corpus_documents()["dm_11_04_2011"]
    article = partition_by_id(document, "art-1")
    annex = partition_by_id(document, "allegato-i")

    assert article.tipo == "articolo"
    assert article.marcatore == "1"
    assert article.contenuto
    assert annex.tipo == "allegato"
    assert annex.contenuto
    assert annex.rubrica == "Allegato I"
    annex_iii = partition_by_id(document, "allegato-iii")
    assert document.vigente_dal.isoformat() == "2011-07-28"
    assert annex_iii.vigente_dal.isoformat() == "2011-04-30"
    assert article.localizzatore["local_path"].endswith("2026-09-23-1.html")
    assert annex.localizzatore["local_path"].endswith("2026-09-23-allegato-i.html")
    assert article.ordine < annex.ordine


def test_pdf_faq_and_composite_decrees_keep_structure_and_page_spans() -> None:
    documents = corpus_documents()
    faq = documents["faq_accordo_59_2025"]
    question = next(
        partition
        for partition in faq.partizioni
        if partition.tipo == "domanda" and partition.identifier.endswith("quesito-1")
    )
    answer = next(
        partition
        for partition in faq.partizioni
        if partition.tipo == "risposta" and partition.genitore == question.identifier
    )
    decree = documents["dm_3_settembre_2021"]
    article = partition_by_id(decree, "documento/art-1")
    comma = partition_by_id(decree, "documento/art-1/comma-1")

    assert decree.vigente_dal.isoformat() == "2022-10-29"
    assert question.genitore is not None
    assert question.contenuto.startswith("Esiste reciprocità")
    assert answer.genitore == question.identifier
    assert answer.localizzatore["pagina_da"] == 1
    assert comma.genitore == article.identifier
    assert article.marcatore == "1"
    assert comma.marcatore == "1"
    assert "stabilisce" in comma.contenuto
    assert article.localizzatore["pagina_da"] == 5
    assert article.localizzatore["spans"][0]["page"] == 5
    assert "x0" in article.localizzatore["spans"][0]


def test_pdf_tables_keep_page_provenance_and_report_reconstruction_anomalies() -> None:
    document = corpus_documents()["di_30_11_2012"]
    tables = [
        partition for partition in document.partizioni if partition.tipo == "tabella"
    ]

    assert tables
    assert any(table.localizzatore["pagina_da"] == 3 for table in tables)
    assert all(table.contenuto and table.localizzatore["spans"] for table in tables)
    assert any(
        partition.localizzatore["pagina_da"] == 1
        and "PROCEDURE STANDARDIZZATE" in partition.contenuto
        for partition in document.partizioni
    )
    assert any(anomaly.page == 3 for anomaly in document.anomalie)


def test_agreement_pdf_joins_wrapped_headings_as_sibling_partitions() -> None:
    document = corpus_documents()["accordo_59_csr_2025"]
    headings = {
        partition.rubrica: partition
        for partition in document.partizioni
        if partition.rubrica
    }
    confined_spaces = headings[
        "RICONOSCIMENTO FORMAZIONE PREGRESSA DEI LAVORATORI, DATORI DI LAVORO E "
        "LAVORATORI AUTONOMI CHE OPERANO IN AMBIENTI SOSPETTI DI INQUINAMENTO O "
        "CONFINATI"
    ]
    equipment = headings[
        "RICONOSCIMENTO FORMAZIONE PREGRESSA DEGLI OPERATORI ADDETTI ALLA "
        "CONDUZIONE DI ATTREZZATURE DI CUI ALL’ARTICOLO 73, COMMA 5, DEL DECRETO "
        "LEGISLATIVO 9 APRILE 2008, N. 81/2008"
    ]

    assert confined_spaces.genitore == equipment.genitore
    parent = partition_by_id(document, confined_spaces.genitore)
    assert parent.rubrica == "DISPOSIZIONI TRANSITORIE"
    assert confined_spaces.localizzatore["pagina_da"] == 115
    assert equipment.localizzatore["pagina_da"] == 115


def test_corpus_parser_emits_thirteen_logical_current_documents() -> None:
    documents = corpus_documents()

    assert len(documents) == 13
    assert {
        "dm_1_settembre_2021",
        "dm_2_settembre_2021",
        "dm_3_settembre_2021",
    } <= documents.keys()
    assert documents["accordo_59_csr_2025"].tipo_documento == "accordo"
    assert documents["faq_accordo_59_2025"].tipo_documento == "faq"
    assert all(document.partizioni for document in documents.values())
    assert all(
        len({partition.identifier for partition in document.partizioni})
        == len(document.partizioni)
        for document in documents.values()
    )

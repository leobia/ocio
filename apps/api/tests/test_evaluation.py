"""Silver set schema and validation tests."""

from __future__ import annotations

import json
from typing import Any

from ocio.evaluation import (
    CorpusIndex,
    default_schema_path,
    format_validation_report,
    validate_lines,
)


def schema() -> dict[str, Any]:
    return json.loads(default_schema_path().read_text(encoding="utf-8"))


def case(**changes: Any) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "id": "silver-0001",
        "kind": "grounded",
        "query": "Qual è l’obbligo?",
        "difficulty": "easy",
        "answerable": True,
        "expected_evidence": [
            {"document_code": "documento", "partition_identifier": "art-1"}
        ],
    }
    value.update(changes)
    return value


def corpus() -> CorpusIndex:
    return CorpusIndex({"documento": True}, frozenset({("documento", "art-1")}))


def lines(*cases: dict[str, Any]) -> list[str]:
    return [json.dumps(value, ensure_ascii=False) for value in cases]


def test_valid_case_passes_schema_invariants_and_references() -> None:
    report = validate_lines(lines(case()), schema(), corpus())

    assert report.valid
    assert report.cases == 1
    assert format_validation_report(report) == "Silver set valido: 1 casi."


def test_schema_errors_are_accumulated() -> None:
    invalid = case(kind="unknown", difficulty="impossible")
    del invalid["query"]

    report = validate_lines(lines(invalid), schema(), corpus())

    assert not report.valid
    messages = [issue.message for issue in report.issues]
    assert any("'query' is a required property" in message for message in messages)
    assert any("kind" in message and "unknown" in message for message in messages)
    assert any(
        "difficulty" in message and "impossible" in message for message in messages
    )


def test_duplicate_ids_and_normalized_queries_are_rejected() -> None:
    report = validate_lines(
        lines(case(), case(query="  QUAL È  L’OBBLIGO?  ")), schema(), corpus()
    )

    assert [issue.message for issue in report.issues] == [
        "id duplicato 'silver-0001'; prima occorrenza alla riga 1",
        "query duplicata; prima occorrenza alla riga 1",
    ]


def test_answerability_invariants_are_enforced_by_the_schema() -> None:
    answerable_without_evidence = case(expected_evidence=[])
    negative_with_evidence = case(
        kind="hard_negative",
        answerable=False,
        expected_evidence=case()["expected_evidence"],
    )

    report = validate_lines(
        lines(answerable_without_evidence, negative_with_evidence), schema(), corpus()
    )

    assert not report.valid
    assert len(report.issues) == 2
    assert all("expected_evidence" in issue.message for issue in report.issues)


def test_malformed_json_and_blank_lines_are_reported_together() -> None:
    report = validate_lines(["{", ""], schema(), corpus())

    assert report.cases == 2
    assert len(report.issues) == 2
    assert "JSON non valido" in report.issues[0].message
    assert report.issues[1].message == "riga vuota"


def test_versioned_seed_matches_schema_and_exported_corpus() -> None:
    evaluation = default_schema_path().parents[1]
    corpus_rows = [
        json.loads(line)
        for line in (evaluation / "corpus-for-silver-set.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    index = CorpusIndex(
        {str(row["document_code"]): True for row in corpus_rows},
        frozenset(
            (str(row["document_code"]), str(row["partition_identifier"]))
            for row in corpus_rows
        ),
    )

    report = validate_lines(
        (evaluation / "silver-set-v1.jsonl").read_text(encoding="utf-8").splitlines(),
        schema(),
        index,
    )

    assert report.valid
    assert report.cases == 20

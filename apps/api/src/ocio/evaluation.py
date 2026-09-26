"""Export and validate retrieval evaluation datasets."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.database import database_url


class EvaluationError(Exception):
    """The evaluation corpus or dataset cannot be processed."""


@dataclass(frozen=True, slots=True)
class CorpusIndex:
    """Stable document and partition references available to an evaluation."""

    documents: Mapping[str, bool]
    partitions: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class CorpusExportReport:
    documents: int
    partitions: int
    output: Path


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    cases: int
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def default_schema_path() -> Path:
    """Return the repository schema used by the v1 dataset."""
    return (
        Path(__file__).resolve().parents[4]
        / "evaluation"
        / "schemas"
        / "silver-set-v1.schema.json"
    )


def corpus_records(connection: Connection) -> list[dict[str, Any]]:
    """Read the enabled, non-empty canonical corpus in deterministic order."""
    rows = connection.execute(
        text(
            "SELECT d.codice AS document_code, "
            "p.identificatore AS partition_identifier, "
            "d.titolo AS document_title, p.tipo AS partition_type, "
            "p.rubrica AS rubric, p.contenuto AS partition_text "
            "FROM partizioni_documentali AS p "
            "JOIN documenti AS d ON d.id = p.documento_id "
            "WHERE d.abilitato_per_agente "
            "AND length(btrim(p.contenuto)) > 0 "
            "ORDER BY d.codice, p.id"
        )
    ).mappings()
    return [dict(row) for row in rows]


def export_evaluation_corpus(output: Path) -> CorpusExportReport:
    """Export the current enabled corpus as compact JSONL for prompt input."""
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise EvaluationError(str(error)) from error
    try:
        with engine.connect() as connection:
            records = corpus_records(connection)
    finally:
        engine.dispose()
    if not records:
        raise EvaluationError("Il corpus abilitato non contiene partizioni con testo.")
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        for record in records
    )
    output.write_text(serialized + "\n", encoding="utf-8")
    return CorpusExportReport(
        documents=len({str(record["document_code"]) for record in records}),
        partitions=len(records),
        output=output,
    )


def load_corpus_index(connection: Connection) -> CorpusIndex:
    """Load stable references, including disabled documents for diagnostics."""
    documents = {
        str(row.codice): bool(row.abilitato_per_agente)
        for row in connection.execute(
            text("SELECT codice, abilitato_per_agente FROM documenti")
        )
    }
    partitions = frozenset(
        (str(row.codice), str(row.identificatore))
        for row in connection.execute(
            text(
                "SELECT d.codice, p.identificatore "
                "FROM partizioni_documentali AS p "
                "JOIN documenti AS d ON d.id = p.documento_id"
            )
        )
    )
    return CorpusIndex(documents, partitions)


def _schema_issue(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return f"schema {path}: {error.message}" if path else f"schema: {error.message}"


def validate_lines(
    lines: Iterable[str], schema: Mapping[str, Any], corpus: CorpusIndex
) -> ValidationReport:
    """Validate JSONL structure, cross-case invariants, and corpus references."""
    validator = Draft202012Validator(schema)
    issues: list[ValidationIssue] = []
    cases: list[tuple[int, dict[str, Any]]] = []
    total = 0
    for line_number, line in enumerate(lines, start=1):
        total += 1
        if not line.strip():
            issues.append(ValidationIssue(line_number, "riga vuota"))
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            issues.append(
                ValidationIssue(
                    line_number,
                    f"JSON non valido alla colonna {error.colno}: {error.msg}",
                )
            )
            continue
        schema_errors = sorted(
            validator.iter_errors(value), key=lambda error: list(error.absolute_path)
        )
        if schema_errors:
            issues.extend(
                ValidationIssue(line_number, _schema_issue(error))
                for error in schema_errors
            )
            continue
        cases.append((line_number, value))

    seen_ids: dict[str, int] = {}
    seen_queries: dict[str, int] = {}
    for line_number, case in cases:
        case_id = str(case["id"])
        query = str(case["query"])
        if case_id in seen_ids:
            issues.append(
                ValidationIssue(
                    line_number,
                    f"id duplicato {case_id!r}; prima occorrenza alla riga "
                    f"{seen_ids[case_id]}",
                )
            )
        else:
            seen_ids[case_id] = line_number
        normalized_query = " ".join(query.casefold().split())
        if normalized_query in seen_queries:
            issues.append(
                ValidationIssue(
                    line_number,
                    "query duplicata; prima occorrenza alla riga "
                    f"{seen_queries[normalized_query]}",
                )
            )
        else:
            seen_queries[normalized_query] = line_number

        for evidence in case["expected_evidence"]:
            document_code = str(evidence["document_code"])
            partition_identifier = str(evidence["partition_identifier"])
            if document_code not in corpus.documents:
                issues.append(
                    ValidationIssue(
                        line_number,
                        f"documento inesistente {document_code!r}",
                    )
                )
                continue
            if not corpus.documents[document_code]:
                issues.append(
                    ValidationIssue(
                        line_number,
                        f"documento non abilitato per l’agente {document_code!r}",
                    )
                )
            if (document_code, partition_identifier) not in corpus.partitions:
                issues.append(
                    ValidationIssue(
                        line_number,
                        f"partizione {partition_identifier!r} inesistente nel "
                        f"documento {document_code!r}",
                    )
                )
    return ValidationReport(total, tuple(issues))


def validate_silver_set(dataset: Path, schema_path: Path) -> ValidationReport:
    """Validate a JSONL dataset against its schema and the canonical corpus."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        lines = dataset.read_text(encoding="utf-8").splitlines()
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(str(error)) from error
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise EvaluationError(str(error)) from error
    try:
        with engine.connect() as connection:
            corpus = load_corpus_index(connection)
    finally:
        engine.dispose()
    return validate_lines(lines, schema, corpus)


def format_export_report(report: CorpusExportReport) -> str:
    return (
        f"Corpus di valutazione esportato: {report.documents} documenti, "
        f"{report.partitions} partizioni in {report.output}."
    )


def format_validation_report(report: ValidationReport) -> str:
    if report.valid:
        return f"Silver set valido: {report.cases} casi."
    details = "\n".join(
        f"- riga {issue.line}: {issue.message}" for issue in report.issues
    )
    return (
        f"Silver set non valido: {len(report.issues)} errori su "
        f"{report.cases} righe.\n{details}"
    )

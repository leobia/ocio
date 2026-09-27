"""Runner riproducibile per i benchmark di retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.bm25 import Bm25Retriever
from ocio.database import database_url
from ocio.evaluation import (
    default_schema_path,
    format_validation_report,
    load_corpus_index,
    validate_lines,
)
from ocio.postgres_fts import PostgresFtsRetriever
from ocio.retrieval import (
    PartitionReference,
    Ranking,
    RetrievalRun,
    RetrievalTraceError,
    Retriever,
    write_trace,
)

BENCHMARK_SCHEMA_VERSION = 1
ALPHA = 1.0
_RETRIEVERS = {"postgres_fts", "bm25"}


class BenchmarkError(Exception):
    """Il benchmark non può essere configurato o eseguito."""


@dataclass(frozen=True, slots=True)
class RetrieverConfiguration:
    name: str
    retriever: str


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    dataset: Path
    chunk_set_fingerprint: str
    top_k: int
    output_directory: Path
    configurations: tuple[RetrieverConfiguration, ...]
    schema_version: int = BENCHMARK_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    query: str
    answerable: bool
    expected_evidence: frozenset[PartitionReference]


@dataclass(frozen=True, slots=True)
class CaseMetrics:
    evidence_recall_at_k: float
    mrr_at_k: float
    alpha_ndcg_at_k: float
    covered_evidence: tuple[PartitionReference, ...]
    first_relevant_rank: int | None


@dataclass(frozen=True, slots=True)
class BenchmarkArtifacts:
    run_id: str
    manifest: Path
    trace: Path
    report: Path


RetrieverFactory = Callable[[str, Connection, str], Retriever]


def load_configuration(source: Path) -> BenchmarkConfiguration:
    """Carica e valida la configurazione YAML del benchmark."""
    try:
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise BenchmarkError(str(error)) from error
    if not isinstance(value, Mapping):
        raise BenchmarkError("La configurazione deve essere un oggetto YAML.")

    allowed = {
        "schema_version",
        "dataset",
        "chunk_set_fingerprint",
        "top_k",
        "output_directory",
        "configurations",
    }
    unknown = set(value) - allowed
    if unknown:
        raise BenchmarkError(f"Campi di configurazione sconosciuti: {sorted(unknown)}.")
    if value.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkError("schema_version deve essere 1.")

    fingerprint = value.get("chunk_set_fingerprint")
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise BenchmarkError("chunk_set_fingerprint deve essere uno SHA-256 esadecimale.")
    top_k = value.get("top_k")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise BenchmarkError("top_k deve essere un intero positivo.")

    dataset = _relative_path(source, value.get("dataset"), "dataset")
    output = _relative_path(source, value.get("output_directory"), "output_directory")
    raw_configurations = value.get("configurations")
    if not isinstance(raw_configurations, list) or not raw_configurations:
        raise BenchmarkError("configurations deve contenere almeno una configurazione.")

    configurations: list[RetrieverConfiguration] = []
    for index, item in enumerate(raw_configurations, start=1):
        if not isinstance(item, Mapping) or set(item) != {"name", "retriever"}:
            raise BenchmarkError(
                f"configurations[{index}] deve contenere soltanto name e retriever."
            )
        name = item["name"]
        retriever = item["retriever"]
        if not isinstance(name, str) or not name.strip():
            raise BenchmarkError(f"configurations[{index}].name non è valido.")
        if retriever not in _RETRIEVERS:
            raise BenchmarkError(
                f"Retriever {retriever!r} non supportato; usare postgres_fts o bm25."
            )
        configurations.append(RetrieverConfiguration(name, str(retriever)))
    names = [item.name for item in configurations]
    if len(names) != len(set(names)):
        raise BenchmarkError("I nomi delle configurazioni devono essere univoci.")

    return BenchmarkConfiguration(
        dataset=dataset,
        chunk_set_fingerprint=fingerprint,
        top_k=top_k,
        output_directory=output,
        configurations=tuple(configurations),
    )


def _relative_path(source: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{field} deve essere un percorso non vuoto.")
    path = Path(value)
    return path if path.is_absolute() else source.resolve().parent / path


def run_benchmark(configuration_path: Path) -> BenchmarkArtifacts:
    """Esegue tutte le configurazioni e scrive manifest, trace e report."""
    configuration = load_configuration(configuration_path)
    try:
        engine = create_engine(database_url())
    except RuntimeError as error:
        raise BenchmarkError(str(error)) from error
    try:
        with engine.connect() as connection:
            return execute_benchmark(configuration, connection)
    finally:
        engine.dispose()


def execute_benchmark(
    configuration: BenchmarkConfiguration,
    connection: Connection,
    retriever_factory: RetrieverFactory | None = None,
) -> BenchmarkArtifacts:
    """Esegue un benchmark usando una connessione già aperta."""
    cases, dataset_digest = _load_cases(configuration.dataset, connection)
    evidence_pool = _load_evidence_pool(
        connection, configuration.chunk_set_fingerprint
    )
    run_id = _run_id(configuration, dataset_digest)
    runs: list[RetrievalRun] = []
    configuration_reports: list[dict[str, Any]] = []
    effective_configurations: list[dict[str, Any]] = []
    factory = retriever_factory or _retriever

    for requested in configuration.configurations:
        retriever = factory(
            requested.retriever, connection, configuration.chunk_set_fingerprint
        )
        case_reports: list[dict[str, Any]] = []
        metrics: list[CaseMetrics] = []
        effective: dict[str, Any] | None = None
        for case in cases:
            try:
                ranking = retriever.retrieve(case.query, configuration.top_k)
            except Exception as error:
                raise BenchmarkError(
                    f"Configurazione {requested.name!r}, caso {case.case_id!r}: {error}"
                ) from error
            ranking = replace(
                ranking,
                configuration={
                    **ranking.configuration,
                    "benchmark_configuration": requested.name,
                    "retriever": requested.retriever,
                },
            )
            if effective is None:
                effective = ranking.configuration
            elif effective != ranking.configuration:
                raise BenchmarkError(
                    f"La configurazione effettiva di {requested.name!r} cambia fra i casi."
                )
            runs.append(
                RetrievalRun(
                    run_id=f"{run_id}:{requested.name}",
                    case_id=case.case_id,
                    query=case.query,
                    chunk_set_fingerprint=configuration.chunk_set_fingerprint,
                    rankings=(ranking,),
                )
            )
            report, case_metrics = _case_report(
                case, ranking, configuration.top_k, evidence_pool
            )
            case_reports.append(report)
            if case_metrics is not None:
                metrics.append(case_metrics)

        assert effective is not None
        effective_configurations.append(
            {
                "name": requested.name,
                "retriever": requested.retriever,
                "effective": effective,
            }
        )
        configuration_reports.append(
            _configuration_report(requested, case_reports, metrics)
        )

    output = configuration.output_directory
    trace_path = output / f"{run_id}.trace.jsonl"
    report_path = output / f"{run_id}.report.json"
    manifest_path = output / f"{run_id}.manifest.json"
    manifest = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "run_id": run_id,
        "dataset": str(configuration.dataset),
        "dataset_sha256": dataset_digest,
        "chunk_set_fingerprint": configuration.chunk_set_fingerprint,
        "top_k": configuration.top_k,
        "configurations": effective_configurations,
        "artifacts": {
            "trace": trace_path.name,
            "report": report_path.name,
        },
    }
    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "run_id": run_id,
        "top_k": configuration.top_k,
        "alpha": ALPHA,
        "configurations": configuration_reports,
    }
    try:
        output.mkdir(parents=True, exist_ok=True)
        write_trace(runs, trace_path)
        _write_json(report_path, report)
        _write_json(manifest_path, manifest)
    except (OSError, RetrievalTraceError) as error:
        raise BenchmarkError(str(error)) from error
    return BenchmarkArtifacts(run_id, manifest_path, trace_path, report_path)


def _load_cases(
    dataset: Path, connection: Connection
) -> tuple[tuple[EvaluationCase, ...], str]:
    try:
        content = dataset.read_bytes()
        lines = content.decode("utf-8").splitlines()
        schema = json.loads(default_schema_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkError(str(error)) from error
    validation = validate_lines(lines, schema, load_corpus_index(connection))
    if not validation.valid:
        raise BenchmarkError(format_validation_report(validation))
    if not lines:
        raise BenchmarkError("Il dataset non contiene casi di valutazione.")
    cases = tuple(_case(json.loads(line)) for line in lines)
    return cases, hashlib.sha256(content).hexdigest()


def _case(value: Mapping[str, Any]) -> EvaluationCase:
    return EvaluationCase(
        case_id=str(value["id"]),
        query=str(value["query"]),
        answerable=bool(value["answerable"]),
        expected_evidence=frozenset(
            PartitionReference(
                document_code=str(item["document_code"]),
                partition_identifier=str(item["partition_identifier"]),
            )
            for item in value["expected_evidence"]
        ),
    )


def _load_evidence_pool(
    connection: Connection, fingerprint: str
) -> tuple[frozenset[PartitionReference], ...]:
    rows = connection.execute(
        text(
            "SELECT documento.codice AS document_code, "
            "       fonte.identificatore_partizione AS partition_identifier, "
            "       chunk.id AS chunk_id "
            "FROM chunk "
            "JOIN insiemi_chunk AS insieme ON insieme.id = chunk.insieme_chunk_id "
            "JOIN documenti AS documento ON documento.id = chunk.documento_id "
            "JOIN chunk_partizioni AS fonte ON fonte.chunk_id = chunk.id "
            "WHERE insieme.fingerprint = :fingerprint "
            "  AND chunk.ruolo = 'ricercabile' "
            "  AND documento.abilitato_per_agente "
            "ORDER BY chunk.id, fonte.posizione"
        ),
        {"fingerprint": fingerprint},
    )
    grouped: dict[int, set[PartitionReference]] = {}
    for row in rows:
        grouped.setdefault(int(row.chunk_id), set()).add(
            PartitionReference(str(row.document_code), str(row.partition_identifier))
        )
    if not grouped:
        raise BenchmarkError(f"Insieme di chunk inesistente o vuoto: {fingerprint}.")
    return tuple(frozenset(value) for value in grouped.values())


def calculate_metrics(
    case: EvaluationCase,
    ranking: Ranking,
    top_k: int,
    evidence_pool: Sequence[frozenset[PartitionReference]],
) -> CaseMetrics:
    """Calcola metriche evidence-aware per un caso rispondibile."""
    if not case.answerable or not case.expected_evidence:
        raise BenchmarkError("Le metriche richiedono un caso rispondibile.")
    expected = case.expected_evidence
    covered: set[PartitionReference] = set()
    first_rank: int | None = None
    dcg = 0.0
    for item in ranking.candidates[:top_k]:
        matches = expected.intersection(item.candidate.source_partitions)
        novel = matches - covered
        if matches and first_rank is None:
            first_rank = item.rank
        if novel:
            dcg += len(novel) / math.log2(item.rank + 1)
            covered.update(novel)

    ideal_dcg = _ideal_dcg(expected, evidence_pool, top_k)
    return CaseMetrics(
        evidence_recall_at_k=len(covered) / len(expected),
        mrr_at_k=0.0 if first_rank is None else 1.0 / first_rank,
        alpha_ndcg_at_k=0.0 if ideal_dcg == 0 else dcg / ideal_dcg,
        covered_evidence=tuple(sorted(covered, key=_evidence_key)),
        first_relevant_rank=first_rank,
    )


def _ideal_dcg(
    expected: frozenset[PartitionReference],
    evidence_pool: Sequence[frozenset[PartitionReference]],
    top_k: int,
) -> float:
    # Con alpha=1 solo la prima occorrenza di un'evidenza produce guadagno.
    remaining = [coverage.intersection(expected) for coverage in evidence_pool]
    covered: set[PartitionReference] = set()
    result = 0.0
    for rank in range(1, top_k + 1):
        best = max(remaining, key=lambda value: len(value - covered), default=frozenset())
        novel = best - covered
        if not novel:
            break
        result += len(novel) / math.log2(rank + 1)
        covered.update(novel)
        remaining.remove(best)
    return result


def _case_report(
    case: EvaluationCase,
    ranking: Ranking,
    top_k: int,
    evidence_pool: Sequence[frozenset[PartitionReference]],
) -> tuple[dict[str, Any], CaseMetrics | None]:
    candidates = [
        {
            "rank": item.rank,
            "document_code": item.candidate.reference.document_code,
            "chunk_identifier": item.candidate.reference.chunk_identifier,
            "score": item.score,
            "covered_evidence": [
                asdict(evidence)
                for evidence in sorted(
                    case.expected_evidence.intersection(
                        item.candidate.source_partitions
                    ),
                    key=_evidence_key,
                )
            ],
        }
        for item in ranking.candidates[:top_k]
    ]
    base: dict[str, Any] = {
        "case_id": case.case_id,
        "query": case.query,
        "answerable": case.answerable,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if not case.answerable:
        return base, None
    metrics = calculate_metrics(case, ranking, top_k, evidence_pool)
    base["metrics"] = {
        "evidence_recall_at_k": metrics.evidence_recall_at_k,
        "mrr_at_k": metrics.mrr_at_k,
        "alpha_ndcg_at_k": metrics.alpha_ndcg_at_k,
        "first_relevant_rank": metrics.first_relevant_rank,
        "covered_evidence": [asdict(item) for item in metrics.covered_evidence],
    }
    return base, metrics


def _configuration_report(
    requested: RetrieverConfiguration,
    cases: list[dict[str, Any]],
    metrics: list[CaseMetrics],
) -> dict[str, Any]:
    negatives = [case for case in cases if not case["answerable"]]
    failures = [
        case["case_id"]
        for case in cases
        if case["answerable"]
        and case["metrics"]["evidence_recall_at_k"] == 0
    ]
    count = len(metrics)
    divisor = count or 1
    aggregate = {
        "answerable_cases": count,
        "evidence_recall_at_k": sum(item.evidence_recall_at_k for item in metrics)
        / divisor,
        "mrr_at_k": sum(item.mrr_at_k for item in metrics) / divisor,
        "alpha_ndcg_at_k": sum(item.alpha_ndcg_at_k for item in metrics) / divisor,
        "failed_queries": failures,
        "hard_negatives": {
            "cases": len(negatives),
            "empty_rankings": sum(case["candidate_count"] == 0 for case in negatives),
            "empty_ranking_rate": (
                0.0
                if not negatives
                else sum(case["candidate_count"] == 0 for case in negatives)
                / len(negatives)
            ),
        },
    }
    return {
        "name": requested.name,
        "retriever": requested.retriever,
        "aggregate": aggregate,
        "cases": cases,
    }


def _run_id(configuration: BenchmarkConfiguration, dataset_digest: str) -> str:
    value = {
        "schema_version": configuration.schema_version,
        "dataset_sha256": dataset_digest,
        "chunk_set_fingerprint": configuration.chunk_set_fingerprint,
        "top_k": configuration.top_k,
        "configurations": [asdict(item) for item in configuration.configurations],
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"benchmark-{hashlib.sha256(serialized.encode()).hexdigest()[:16]}"


def _retriever(kind: str, connection: Connection, fingerprint: str) -> Retriever:
    if kind == "postgres_fts":
        return PostgresFtsRetriever(connection, fingerprint)
    if kind == "bm25":
        return Bm25Retriever(connection, fingerprint)
    raise BenchmarkError(f"Retriever non supportato: {kind}.")


def _evidence_key(value: PartitionReference) -> tuple[str, str]:
    return value.document_code, value.partition_identifier


def _write_json(output: Path, value: object) -> None:
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

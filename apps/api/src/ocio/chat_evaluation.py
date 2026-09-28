"""Live comparison of versioned chat runtime profiles on the silver set."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from sqlalchemy import create_engine

from ocio.api import ChatBackend
from ocio.chat_runtime import RuntimeChatBackend, load_profile
from ocio.database import database_url


class ChatEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ChatEvaluationArtifacts:
    report: Path


def run_chat_evaluation(
    configuration: Path,
    backend_factory: Callable[[str], ChatBackend] | None = None,
) -> ChatEvaluationArtifacts:
    try:
        raw = yaml.safe_load(configuration.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ChatEvaluationError("schema_version evaluation non supportata")
        runtime_config = (configuration.parent / raw["runtime_config"]).resolve()
        dataset = (configuration.parent / raw["dataset"]).resolve()
        output = (configuration.parent / raw["output"]).resolve()
        profiles = tuple(str(item) for item in raw["profiles"])
        cases = tuple(
            json.loads(line)
            for line in dataset.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
        if isinstance(error, ChatEvaluationError):
            raise
        raise ChatEvaluationError(f"Evaluation chat non valida: {error}") from error
    if len(profiles) < 2 or not cases:
        raise ChatEvaluationError("Servono almeno due profili e un caso")

    engine = None
    if backend_factory is None:
        try:
            engine = create_engine(database_url())
        except RuntimeError as error:
            raise ChatEvaluationError(str(error)) from error

        def configured_backend(name: str) -> ChatBackend:
            assert engine is not None
            return RuntimeChatBackend(engine, load_profile(runtime_config, name))

        backend_factory = configured_backend
    try:
        results = []
        for profile in profiles:
            try:
                backend = backend_factory(profile)
            except Exception as error:
                raise ChatEvaluationError(
                    f"Profilo {profile!r} non avviabile: {error}"
                ) from error
            results.append(_evaluate(profile, backend, cases))
    finally:
        if engine is not None:
            engine.dispose()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"schema_version": 1, "profiles": results},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return ChatEvaluationArtifacts(output)


def _evaluate(
    name: str, backend: ChatBackend, cases: tuple[dict[str, Any], ...]
) -> dict[str, Any]:
    results = []
    for case in cases:
        started_at = perf_counter()
        try:
            reply = backend.answer(str(case["query"]), (), {})
        except Exception as error:
            results.append({
                "case_id": case["id"],
                "status": "ERROR",
                "passed": False,
                "error_type": type(error).__name__,
                "latency_ms": (perf_counter() - started_at) * 1000,
                "trace_present": False,
            })
            continue
        cited = {
            (
                str(citation["chunk"]["document_code"]),
                str(source["partition_identifier"]),
            )
            for citation in reply.citations
            for source in citation["sources"]
        }
        expected = {
            (str(item["document_code"]), str(item["partition_identifier"]))
            for item in case["expected_evidence"]
        }
        passed = (
            reply.status == "ANSWER" and expected <= cited
            if case["answerable"]
            else reply.status == "ABSTAIN"
        )
        results.append(
            {
                "case_id": case["id"],
                "status": reply.status,
                "passed": passed,
                "expected_evidence": sorted(expected),
                "cited_evidence": sorted(cited),
                "latency_ms": (perf_counter() - started_at) * 1000,
                "trace_present": reply.trace is not None,
            }
        )
    return {
        "name": name,
        "aggregate": {
            "cases": len(results),
            "passed": sum(item["passed"] for item in results),
            "success_rate": sum(item["passed"] for item in results) / len(results),
            "mean_latency_ms": sum(item["latency_ms"] for item in results)
            / len(results),
        },
        "cases": results,
    }

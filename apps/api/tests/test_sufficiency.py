"""Tests for the relevance and evidence-sufficiency gate."""

from __future__ import annotations

from typing import Any

import pytest

from ocio.retrieval import Candidate, ChunkReference, RankedCandidate, Ranking
from ocio.sufficiency import (
    AnswerPipeline,
    SufficiencyConfig,
    SufficiencyGate,
    SufficiencyRequest,
)


class FakeJudge:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.requests: list[SufficiencyRequest] = []

    def judge(self, request: SufficiencyRequest) -> dict[str, Any]:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Ranking]] = []

    def generate(self, question: str, ranking: Ranking) -> Any:
        self.calls.append((question, ranking))
        return "generated"


def ranking(*scores: float) -> Ranking:
    return Ranking(
        "rerank",
        tuple(
            RankedCandidate(
                Candidate(ChunkReference("doc", f"chunk-{index}"), "passage", ()),
                score,
                index,
            )
            for index, score in enumerate(scores, start=1)
        ),
        {},
        1.0,
    )


def gate(result: dict[str, Any] | Exception) -> tuple[SufficiencyGate, FakeJudge]:
    judge = FakeJudge(result)
    return SufficiencyGate(
        judge, SufficiencyConfig(0.5, 1, "judge-model", "prompt-v1")
    ), judge


@pytest.mark.parametrize("scores", [(), (0.49,)])
def test_obvious_failures_abstain_without_judge(scores: tuple[float, ...]) -> None:
    service, judge = gate({})

    result = service.evaluate("question", ranking(*scores))

    assert result.decision.decision == "ABSTAIN"
    assert result.decision.missing_information
    assert not judge.requests
    assert result.trace.configuration["minimum_score"] == 0.5
    assert result.trace.configuration["model"] == "judge-model"


def test_threshold_is_inclusive_and_answer_invokes_generator() -> None:
    service, judge = gate({
        "decision": "ANSWER",
        "reason_code": "SUFFICIENT",
        "missing_information": [],
        "evidence_ids": ["C1"],
    })
    generator = FakeGenerator()

    result = AnswerPipeline(service, generator).answer("question", ranking(0.5))  # type: ignore[arg-type]

    assert result.status == "ANSWER"
    assert len(judge.requests) == 1
    assert len(generator.calls) == 1
    assert result.sufficiency.error is None


def test_judge_abstention_never_invokes_generator() -> None:
    service, _ = gate({
        "decision": "ABSTAIN",
        "reason_code": "MISSING_SCOPE",
        "missing_information": ["Ambito di applicazione."],
        "evidence_ids": ["C1"],
    })
    generator = FakeGenerator()

    result = AnswerPipeline(service, generator).answer("question", ranking(0.8))  # type: ignore[arg-type]

    assert result.status == "ABSTAIN"
    assert result.decision.missing_information == ("Ambito di applicazione.",)
    assert not generator.calls


@pytest.mark.parametrize(
    "judge_result",
    [
        {
            "decision": "ANSWER", "reason_code": "SUFFICIENT",
            "missing_information": [], "evidence_ids": ["UNKNOWN"],
        },
        {"decision": "MAYBE"},
        RuntimeError("provider down"),
    ],
)
def test_invalid_output_and_provider_failure_fail_closed(
    judge_result: dict[str, Any] | Exception,
) -> None:
    service, _ = gate(judge_result)
    generator = FakeGenerator()

    result = AnswerPipeline(service, generator).answer("question", ranking(0.8))  # type: ignore[arg-type]

    assert result.status == "ABSTAIN"
    assert result.decision.reason_code == "JUDGE_ERROR"
    assert result.decision.missing_information
    assert result.sufficiency.error is not None
    assert not generator.calls


def test_configuration_is_validated() -> None:
    with pytest.raises(ValueError):
        SufficiencyConfig(float("nan"), 1, "model")
    with pytest.raises(ValueError):
        SufficiencyConfig(0.5, 0, "model")

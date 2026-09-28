"""Evidence sufficiency gate between retrieval and grounded generation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, Literal, Protocol

from ocio.generation import GenerationResult, GroundedAnswerGenerator
from ocio.retrieval import Ranking

Decision = Literal["ANSWER", "ABSTAIN"]


@dataclass(frozen=True, slots=True)
class SufficiencyConfig:
    minimum_score: float
    minimum_evidence: int
    model: str
    prompt_version: str = "sufficiency-v1"

    def __post_init__(self) -> None:
        if not math.isfinite(self.minimum_score):
            raise ValueError("minimum_score must be finite")
        if self.minimum_evidence < 1:
            raise ValueError("minimum_evidence must be positive")
        if not self.model.strip() or not self.prompt_version.strip():
            raise ValueError("model and prompt_version must be non-empty")


@dataclass(frozen=True, slots=True)
class SufficiencyEvidence:
    evidence_id: str
    passage: str
    score: float


@dataclass(frozen=True, slots=True)
class SufficiencyRequest:
    question: str
    evidence: tuple[SufficiencyEvidence, ...]
    model: str
    prompt_version: str
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class SufficiencyDecision:
    decision: Decision
    reason_code: str
    missing_information: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SufficiencyTrace:
    question: str
    configuration: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    decision: Decision
    reason_code: str
    missing_information: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    latency_ms: float
    error: dict[str, str] | None
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class SufficiencyResult:
    decision: SufficiencyDecision
    trace: SufficiencyTrace


class SufficiencyJudge(Protocol):
    def judge(self, request: SufficiencyRequest) -> Mapping[str, Any]: ...


class SufficiencyGate:
    def __init__(self, judge: SufficiencyJudge, config: SufficiencyConfig) -> None:
        self.judge = judge
        self.config = config

    def evaluate(self, question: str, ranking: Ranking) -> SufficiencyResult:
        started_at = perf_counter()
        evidence = tuple(
            SufficiencyEvidence(f"C{index}", item.candidate.content, item.score)
            for index, item in enumerate(ranking.candidates, start=1)
        )
        obvious = self._obvious_failure(question, evidence)
        if obvious is not None:
            return self._result(question, evidence, obvious, started_at)
        try:
            raw = self.judge.judge(SufficiencyRequest(
                question, evidence, self.config.model, self.config.prompt_version
            ))
            decision = _validate_decision(raw, {item.evidence_id for item in evidence})
            return self._result(question, evidence, decision, started_at)
        except Exception as error:
            decision = SufficiencyDecision(
                "ABSTAIN", "JUDGE_ERROR",
                ("Non è stato possibile verificare la sufficienza delle evidenze.",),
                (),
            )
            return self._result(question, evidence, decision, started_at, error)

    def _obvious_failure(
        self, question: str, evidence: tuple[SufficiencyEvidence, ...]
    ) -> SufficiencyDecision | None:
        if not question.strip():
            return SufficiencyDecision(
                "ABSTAIN", "EMPTY_QUESTION", ("La domanda è vuota.",), ()
            )
        if len(evidence) < self.config.minimum_evidence:
            return SufficiencyDecision(
                "ABSTAIN", "INSUFFICIENT_EVIDENCE_COUNT",
                (f"Servono almeno {self.config.minimum_evidence} evidenze pertinenti.",),
                tuple(item.evidence_id for item in evidence),
            )
        relevant = tuple(
            item.evidence_id
            for item in evidence
            if item.score >= self.config.minimum_score
        )
        if len(relevant) < self.config.minimum_evidence:
            return SufficiencyDecision(
                "ABSTAIN", "BELOW_RELEVANCE_THRESHOLD",
                ("Mancano evidenze con rilevanza sufficiente.",), relevant,
            )
        return None

    def _result(
        self,
        question: str,
        evidence: tuple[SufficiencyEvidence, ...],
        decision: SufficiencyDecision,
        started_at: float,
        error: Exception | None = None,
    ) -> SufficiencyResult:
        trace = SufficiencyTrace(
            question=question,
            configuration={
                "minimum_score": self.config.minimum_score,
                "minimum_evidence": self.config.minimum_evidence,
                "model": self.config.model,
                "prompt_version": self.config.prompt_version,
                "output_schema_version": 1,
            },
            evidence=tuple(asdict(item) for item in evidence),
            decision=decision.decision,
            reason_code=decision.reason_code,
            missing_information=decision.missing_information,
            evidence_ids=decision.evidence_ids,
            latency_ms=(perf_counter() - started_at) * 1000,
            error=(
                {"type": type(error).__name__, "message": str(error)}
                if error is not None else None
            ),
        )
        return SufficiencyResult(decision, trace)


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    status: Literal["ANSWER"]
    generation: GenerationResult
    sufficiency: SufficiencyTrace


@dataclass(frozen=True, slots=True)
class AbstentionOutcome:
    status: Literal["ABSTAIN"]
    decision: SufficiencyDecision
    sufficiency: SufficiencyTrace


class AnswerPipeline:
    def __init__(
        self, gate: SufficiencyGate, generator: GroundedAnswerGenerator
    ) -> None:
        self.gate = gate
        self.generator = generator

    def answer(
        self, question: str, ranking: Ranking
    ) -> AnswerOutcome | AbstentionOutcome:
        result = self.gate.evaluate(question, ranking)
        if result.decision.decision == "ABSTAIN":
            return AbstentionOutcome("ABSTAIN", result.decision, result.trace)
        return AnswerOutcome(
            "ANSWER", self.generator.generate(question, ranking), result.trace
        )


def _validate_decision(
    raw: Mapping[str, Any], known_evidence: set[str]
) -> SufficiencyDecision:
    expected = {"decision", "reason_code", "missing_information", "evidence_ids"}
    if set(raw) != expected or raw["decision"] not in ("ANSWER", "ABSTAIN"):
        raise ValueError("invalid sufficiency decision schema")
    reason = raw["reason_code"]
    missing = raw["missing_information"]
    identifiers = raw["evidence_ids"]
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("invalid reason_code")
    if not isinstance(missing, list) or any(
        not isinstance(item, str) or not item.strip() for item in missing
    ):
        raise ValueError("invalid missing_information")
    if not isinstance(identifiers, list) or any(
        not isinstance(item, str) for item in identifiers
    ):
        raise ValueError("invalid evidence_ids")
    if unknown := set(identifiers) - known_evidence:
        raise ValueError(f"unknown evidence IDs: {sorted(unknown)}")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate evidence IDs")
    if raw["decision"] == "ANSWER" and not identifiers:
        raise ValueError("ANSWER requires evidence")
    if raw["decision"] == "ABSTAIN" and not missing:
        raise ValueError("ABSTAIN requires missing information")
    return SufficiencyDecision(
        raw["decision"], reason.strip(),
        tuple(item.strip() for item in missing), tuple(identifiers),
    )

"""Server-side composition of the real OCIO chat pipeline."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import tiktoken
import yaml
from openai import OpenAI
from sqlalchemy import Engine

from ocio.api import Reply
from ocio.cohere_reranker import CohereReranker, reranker_from_environment
from ocio.conversation import (
    CaseFact,
    CaseState,
    Conversation,
    Message,
    QueryRewrite,
    rewrite_query,
)
from ocio.dense import DenseRetriever
from ocio.embeddings import CONFIGS, OpenAIEmbeddingClient
from ocio.generation import (
    GenerationConfig,
    GroundedAnswerGenerator,
    PostgresCitationResolver,
)
from ocio.openai_generation import (
    OpenAIAnswerProvider,
    OpenAIQueryRewriter,
    OpenAISufficiencyJudge,
    ResponsesClient,
)
from ocio.retrieval import RankedCandidate, Ranking
from ocio.sufficiency import (
    AbstentionOutcome,
    AnswerPipeline,
    SufficiencyConfig,
    SufficiencyGate,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "chat-runtime-v1.yaml"


class ChatConfigurationError(ValueError):
    """The selected server-owned chat configuration is invalid."""


@dataclass(frozen=True, slots=True)
class ChatProfile:
    chunk_set_fingerprint: str
    embedding: str
    reranker: Literal["cohere"] | None
    candidate_k: int
    top_k: int
    rewrite_model: str
    rewrite_prompt: str
    rewrite_token_budget: int
    rewrite_reasoning_effort: str
    rewrite_max_output_tokens: int
    sufficiency_model: str
    sufficiency_prompt: str
    sufficiency_reasoning_effort: str
    sufficiency_max_output_tokens: int
    minimum_score: float
    minimum_evidence: int
    generation_model: str
    generation_prompt: str
    generation_reasoning_effort: str
    max_output_tokens: int
    timeout_seconds: float
    max_retries: int


class RuntimeChatBackend:
    """Run rewrite, retrieval, sufficiency and grounded generation per request."""

    def __init__(self, engine: Engine, profile: ChatProfile) -> None:
        self.engine = engine
        self.profile = profile
        client = OpenAI(
            api_key=_required_secret("OPENAI_API_KEY"),
            timeout=profile.timeout_seconds,
            max_retries=profile.max_retries,
        )
        responses = cast(ResponsesClient, client.responses)
        self.rewriter = OpenAIQueryRewriter(
            responses,
            profile.rewrite_model,
            profile.rewrite_prompt,
            profile.rewrite_reasoning_effort,
            profile.rewrite_max_output_tokens,
        )
        self.judge = OpenAISufficiencyJudge(
            responses,
            profile.sufficiency_reasoning_effort,
            profile.sufficiency_max_output_tokens,
        )
        self.provider = OpenAIAnswerProvider(responses)
        self.embedding_client = OpenAIEmbeddingClient(
            timeout=profile.timeout_seconds, max_retries=profile.max_retries
        )
        self.reranker: CohereReranker | None = (
            reranker_from_environment(profile.timeout_seconds)
            if profile.reranker == "cohere"
            else None
        )
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def answer(
        self,
        question: str,
        history: Sequence[Mapping[str, Any]],
        case_state: Mapping[str, Mapping[str, Any]],
    ) -> Reply:
        conversation = _conversation(history, case_state, question)
        rewrite = rewrite_query(
            conversation,
            question,
            self.rewriter,
            token_budget=self.profile.rewrite_token_budget,
            count_tokens=lambda value: len(self.encoding.encode(value)),
        )
        if rewrite.decision == "CLARIFY":
            assert rewrite.clarification is not None
            return Reply(
                "ABSTAIN",
                rewrite.clarification,
                missing_information=(rewrite.clarification,),
                trace={"rewrite": _rewrite_trace(rewrite, self.profile)},
            )

        assert rewrite.standalone_query is not None
        with self.engine.connect() as connection:
            ranking = DenseRetriever(
                connection,
                self.profile.chunk_set_fingerprint,
                CONFIGS[self.profile.embedding],
                self.embedding_client,
            ).retrieve(rewrite.standalone_query, self.profile.candidate_k)
            if self.reranker is not None:
                ranking = self.reranker.rerank(
                    rewrite.standalone_query, ranking, self.profile.top_k
                )
                ranking = Ranking(
                    ranking.stage,
                    ranking.candidates,
                    {
                        **ranking.configuration,
                        "chunk_set_fingerprint": self.profile.chunk_set_fingerprint,
                    },
                    ranking.latency_ms,
                )
            else:
                ranking = _limit_ranking(ranking, self.profile.top_k)
            pipeline = AnswerPipeline(
                SufficiencyGate(
                    self.judge,
                    SufficiencyConfig(
                        self.profile.minimum_score,
                        self.profile.minimum_evidence,
                        self.profile.sufficiency_model,
                        self.profile.sufficiency_prompt,
                    ),
                ),
                GroundedAnswerGenerator(
                    PostgresCitationResolver(connection),
                    self.provider,
                    GenerationConfig(
                        self.profile.generation_model,
                        self.profile.generation_prompt,
                        {
                            "max_output_tokens": self.profile.max_output_tokens,
                            "reasoning": {
                                "effort": self.profile.generation_reasoning_effort
                            },
                        },
                    ),
                ),
            )
            outcome = pipeline.answer(question, ranking)

        trace: dict[str, Any] = {
            "rewrite": _rewrite_trace(rewrite, self.profile),
            "retrieval": asdict(ranking),
            "sufficiency": asdict(outcome.sufficiency),
        }
        if isinstance(outcome, AbstentionOutcome):
            return Reply(
                "ABSTAIN",
                "Non ho evidenze sufficienti per rispondere in modo verificabile.",
                missing_information=outcome.decision.missing_information,
                trace=trace,
            )

        answer = outcome.generation.answer
        trace["generation"] = asdict(outcome.generation.trace)
        return Reply(
            "ANSWER",
            "\n\n".join(claim.text for claim in answer.claims),
            tuple(asdict(citation) for citation in answer.citations),
            answer.missing_data,
            answer.conditions,
            trace,
        )


def backend_from_environment(engine: Engine) -> RuntimeChatBackend | None:
    """Return no backend unless a server-side profile is explicitly selected."""
    profile_name = os.environ.get("OCIO_CHAT_PROFILE")
    if not profile_name:
        return None
    path = Path(os.environ.get("OCIO_CHAT_CONFIG", DEFAULT_CONFIG))
    return RuntimeChatBackend(engine, load_profile(path, profile_name))


def load_profile(path: Path, profile_name: str) -> ChatProfile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ChatConfigurationError("schema_version chat non supportata")
        profiles = raw["profiles"]
        value = profiles[profile_name]
        if not isinstance(value, dict):
            raise TypeError("profile must be an object")
        retrieval = value["retrieval"]
        rewrite = value["rewrite"]
        sufficiency = value["sufficiency"]
        generation = value["generation"]
        limits = value["limits"]
        if (
            retrieval["embedding_provider"] != "openai"
            or rewrite["provider"] != "openai"
            or sufficiency["provider"] != "openai"
            or generation["provider"] != "openai"
        ):
            raise ChatConfigurationError("Provider chat non supportato")
        profile = ChatProfile(
            chunk_set_fingerprint=str(retrieval["chunk_set_fingerprint"]),
            embedding=str(retrieval["embedding"]),
            reranker=retrieval.get("reranker"),
            candidate_k=int(retrieval["candidate_k"]),
            top_k=int(retrieval["top_k"]),
            rewrite_model=str(rewrite["model"]),
            rewrite_prompt=str(rewrite["prompt_version"]),
            rewrite_token_budget=int(rewrite["token_budget"]),
            rewrite_reasoning_effort=str(rewrite["reasoning_effort"]),
            rewrite_max_output_tokens=int(rewrite["max_output_tokens"]),
            sufficiency_model=str(sufficiency["model"]),
            sufficiency_prompt=str(sufficiency["prompt_version"]),
            sufficiency_reasoning_effort=str(sufficiency["reasoning_effort"]),
            sufficiency_max_output_tokens=int(sufficiency["max_output_tokens"]),
            minimum_score=float(sufficiency["minimum_score"]),
            minimum_evidence=int(sufficiency["minimum_evidence"]),
            generation_model=str(generation["model"]),
            generation_prompt=str(generation["prompt_version"]),
            generation_reasoning_effort=str(generation["reasoning_effort"]),
            max_output_tokens=int(generation["max_output_tokens"]),
            timeout_seconds=float(limits["timeout_seconds"]),
            max_retries=int(limits["max_retries"]),
        )
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
        if isinstance(error, ChatConfigurationError):
            raise
        raise ChatConfigurationError(
            f"Configurazione chat non valida: {error}"
        ) from error
    if (
        profile.embedding not in CONFIGS
        or profile.reranker not in (None, "cohere")
        or profile.candidate_k < profile.top_k
        or profile.top_k < 1
        or profile.rewrite_token_budget < 1
        or profile.rewrite_max_output_tokens < 1
        or profile.minimum_evidence < 1
        or profile.sufficiency_max_output_tokens < 1
        or profile.max_output_tokens < 1
        or profile.timeout_seconds <= 0
        or profile.max_retries < 0
        or any(
            not item.strip()
            for item in (
                profile.chunk_set_fingerprint,
                profile.rewrite_model,
                profile.rewrite_prompt,
                profile.rewrite_reasoning_effort,
                profile.sufficiency_model,
                profile.sufficiency_prompt,
                profile.sufficiency_reasoning_effort,
                profile.generation_model,
                profile.generation_prompt,
                profile.generation_reasoning_effort,
            )
        )
    ):
        raise ChatConfigurationError("Valori del profilo chat non validi")
    return profile


def _conversation(
    history: Sequence[Mapping[str, Any]],
    state: Mapping[str, Mapping[str, Any]],
    question: str,
) -> Conversation:
    messages = (
        history[:-1] if history and history[-1].get("content") == question else history
    )
    log = tuple(
        Message(
            str(item["id"]),
            item["role"],
            str(item["content"]),
            _datetime(item.get("created_at")),
        )
        for item in messages
        if item.get("role") in ("user", "assistant")
    )
    facts = tuple(
        sorted(
            (
                name,
                CaseFact(
                    _fact_value(value.get("value")),
                    str(value.get("source_message_id") or "case_state"),
                    value.get("status", "unknown"),
                    _datetime(value.get("updated_at")),
                ),
            )
            for name, value in state.items()
        )
    )
    return Conversation(log, CaseState(facts))


def _fact_value(value: object) -> str | int | bool | tuple[str, ...] | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(UTC)


def _limit_ranking(ranking: Ranking, limit: int) -> Ranking:
    candidates = tuple(
        RankedCandidate(item.candidate, item.score, rank, item.contributions)
        for rank, item in enumerate(ranking.candidates[:limit], start=1)
    )
    return Ranking(ranking.stage, candidates, ranking.configuration, ranking.latency_ms)


def _rewrite_trace(rewrite: QueryRewrite, profile: ChatProfile) -> dict[str, Any]:
    return {
        "model": profile.rewrite_model,
        "prompt_version": profile.rewrite_prompt,
        "reasoning_effort": profile.rewrite_reasoning_effort,
        "decision": rewrite.decision,
        "original_query": rewrite.original_query,
        "standalone_query": rewrite.standalone_query,
        "clarification": rewrite.clarification,
        "recent_turn_ids": rewrite.recent_turn_ids,
    }


def _required_secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ChatConfigurationError(f"{name} non è impostata sul server")
    return value

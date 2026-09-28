"""OpenAI adapter for grounded structured generation."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, cast

from openai import OpenAI, OpenAIError

from ocio.conversation import RewriteRequest
from ocio.generation import (
    AnswerProvider,
    ProviderGenerationError,
    ProviderRequest,
)
from ocio.sufficiency import SufficiencyRequest


class ResponsesClient(Protocol):
    def create(self, **request: Any) -> object: ...


class OpenAIAnswerProvider:
    """Send only opaque evidence IDs and passages to OpenAI."""

    def __init__(self, client: ResponsesClient) -> None:
        self.client = client

    def generate(self, request: ProviderRequest) -> dict[str, Any]:
        evidence = [
            {"citation_id": item.citation_id, "passage": item.passage}
            for item in request.evidence
        ]
        try:
            response = self.client.create(
                model=request.model,
                instructions=(
                    "Answer the question only from the supplied evidence. "
                    "Return each normative claim separately and cite one or more "
                    "supplied citation_id values. Never invent IDs or provenance."
                ),
                input=json.dumps(
                    {"question": request.question, "evidence": evidence},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "grounded_answer",
                        "strict": True,
                        "schema": GROUNDED_ANSWER_SCHEMA,
                    }
                },
                store=False,
                **request.parameters,
            )
        except (OpenAIError, TypeError, ValueError) as error:
            raise ProviderGenerationError(f"Chiamata OpenAI fallita: {error}") from error
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise ProviderGenerationError("OpenAI non ha restituito output strutturato.")
        try:
            value = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ProviderGenerationError("Output OpenAI non decodificabile.") from error
        if not isinstance(value, dict):
            raise ProviderGenerationError("Output OpenAI non è un oggetto JSON.")
        return value


class OpenAISufficiencyJudge:
    """Evaluate whether supplied passages can answer the question."""

    def __init__(
        self, client: ResponsesClient, reasoning_effort: str = "low",
        max_output_tokens: int = 500,
    ) -> None:
        self.client = client
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens

    def judge(self, request: SufficiencyRequest) -> dict[str, Any]:
        try:
            response = self.client.create(
                model=request.model,
                instructions=(
                    "Decide whether the supplied evidence is relevant and sufficient "
                    "to answer the question. Return ANSWER only when it is sufficient."
                ),
                input=json.dumps(
                    {"question": request.question, "evidence": [
                        {"evidence_id": item.evidence_id, "passage": item.passage}
                        for item in request.evidence
                    ]},
                    ensure_ascii=False, separators=(",", ":"),
                ),
                text={"format": {
                    "type": "json_schema", "name": "sufficiency_decision",
                    "strict": True, "schema": SUFFICIENCY_SCHEMA,
                }},
                reasoning={"effort": self.reasoning_effort},
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
        except (OpenAIError, TypeError, ValueError) as error:
            raise ProviderGenerationError(f"Chiamata OpenAI fallita: {error}") from error
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise ProviderGenerationError("OpenAI non ha restituito il giudizio.")
        try:
            value = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ProviderGenerationError("Giudizio OpenAI non decodificabile.") from error
        if not isinstance(value, dict):
            raise ProviderGenerationError("Il giudizio OpenAI non è un oggetto JSON.")
        return value


class OpenAIQueryRewriter:
    """Rewrite only the bounded conversation context supplied by the domain."""

    def __init__(
        self, client: ResponsesClient, model: str, prompt_version: str,
        reasoning_effort: str = "low", max_output_tokens: int = 500,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_version = prompt_version
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens

    def rewrite(self, request: RewriteRequest) -> dict[str, Any]:
        payload = {
            "question": request.original_query,
            "recent_messages": [
                {"role": item.role, "content": item.content}
                for item in request.recent_messages
            ],
            "case_state": {
                name: {"value": fact.value, "status": fact.status}
                for name, fact in request.case_state.facts
            },
        }
        try:
            response = self.client.create(
                model=self.model,
                instructions=(
                    "Rewrite the last user question as a standalone Italian search "
                    "query, preserving exact legal references and facts. If the "
                    "context permits incompatible interpretations, ask one concise "
                    "clarifying question instead of guessing."
                ),
                input=json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                ),
                text={"format": {
                    "type": "json_schema", "name": "query_rewrite",
                    "strict": True, "schema": QUERY_REWRITE_SCHEMA,
                }},
                max_output_tokens=self.max_output_tokens,
                reasoning={"effort": self.reasoning_effort},
                store=False,
            )
        except (OpenAIError, TypeError, ValueError) as error:
            raise ProviderGenerationError(f"Chiamata OpenAI fallita: {error}") from error
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise ProviderGenerationError("OpenAI non ha restituito la riscrittura.")
        try:
            value = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ProviderGenerationError(
                "Riscrittura OpenAI non decodificabile."
            ) from error
        if not isinstance(value, dict):
            raise ProviderGenerationError(
                "La riscrittura OpenAI non è un oggetto JSON."
            )
        return value


def provider_from_environment() -> AnswerProvider:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ProviderGenerationError(
            "OPENAI_API_KEY non è impostata; configurarla sul server."
        )
    return OpenAIAnswerProvider(
        cast(ResponsesClient, OpenAI(api_key=api_key).responses)
    )


GROUNDED_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "citation_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["text", "citation_ids"],
                "additionalProperties": False,
            },
        },
        "conditions": {"type": "array", "items": {"type": "string"}},
        "missing_data": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "conditions", "missing_data"],
    "additionalProperties": False,
}


SUFFICIENCY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ANSWER", "ABSTAIN"]},
        "reason_code": {"type": "string", "minLength": 1},
        "missing_information": {
            "type": "array", "items": {"type": "string", "minLength": 1}
        },
        "evidence_ids": {
            "type": "array", "items": {"type": "string", "minLength": 1},
        },
    },
    "required": ["decision", "reason_code", "missing_information", "evidence_ids"],
    "additionalProperties": False,
}


QUERY_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["RETRIEVE", "CLARIFY"]},
        "standalone_query": {"type": ["string", "null"]},
        "clarification": {"type": ["string", "null"]},
    },
    "required": ["decision", "standalone_query", "clarification"],
    "additionalProperties": False,
}

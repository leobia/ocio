"""OpenAI adapter for grounded structured generation."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, cast

from openai import OpenAI, OpenAIError

from ocio.generation import (
    AnswerProvider,
    ProviderGenerationError,
    ProviderRequest,
)


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

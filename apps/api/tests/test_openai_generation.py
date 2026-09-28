"""Offline tests for the OpenAI grounded-answer adapter."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ocio.conversation import Conversation, RewriteRequest
from ocio.generation import ProviderEvidence, ProviderGenerationError, ProviderRequest
from ocio.openai_generation import (
    OpenAIAnswerProvider,
    OpenAIQueryRewriter,
    OpenAISufficiencyJudge,
    provider_from_environment,
)
from ocio.sufficiency import SufficiencyEvidence, SufficiencyRequest


@dataclass
class Response:
    output_text: str


class FakeResponses:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **request: object) -> object:
        self.calls.append(request)
        return self.response


def request() -> ProviderRequest:
    return ProviderRequest(
        "domanda", (ProviderEvidence("C1", "passaggio"),), "test-model",
        {"temperature": 0}, "prompt-v1", 1,
    )


def test_uses_responses_strict_schema_without_sending_provenance() -> None:
    client = FakeResponses(Response(
        '{"claims":[{"text":"claim","citation_ids":["C1"]}],'
        '"conditions":[],"missing_data":[]}'
    ))

    result = OpenAIAnswerProvider(client).generate(request())

    assert result["claims"][0]["citation_ids"] == ["C1"]
    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["store"] is False
    assert call["temperature"] == 0
    assert "passaggio" in str(call["input"])
    assert "https://" not in str(call["input"])
    assert call["text"]["format"]["strict"] is True  # type: ignore[index]


@pytest.mark.parametrize("response", [Response("not-json"), object()])
def test_rejects_invalid_openai_output(response: object) -> None:
    with pytest.raises(ProviderGenerationError):
        OpenAIAnswerProvider(FakeResponses(response)).generate(request())


def test_live_adapter_requires_server_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProviderGenerationError, match="OPENAI_API_KEY"):
        provider_from_environment()


def test_sufficiency_judge_uses_strict_schema() -> None:
    client = FakeResponses(Response(
        '{"decision":"ANSWER","reason_code":"SUFFICIENT",'
        '"missing_information":[],"evidence_ids":["C1"]}'
    ))
    judge_request = SufficiencyRequest(
        "domanda", (SufficiencyEvidence("C1", "passaggio", 0.9),),
        "judge-model", "prompt-v1",
    )

    result = OpenAISufficiencyJudge(client).judge(judge_request)

    assert result["decision"] == "ANSWER"
    call = client.calls[0]
    assert call["model"] == "judge-model"
    assert call["store"] is False
    assert call["text"]["format"]["strict"] is True  # type: ignore[index]
    assert "uniqueItems" not in call["text"]["format"]["schema"]["properties"][  # type: ignore[index]
        "evidence_ids"
    ]


def test_query_rewriter_uses_bounded_context_and_strict_schema() -> None:
    client = FakeResponses(Response(
        '{"decision":"RETRIEVE","standalone_query":"Quali DPI servono?",'
        '"clarification":null}'
    ))
    conversation = Conversation().append("turn-1", "user", "Parliamo dei DPI")

    result = OpenAIQueryRewriter(
        client, "rewrite-model", "rewrite-v1"
    ).rewrite(RewriteRequest(
        "E quali servono?", conversation.log, conversation.case_state
    ))

    assert result["standalone_query"] == "Quali DPI servono?"
    call = client.calls[0]
    assert call["model"] == "rewrite-model"
    assert call["store"] is False
    assert call["reasoning"] == {"effort": "low"}
    assert "Parliamo dei DPI" in str(call["input"])
    assert call["text"]["format"]["strict"] is True  # type: ignore[index]

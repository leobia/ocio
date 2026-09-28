"""Tests for layered conversational state."""

from datetime import UTC, datetime
from typing import Any

from ocio.conversation import Conversation, RewriteRequest, rewrite_query

NOW = datetime(2026, 9, 28, tzinfo=UTC)


class Rewriter:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.request: RewriteRequest | None = None

    def rewrite(self, request: RewriteRequest) -> dict[str, Any]:
        self.request = request
        return self.result


def words(value: str) -> int:
    return len(value.split())


def test_correction_replaces_case_fact_without_changing_the_log() -> None:
    conversation = Conversation().append(
        "turn-1", "user", "Abbiamo 12 dipendenti", created_at=NOW
    )
    conversation = conversation.record_fact("employee_count", 12, "turn-1", updated_at=NOW)
    old_log = conversation.log

    corrected = conversation.append("turn-2", "user", "Correzione: sono 18", created_at=NOW)
    corrected = corrected.record_fact("employee_count", 18, "turn-2", updated_at=NOW)

    assert corrected.log[:1] == old_log
    current_fact = corrected.case_state.get("employee_count")
    previous_fact = conversation.case_state.get("employee_count")
    assert current_fact is not None
    assert previous_fact is not None
    assert (current_fact.value, current_fact.source_turn_id) == (18, "turn-2")
    assert previous_fact.value == 12


def test_topic_change_only_exposes_the_recent_token_window() -> None:
    conversation = Conversation()
    conversation = conversation.append("turn-1", "user", "vecchio tema amianto", created_at=NOW)
    conversation = conversation.append("turn-2", "assistant", "vecchia risposta", created_at=NOW)
    conversation = conversation.append("turn-3", "user", "nuovo tema dpi", created_at=NOW)
    rewriter = Rewriter({
        "decision": "RETRIEVE",
        "standalone_query": "Quando sono obbligatori i DPI?",
        "clarification": None,
    })

    result = rewrite_query(
        conversation, "Quando sono obbligatori?", rewriter,
        token_budget=3, count_tokens=words,
    )

    assert result.original_query == "Quando sono obbligatori?"
    assert result.standalone_query == "Quando sono obbligatori i DPI?"
    assert result.recent_turn_ids == ("turn-3",)
    assert rewriter.request is not None
    assert [message.content for message in rewriter.request.recent_messages] == ["nuovo tema dpi"]


def test_ambiguity_requests_clarification_instead_of_inventing_a_query() -> None:
    rewriter = Rewriter({
        "decision": "CLARIFY",
        "standalone_query": None,
        "clarification": "Ti riferisci ai DPI o alla formazione?",
    })

    result = rewrite_query(
        Conversation(), "E per quelli?", rewriter,
        token_budget=20, count_tokens=words,
    )

    assert result.decision == "CLARIFY"
    assert result.standalone_query is None
    assert result.clarification == "Ti riferisci ai DPI o alla formazione?"

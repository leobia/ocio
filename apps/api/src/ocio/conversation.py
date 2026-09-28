"""Small, provider-independent conversational state for OCIO."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal, Protocol

FactStatus = Literal["confirmed", "inferred", "unknown"]
type FactValue = str | int | bool | date | tuple[str, ...] | None
MessageRole = Literal["user", "assistant"]
RewriteDecision = Literal["RETRIEVE", "CLARIFY"]


@dataclass(frozen=True, slots=True)
class Message:
    turn_id: str
    role: MessageRole
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.turn_id.strip() or not self.content.strip():
            raise ValueError("turn_id and content must be non-empty")


@dataclass(frozen=True, slots=True)
class CaseFact:
    value: FactValue
    source_turn_id: str
    status: FactStatus
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.source_turn_id.strip():
            raise ValueError("source_turn_id must be non-empty")
        if self.status == "unknown" and self.value is not None:
            raise ValueError("unknown facts cannot have a value")
        if self.status != "unknown" and self.value is None:
            raise ValueError("known facts require a value")


@dataclass(frozen=True, slots=True)
class CaseState:
    """Current typed facts; replacements never mutate the conversation log."""

    facts: tuple[tuple[str, CaseFact], ...] = ()

    def __post_init__(self) -> None:
        names = [name for name, _ in self.facts]
        if any(not name.strip() for name in names) or len(names) != len(set(names)):
            raise ValueError("fact names must be non-empty and unique")

    def get(self, name: str) -> CaseFact | None:
        return dict(self.facts).get(name)

    def set(self, name: str, fact: CaseFact) -> CaseState:
        if not name.strip():
            raise ValueError("fact name must be non-empty")
        facts = dict(self.facts)
        facts[name] = fact
        return CaseState(tuple(sorted(facts.items())))


@dataclass(frozen=True, slots=True)
class Conversation:
    log: tuple[Message, ...] = ()
    case_state: CaseState = CaseState()

    def append(
        self,
        turn_id: str,
        role: MessageRole,
        content: str,
        *,
        created_at: datetime | None = None,
    ) -> Conversation:
        message = Message(
            turn_id, role, content, created_at or datetime.now(UTC)
        )
        return replace(self, log=(*self.log, message))

    def record_fact(
        self,
        name: str,
        value: FactValue,
        source_turn_id: str,
        status: FactStatus = "confirmed",
        *,
        updated_at: datetime | None = None,
    ) -> Conversation:
        fact = CaseFact(
            value, source_turn_id, status, updated_at or datetime.now(UTC)
        )
        return replace(self, case_state=self.case_state.set(name, fact))

    def recent(
        self, token_budget: int, count_tokens: Callable[[str], int]
    ) -> tuple[Message, ...]:
        if token_budget < 0:
            raise ValueError("token_budget cannot be negative")
        selected: list[Message] = []
        used = 0
        for message in reversed(self.log):
            cost = count_tokens(message.content)
            if cost < 0:
                raise ValueError("token count cannot be negative")
            if used + cost > token_budget:
                break
            selected.append(message)
            used += cost
        return tuple(reversed(selected))


@dataclass(frozen=True, slots=True)
class RewriteRequest:
    original_query: str
    recent_messages: tuple[Message, ...]
    case_state: CaseState


class QueryRewriter(Protocol):
    def rewrite(self, request: RewriteRequest) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class QueryRewrite:
    decision: RewriteDecision
    original_query: str
    standalone_query: str | None
    clarification: str | None
    recent_turn_ids: tuple[str, ...]
    case_state: CaseState


def rewrite_query(
    conversation: Conversation,
    original_query: str,
    rewriter: QueryRewriter,
    *,
    token_budget: int,
    count_tokens: Callable[[str], int],
) -> QueryRewrite:
    """Build and trace a standalone query, or expose unresolved ambiguity."""
    if not original_query.strip():
        raise ValueError("original_query must be non-empty")
    recent = conversation.recent(token_budget, count_tokens)
    raw = rewriter.rewrite(RewriteRequest(original_query, recent, conversation.case_state))
    decision = raw.get("decision")
    standalone = raw.get("standalone_query")
    clarification = raw.get("clarification")
    if decision == "RETRIEVE":
        if not isinstance(standalone, str) or not standalone.strip():
            raise ValueError("RETRIEVE requires a standalone_query")
        if clarification is not None:
            raise ValueError("RETRIEVE cannot include a clarification")
        return QueryRewrite(
            "RETRIEVE", original_query, standalone.strip(), None,
            tuple(message.turn_id for message in recent), conversation.case_state,
        )
    if decision == "CLARIFY":
        if not isinstance(clarification, str) or not clarification.strip():
            raise ValueError("CLARIFY requires a clarification")
        if standalone is not None:
            raise ValueError("CLARIFY cannot choose a standalone_query")
        return QueryRewrite(
            "CLARIFY", original_query, None, clarification.strip(),
            tuple(message.turn_id for message in recent), conversation.case_state,
        )
    raise ValueError("invalid rewrite decision")

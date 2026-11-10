"""The conversation, in the agent's own terms rather than a provider's.

The agent loop reads and writes only these types. Translating them to and from a
provider's wire format is the adapter's job (llm.py), so a provider's quirks -
Gemini sending tool results as "user" turns, its thought signatures - stay in
one file instead of leaking into the loop and its history trimming (ADR-0029).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass(frozen=True)
class ToolCall:
    """One function the model asked to run."""
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    # Set when the provider issues call ids, so a result can be matched to its
    # call when several run in one round.
    id: Optional[str] = None


@dataclass
class UserTurn:
    """Something the person actually typed or said."""
    text: str


@dataclass
class ModelTurn:
    """The model's reply: prose, tool requests, or both.

    `raw` is the provider's own representation of this turn. Adapters echo it
    back verbatim when present, because it can carry state the neutral fields
    do not - Gemini's thought signatures, which multi-step tool use depends on.
    """
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None


@dataclass
class ToolResult:
    call: ToolCall
    result: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        """The shape the interface and the evaluation harness read."""
        return {"tool": self.call.name, "args": self.call.args,
                "result": self.result}


@dataclass
class ToolResultsTurn:
    """Every result for one round of tool calls, in the order they were asked."""
    results: List[ToolResult]


Turn = Union[UserTurn, ModelTurn, ToolResultsTurn]

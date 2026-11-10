"""The tools the model may call: each one's schema next to the function it runs.

The schema used to live in prompts.py and the dispatch table in agent.py, so
adding a tool meant editing two files and forgetting one was silent until the
model called it. One registry now holds both, and the schemas the model sees
are derived from it (ADR-0029).

Tools run here, never in the model: every number an answer cites comes back
from one of these calls (ADR-0007).
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import tools as T
from .messages import ToolCall, ToolResult
from .store import Store

log = logging.getLogger(__name__)

Handler = Callable[[Store, Dict[str, Any]], Dict[str, Any]]

# One round rarely asks for more than a handful - a comparison scores each
# airport it names. The cap bounds what one round can open at once.
MAX_PARALLEL_TOOLS = 8


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Handler

    def schema(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters}


def _one(arg: str, description: str) -> Dict[str, Any]:
    """Parameters for a tool taking a single string."""
    return {"type": "object",
            "properties": {arg: {"type": "string", "description": description}},
            "required": [arg]}


def _codes(description: str) -> Dict[str, Any]:
    """Parameters for a tool taking a list of airport codes."""
    return {"type": "object",
            "properties": {"codes": {"type": "array", "items": {"type": "string"},
                                     "description": description}},
            "required": ["codes"]}


TOOLS: Sequence[Tool] = (
    Tool(
        name="resolve_airports",
        description=(
            "Turn a place description into airport codes. Handles airport codes, "
            "airport and city names, multi-airport metros (returns a primary "
            "match plus alternates), named regions such as 'New England', and "
            "US states. Use this FIRST whenever the user names a place rather "
            "than a code. Also identifies out-of-scope foreign airports."
        ),
        parameters=_one("query", "Place as the user described it, e.g. "
                                 "'New England', 'the LA airports', 'Santa Ana'"),
        handler=lambda store, a: T.resolve_airports(store, a["query"]),
    ),
    Tool(
        name="score_airport",
        description=(
            "Full investment score for one airport: final score, the three "
            "components with raw values and tier percentiles, growth multiplier, "
            "constraint type (runway-limited vs terminal-limited), confidence, "
            "caveats, and absolute figures. Use this to explain WHY an airport "
            "is or is not constrained."
        ),
        parameters=_one("code", "Airport code, e.g. SFO"),
        handler=lambda store, a: T.score_airport(store, a["code"]),
    ),
    Tool(
        name="rank_airports",
        description=(
            "Rank several airports, grouped by size tier. Returns excluded "
            "airports with reasons. Use for 'which airports in X are the best "
            "candidates' questions, after resolve_airports."
        ),
        parameters=_codes("Airport codes to rank"),
        handler=lambda store, a: T.rank_airports(store, a["codes"]),
    ),
    Tool(
        name="compare_airports",
        description=(
            "Side-by-side comparison of two or more airports. Returns raw "
            "measured metrics plus tier percentiles, and flags when the airports "
            "are in different tiers and therefore not directly comparable by "
            "score."
        ),
        parameters=_codes("Airport codes to compare"),
        handler=lambda store, a: T.compare_airports(store, a["codes"]),
    ),
    Tool(
        name="route_profile",
        description=(
            "Route network for one airport: long-haul share (3000+ statute "
            "miles), international share, destination count and biggest routes. "
            "Passenger and cargo are reported SEPARATELY, which matters at "
            "freight hubs. Use for questions about long-haul, international mix "
            "or destinations."
        ),
        parameters=_one("code", "Airport code"),
        handler=lambda store, a: T.route_profile(store, a["code"]),
    ),
    Tool(
        name="current_conditions",
        description=(
            "Live FAA disruptions at an airport right now: ground delay "
            "programs, ground stops, closures. This is separate from the "
            "historical score and never affects it. Use only when the user asks "
            "about current or right-now conditions."
        ),
        parameters=_one("code", "Airport code"),
        handler=lambda store, a: T.current_conditions(store, a["code"]),
    ),
)


class Toolbox:
    """Runs the model's tool calls against one snapshot.

    Failures come back as results, not exceptions: the model can then tell the
    person the data is unavailable instead of the whole request dying.
    """

    def __init__(self, store: Store, tools: Optional[Sequence[Tool]] = None):
        self.store = store
        self.tools: Dict[str, Tool] = {t.name: t for t in (tools or TOOLS)}
        if len(self.tools) != len(tools or TOOLS):
            raise ValueError("Two tools share a name.")

    def schemas(self) -> List[Dict[str, Any]]:
        return [t.schema() for t in self.tools.values()]

    def run(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            result = {"error": "unknown_tool",
                      "message": "No tool named %s." % call.name}
        else:
            try:
                result = tool.handler(self.store, call.args or {})
            except KeyError as exc:
                result = {"error": "bad_arguments",
                          "message": "%s missing required argument %s."
                                     % (call.name, exc)}
            except Exception as exc:
                log.exception("tool %s failed", call.name)
                result = {"error": "tool_failed",
                          "message": "%s failed: %s" % (call.name, exc)}
        log.info("tool %s %s -> %s", call.name, call.args,
                 result.get("error", "ok") if isinstance(result, dict) else "ok")
        return ToolResult(call=call, result=result)

    def run_all(self, calls: Sequence[ToolCall]) -> List[ToolResult]:
        """Run one round's calls concurrently; results keep the calls' order.

        The tools are independent reads, and one of them waits on the FAA's
        live feed, so a round that compares four airports and checks current
        conditions should take as long as its slowest call, not their sum.
        """
        if len(calls) <= 1:
            return [self.run(c) for c in calls]
        workers = min(len(calls), MAX_PARALLEL_TOOLS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self.run, calls))

"""The agent loop, the tool registry and the Gemini wire format (ADR-0029).

The loop is driven by a scripted model, so these run with no API key and no
network: what is under test is what the agent does with the model's turns, not
what the model says.
"""
import threading
import time

import pytest

from airport_intel.agent import MAX_TOOL_ROUNDS, TOOL_LIMIT_ANSWER, Agent
from airport_intel.llm import LLMError, from_gemini_content, to_gemini_contents
from airport_intel.messages import (ModelTurn, ToolCall, ToolResult,
                                    ToolResultsTurn, UserTurn)
from airport_intel.store import Store
from airport_intel.toolbox import TOOLS, Tool, Toolbox


@pytest.fixture(scope="module")
def store():
    return Store()


class ScriptedModel:
    """Plays back fixed turns and records what it was shown each time."""

    active_model = "scripted"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []

    def generate(self, turns, system, tools=None):
        self.seen.append({"turns": list(turns), "tools": tools})
        if not self.turns:
            raise AssertionError("the agent asked for more turns than scripted")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def _call(name, **args):
    return ModelTurn(tool_calls=[ToolCall(name, args)])


# --- the loop ----------------------------------------------------------------

def test_tool_results_reach_the_model_before_it_answers(store):
    model = ScriptedModel(_call("score_airport", code="BOS"),
                          ModelTurn("Boston is constrained."))
    out = Agent(store=store, llm=model).ask("How is Boston?")

    assert out["answer"] == "Boston is constrained."
    assert [c["tool"] for c in out["tool_calls"]] == ["score_airport"]
    assert out["tool_calls"][0]["result"]["code"] == "BOS"

    second_look = model.seen[1]["turns"]
    assert isinstance(second_look[-1], ToolResultsTurn)
    assert second_look[-1].results[0].result["code"] == "BOS"


def test_the_model_is_offered_every_registered_tool(store):
    model = ScriptedModel(ModelTurn("Hello."))
    Agent(store=store, llm=model).ask("hi")
    offered = {t["name"] for t in model.seen[0]["tools"]}
    assert offered == {t.name for t in TOOLS}


def test_the_round_limit_is_an_answer_not_a_hang(store):
    model = ScriptedModel(*[_call("score_airport", code="BOS")] * MAX_TOOL_ROUNDS)
    out = Agent(store=store, llm=model).ask("loop forever")
    assert out["answer"] == TOOL_LIMIT_ANSWER
    assert len(out["tool_calls"]) == MAX_TOOL_ROUNDS


def test_follow_ups_see_the_earlier_exchange(store):
    model = ScriptedModel(ModelTurn("Boston."), ModelTurn("Providence."))
    agent = Agent(store=store, llm=model)
    agent.ask("first")
    agent.ask("what about Providence?")
    texts = [t.text for t in model.seen[1]["turns"] if isinstance(t, UserTurn)]
    assert texts == ["first", "what about Providence?"]


def test_a_failed_question_leaves_no_trace_in_the_history(store):
    """A question the model never answered must not be re-sent next time."""
    model = ScriptedModel(ModelTurn("Boston."),
                          _call("score_airport", code="SFO"),
                          LLMError("quota"))
    agent = Agent(store=store, llm=model)
    agent.ask("first")
    before = list(agent.history)
    with pytest.raises(LLMError):
        agent.ask("second")
    assert agent.history == before


# --- the toolbox ---------------------------------------------------------------

def test_an_unknown_tool_is_reported_to_the_model(store):
    result = Toolbox(store).run(ToolCall("make_it_up", {}))
    assert result.result["error"] == "unknown_tool"


def test_a_missing_argument_is_reported_to_the_model(store):
    result = Toolbox(store).run(ToolCall("score_airport", {}))
    assert result.result["error"] == "bad_arguments"


def test_a_failing_tool_does_not_kill_the_request(store):
    def boom(store, args):
        raise RuntimeError("feed down")
    box = Toolbox(store, [Tool("boom", "", {}, boom)])
    assert box.run(ToolCall("boom", {})).result["error"] == "tool_failed"


def test_every_schema_names_a_tool_that_exists(store):
    """The failure the registry exists to prevent: a schema with no handler."""
    box = Toolbox(store)
    for schema in box.schemas():
        assert schema["name"] in box.tools
        assert schema["parameters"]["type"] == "object"
        for arg in schema["parameters"].get("required", []):
            assert arg in schema["parameters"]["properties"]


def test_duplicate_tool_names_are_refused(store):
    tool = Tool("same", "", {}, lambda s, a: {})
    with pytest.raises(ValueError):
        Toolbox(store, [tool, tool])


def test_one_round_runs_in_parallel_and_keeps_order(store):
    """A round takes as long as its slowest call, and results stay matched."""
    active, peak, lock = [0], [0], threading.Lock()

    def slow(store, args):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return {"n": args["n"]}

    box = Toolbox(store, [Tool("slow", "", {}, slow)])
    results = box.run_all([ToolCall("slow", {"n": i}) for i in range(4)])
    assert [r.result["n"] for r in results] == [0, 1, 2, 3]
    assert peak[0] > 1


# --- Gemini wire format ----------------------------------------------------------

def test_the_models_own_parts_are_echoed_verbatim():
    """Thought signatures ride on the parts; rebuilding them would drop them."""
    raw = [{"functionCall": {"name": "score_airport", "args": {"code": "BOS"}},
            "thoughtSignature": "opaque"}]
    turn = from_gemini_content({"role": "model", "parts": raw})
    assert turn.tool_calls == [ToolCall("score_airport", {"code": "BOS"})]
    assert to_gemini_contents([turn])[0]["parts"] is raw


def test_tool_results_travel_as_function_responses():
    call = ToolCall("score_airport", {"code": "BOS"})
    wire = to_gemini_contents([UserTurn("q"), ModelTurn(tool_calls=[call]),
                               ToolResultsTurn([ToolResult(call, {"x": 1})])])
    assert [w["role"] for w in wire] == ["user", "model", "user"]
    assert wire[1]["parts"] == [{"functionCall": {"name": "score_airport",
                                                  "args": {"code": "BOS"}}}]
    assert wire[2]["parts"] == [{"functionResponse": {
        "name": "score_airport", "response": {"result": {"x": 1}}}}]


def test_text_and_calls_are_separated():
    turn = from_gemini_content({"parts": [
        {"text": "Let me check. "}, {"functionCall": {"name": "t", "id": "c1"}}]})
    assert turn.text == "Let me check. "
    assert turn.tool_calls == [ToolCall("t", {}, id="c1")]

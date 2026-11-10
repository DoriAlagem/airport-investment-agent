"""Tests for the six tools, against the real snapshot.

These run over the committed database rather than fixtures: the tools exist to
answer real analysts' questions from real data, and a fixture would test the
plumbing while leaving the actual answers unverified.

Skipped rather than failed when the snapshot is absent, so a fresh clone that
has not run the build is not reported as broken.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from airport_intel import tools as T  # noqa: E402
from airport_intel.config import DB_PATH, LONG_HAUL_MILES  # noqa: E402
from airport_intel.store import Store  # noqa: E402

pytestmark = pytest.mark.skipif(
    not Path(DB_PATH).exists(),
    reason="no snapshot; run python -m airport_intel.etl.build",
)


@pytest.fixture(scope="module")
def store():
    return Store()


# --- resolve_airports ------------------------------------------------------


def test_new_england_resolves_to_new_england(store):
    """The regression that matters most: this once returned LAX."""
    out = T.resolve_airports(store, "Which airports in New England are candidates?")
    assert out["match_type"] == "region"
    codes = {a["code"] for a in out["airports"]}
    assert {"BOS", "BDL", "PWM"} <= codes
    assert "LAX" not in codes


def test_region_reports_what_it_excluded(store):
    """Silently dropping small airports would narrow a question invisibly
    (ADR-0012 correction 3)."""
    out = T.resolve_airports(store, "New England")
    assert "excluded" in out
    for item in out["excluded"]:
        assert item["reason"]


def test_ambiguous_metro_states_its_assumption(store):
    out = T.resolve_airports(store, "LA")
    assert out["airports"][0]["code"] == "LAX"
    assert "assumption" in out and "LAX" in out["assumption"]
    assert {a["code"] for a in out["alternates"]} & {"BUR", "ONT", "LGB", "SNA"}


def test_foreign_airport_is_out_of_scope_with_a_reason(store):
    out = T.resolve_airports(store, "Heathrow")
    assert out["error"] == "out_of_scope"
    assert "US" in out["message"]


# --- score_airport ---------------------------------------------------------


def test_score_carries_components_confidence_and_windows(store):
    out = T.score_airport(store, "SFO")
    assert out["final_score"] is not None
    assert {c["name"] for c in out["components"]} == {
        "peak_saturation", "fullness", "capacity_delay"}
    assert out["confidence"] in ("high", "medium", "low")
    # Percentiles are meaningless without their peer group (ADR-0009).
    assert "hubs" in out["peer_group"]
    # A score must never be readable as "current" without its window (ADR-0005).
    assert out["data_windows"]["congestion_and_delay"]["end"]


def test_score_reports_absolute_figures_beside_percentiles(store):
    """The score is relative to peers; an absolute anchor stops it being read
    as an absolute measure of fullness (ADR-0006)."""
    out = T.score_airport(store, "BOS")
    assert 0 < out["absolute_figures"]["load_factor"] < 1
    assert out["absolute_figures"]["peak_hour_departures"] > 0


def test_unknown_airport_is_not_found_rather_than_guessed(store):
    assert T.score_airport(store, "ZZZ")["error"] == "not_found"


# --- rank_airports ---------------------------------------------------------


def test_ranking_is_grouped_by_tier(store):
    """A single merged list would compare percentiles computed against
    different peer groups (ADR-0012 correction 1)."""
    out = T.rank_airports(store, ["BOS", "BDL", "PWM", "MHT", "BTV"])
    tiers = [g["tier"] for g in out["ranking_by_tier"]]
    assert len(tiers) > 1
    assert len(set(tiers)) == len(tiers)
    for group in out["ranking_by_tier"]:
        scores = [a["final_score"] for a in group["airports"]]
        assert scores == sorted(scores, reverse=True)
    assert "own size" in out["note"]


# --- compare_airports ------------------------------------------------------


def test_cross_tier_comparison_is_flagged_and_leads_with_raw_metrics(store):
    """LAX and SNA sit in different tiers, so their scores are not comparable;
    the raw figures are (ADR-0009)."""
    out = T.compare_airports(store, ["LAX", "SNA"])
    assert out["cross_tier"] is True
    assert "not directly comparable" in out["comparison_basis"]
    for airport in out["airports"]:
        assert airport["raw_metrics"]["load_factor"] is not None


def test_same_tier_comparison_is_not_flagged(store):
    out = T.compare_airports(store, ["JFK", "LAX"])
    assert out["cross_tier"] is False


# --- route_profile ---------------------------------------------------------


def test_anchorage_separates_passenger_from_cargo(store):
    """A blended long-haul figure at ANC is dominated by freight and would
    badly mislead a passenger-capacity reader (ADR-0012 correction 6)."""
    out = T.route_profile(store, "ANC")
    assert {"passenger", "cargo"} <= set(out["by_service"])
    cargo = out["by_service"]["cargo"]["long_haul_share"]
    passenger = out["by_service"]["passenger"]["long_haul_share"]
    assert cargo > passenger
    assert "note" in out and "argo" in out["note"]


def test_long_haul_definition_is_stated(store):
    """No industry standard exists, so the threshold must be disclosed rather
    than implied (ADR-0012 correction 5)."""
    out = T.route_profile(store, "JFK")
    assert out["long_haul_definition_miles"] == LONG_HAUL_MILES
    assert str(LONG_HAUL_MILES) in out["assumption"]


# --- universe --------------------------------------------------------------


def test_cargo_hub_is_outside_the_passenger_universe(store):
    """Fort Worth Alliance flies constantly and carries almost nobody; the
    thesis is passenger capacity (ADR-0022)."""
    score = store.score("AFW")
    if score is not None:
        assert score.final is None
        assert "primary-airport threshold" in score.excluded


def test_portsmouth_is_inside_it(store):
    """82,727 passengers a year, in New England, and dropped by the old
    departures-based floor (ADR-0022)."""
    score = store.score("PSM")
    assert score is not None and score.final is not None


# --- FAA live feed ---------------------------------------------------------

FAA_SAMPLE = """<?xml version="1.0"?>
<AIRPORT_STATUS_INFORMATION>
  <Update_Time>Wed Aug 12 13:11:53 2026 GMT</Update_Time>
  <Delay_type>
    <Name>Airport Closures</Name>
    <Airport_Closure_List>
      <Airport><ARPT>SNA</ARPT><Reason>SNA AD AP CLSD DLY</Reason>
        <Start>Aug 11 at 06:30 UTC.</Start><Reopen>Aug 15 at 13:15 UTC.</Reopen></Airport>
      <Airport><ARPT>PVD</ARPT><Reason>PVD AD AP CLSD EXC HEL</Reason>
        <Start>Aug 11 at 04:30 UTC.</Start><Reopen>Aug 22 at 09:45 UTC.</Reopen></Airport>
    </Airport_Closure_List>
  </Delay_type>
</AIRPORT_STATUS_INFORMATION>"""


def test_faa_parser_finds_events_for_the_right_airport():
    """The container tag is "Airport_Closure_List", not "...Closure".

    Matching tag suffixes meant nothing ever matched, so the tool reported
    "no active FAA programs" even for airports that were closed (ADR-0004).
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(FAA_SAMPLE)

    sna = T.parse_faa_events(root, "SNA")
    assert len(sna) == 1
    assert sna[0]["type"] == "Airport Closures"
    assert "CLSD" in sna[0]["detail"]
    assert "Reopen" in sna[0]["detail"]

    assert T.parse_faa_events(root, "sna"), "code match must be case-insensitive"
    assert T.parse_faa_events(root, "SFO") == []


def test_duplicate_codes_appear_once(store):
    """The model assembles code lists from several resolve calls, which overlap.
    Without de-duplication an airport shows up repeatedly in one ranking."""
    ranked = T.rank_airports(store, ["BOS", "BOS", "bos", " bos "])
    assert sum(len(g["airports"]) for g in ranked["ranking_by_tier"]) == 1
    assert len(T.compare_airports(store, ["LAX", "lax"])["airports"]) == 1


# --- conversation history (ADR-0007) ---------------------------------------

from airport_intel.llm import to_gemini_contents
from airport_intel.messages import (ModelTurn, ToolCall, ToolResult,
                                    ToolResultsTurn, UserTurn)


def _agent_with_history(entries):
    from airport_intel.agent import Agent
    a = Agent.__new__(Agent)          # no store or API key needed
    a.history = list(entries)
    a.language = None
    return a


def _exchange(question):
    """One question that used a tool: ask, call, result, answer."""
    call = ToolCall("score_airport", {"code": "BOS"})
    return [
        UserTurn(question),
        ModelTurn(tool_calls=[call]),
        ToolResultsTurn([ToolResult(call, {})]),
        ModelTurn("Boston Logan scores 79.6."),
    ]


def test_trimming_never_opens_on_a_tool_result():
    """A function response separated from its call breaks the whole request.

    Gemini answers it with INVALID_ARGUMENT and the conversation dies - which
    it did, on about the fourth question, because a function response is also
    role "user" and the old trim stopped at the first one it met.
    """
    from airport_intel.agent import MAX_HISTORY_ENTRIES
    a = _agent_with_history([e for i in range(12) for e in _exchange("q%d" % i)])
    a._trim_history()
    assert len(a.history) <= MAX_HISTORY_ENTRIES
    assert isinstance(a.history[0], UserTurn), a.history[0]
    assert "functionResponse" not in str(to_gemini_contents(a.history)[0])


def test_every_tool_result_still_follows_its_call():
    """The invariant Gemini actually enforces, checked on the wire."""
    a = _agent_with_history([e for i in range(12) for e in _exchange("q%d" % i)])
    a._trim_history()
    wire = to_gemini_contents(a.history)
    for i, entry in enumerate(wire):
        if any("functionResponse" in p for p in entry["parts"]):
            assert i > 0
            assert any("functionCall" in p for p in wire[i - 1]["parts"])


def test_a_short_conversation_is_left_alone():
    a = _agent_with_history(_exchange("only question"))
    before = list(a.history)
    a._trim_history()
    assert a.history == before


def test_one_enormous_exchange_keeps_its_question():
    """A question needing many tools must not trim away the question itself."""
    long_exchange = [UserTurn("a hard question")]
    for _ in range(30):
        call = ToolCall("t", {})
        long_exchange += [ModelTurn(tool_calls=[call]),
                          ToolResultsTurn([ToolResult(call, {})])]
    a = _agent_with_history(long_exchange)
    a._trim_history()
    assert isinstance(a.history[0], UserTurn)
    assert a.history[0].text == "a hard question"

"""Tests for the deterministic scoring core.

These exist because the scoring logic is the part of the system that must be
provably correct: the model narrates, but every number comes from here. The
cases below are the design decisions from the ADRs, written as assertions.

    python -m pytest tests/ -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airport_intel.scoring import (  # noqa: E402
    GROWTH_MAX,
    caveats_for as scoring_caveats,
    WEIGHTS,
    GROWTH_MIN,
    constraint_type,
    growth_factor,
    percentile_rank,
    score_all,
)


# --- percentile_rank -------------------------------------------------------


def test_percentile_rank_orders_and_bounds():
    pool = [1.0, 2.0, 3.0, 4.0]
    assert percentile_rank(pool, 0.0) == 0.0
    assert percentile_rank(pool, 5.0) == 100.0
    assert percentile_rank(pool, 2.0) < percentile_rank(pool, 3.0)


def test_percentile_rank_handles_empty_pool():
    assert percentile_rank([], 1.0) == 0.0


# --- growth_factor ---------------------------------------------------------


def test_growth_is_bounded_both_ways():
    """Growth adjusts the score; it must never dominate it (ADR-0002)."""
    assert growth_factor(5.0, 0.1) == GROWTH_MAX
    assert growth_factor(-5.0, -0.1) == GROWTH_MIN


def test_decline_with_emptying_planes_is_penalised():
    """Falling passengers AND falling load factor is genuine decline."""
    assert growth_factor(-0.08, -0.05) < 1.0


def test_decline_with_holding_load_factor_is_not_penalised():
    """The asymmetric rule (ADR-0006).

    A saturated airport can lose passengers *because* it is full. Penalising
    that would reintroduce the inversion the whole thesis rejects, this time
    through the multiplier.
    """
    assert growth_factor(-0.08, 0.02) == 1.0
    assert growth_factor(-0.08, 0.0) == 1.0


def test_missing_growth_data_is_neutral():
    assert growth_factor(None, None) == 1.0


def test_growth_cannot_lift_an_empty_airport_over_a_full_one():
    """The bound expressed as the thing it exists to prevent (ADR-0002)."""
    empty_but_booming = 40 * growth_factor(0.20, 0.05)
    full_but_shrinking = 90 * growth_factor(-0.20, -0.10)
    assert empty_but_booming < full_but_shrinking


# --- constraint_type -------------------------------------------------------


def test_constraint_type_thresholds():
    """Departures per EFFECTIVE runway; doubled internally to movements.

    Recalibrated when the denominator changed from raw runways to usable
    streams (ADR-0023): San Diego sustains ~50 movements/hour on one runway and
    is genuinely runway-limited, while Boston and JFK have airfield capacity to
    spare.
    """
    assert constraint_type(25.0) == "runway-limited"     # 50 movements/hr
    assert constraint_type(7.0) == "terminal-limited"    # 14 movements/hr
    assert constraint_type(13.0) == "mixed"              # 26 movements/hr
    assert constraint_type(None) == "unknown"


# --- score_all -------------------------------------------------------------


def _airport(code, tier="large", **kw):
    row = {
        "code": code,
        "tier": tier,
        "annual_departures": 100_000,
        "enplanements": 5_000_000,
        "peak_saturation": 0.5,
        "fullness": 0.80,
        "capacity_delay": 2.0,
        "pax_cagr": 0.0,
        "load_factor_change": 0.0,
        "peak_flights_per_runway": 10.0,
        "runway_count": 3,
        "carrier_coverage": 0.95,
        "peak_months_present": 12,
        "cargo_share": 0.02,
        "cargo_bias_flag": False,
        "growth_years": 2,
    }
    row.update(kw)
    return row


def test_ranking_is_within_tier_not_across():
    """A medium hub at its ceiling must be able to out-score a quiet mega-hub.

    Percentiles are computed inside each tier, so the two never compete
    directly (ADR-0009).
    """
    rows = [
        _airport("BIG1", "large", peak_saturation=0.9, fullness=0.90, capacity_delay=5.0),
        _airport("BIG2", "large", peak_saturation=0.2, fullness=0.70, capacity_delay=1.0),
        _airport("MED1", "medium", peak_saturation=0.9, fullness=0.90, capacity_delay=5.0),
        _airport("MED2", "medium", peak_saturation=0.2, fullness=0.70, capacity_delay=1.0),
    ]
    scores = score_all(rows)
    assert scores["MED1"].final == scores["BIG1"].final
    assert scores["MED1"].final > scores["BIG2"].final


def test_low_volume_airports_are_excluded_with_a_reason():
    """Exclusion must be visible, never silent (ADR-0012 correction 3)."""
    scores = score_all([_airport("TINY", enplanements=900)])
    assert scores["TINY"].final is None
    assert "primary-airport threshold" in scores["TINY"].excluded


def test_floor_counts_passengers_not_flights():
    """A cargo field or bush strip can out-fly a regional airport while
    carrying almost nobody. The thesis is passenger capacity (ADR-0022)."""
    rows = [
        _airport("CARGO", annual_departures=8_899, enplanements=894),
        _airport("REGIONAL", annual_departures=1_160, enplanements=156_151),
    ]
    scores = score_all(rows)
    assert scores["CARGO"].final is None
    assert scores["REGIONAL"].final is not None


def test_missing_component_renormalises_rather_than_scoring_zero():
    """A gap in federal reporting must not read as 'uncongested'."""
    rows = [
        _airport("A", peak_saturation=0.9, fullness=0.9, capacity_delay=5.0),
        _airport("B", peak_saturation=0.1, fullness=0.1, capacity_delay=0.1),
        _airport("GAP", peak_saturation=0.9, fullness=0.9, capacity_delay=None),
    ]
    scores = score_all(rows)
    assert scores["GAP"].final is not None
    assert scores["GAP"].final > scores["B"].final


def test_cargo_bias_travels_with_the_score():
    """At cargo hubs the bias attaches to the score, not the prose (ADR-0014)."""
    scores = score_all([_airport("ANC", cargo_share=0.57, cargo_bias_flag=True)])
    assert any("cargo" in c.lower() for c in scores["ANC"].caveats)
    assert any("understated" in c.lower() for c in scores["ANC"].caveats)


def test_partial_carrier_coverage_lowers_confidence_and_is_disclosed():
    scores = score_all([_airport("PVD", carrier_coverage=0.62, peak_months_present=8)])
    assert scores["PVD"].confidence == "medium"
    assert any("covers 62%" in c for c in scores["PVD"].caveats)


def test_scoring_is_deterministic():
    rows = [_airport("A"), _airport("B", peak_saturation=0.9)]
    assert [s.final for s in score_all(rows).values()] == \
           [s.final for s in score_all(rows).values()]


def test_uncongested_airports_are_not_labelled_terminal_limited():
    """"Terminal-limited" reads as "build a terminal here".

    An airport with quiet runways and no congestion was previously given that
    label purely because its runways were empty, which inverts the advice.
    """
    from airport_intel.scoring import constraint_type
    assert constraint_type(5.0, congestion=12.5) == "not constrained"
    assert constraint_type(5.0, congestion=80.0) == "terminal-limited"
    assert constraint_type(20.0, congestion=80.0) == "runway-limited"
    # No congestion supplied: fall back to the geometry alone.
    assert constraint_type(5.0) == "terminal-limited"


def test_missing_peak_data_is_named_not_just_scored_around():
    """A score built on two of three components must say which one is absent
    (ADR-0010) - lowering confidence alone does not tell the reader what is
    missing."""
    scores = score_all([_airport("PSM", peak_saturation=None)])
    caveats = " ".join(scores["PSM"].caveats).lower()
    assert "peak-hour" in caveats


def test_history_is_bounded_and_never_starts_on_a_model_turn():
    """An unbounded history grows the request every turn; a window that opens
    on a model turn is rejected outright by the API."""
    from airport_intel.agent import Agent, MAX_HISTORY_ENTRIES
    from airport_intel.messages import ModelTurn, UserTurn

    agent = Agent.__new__(Agent)          # no store or API key needed
    agent.history = []
    for i in range(MAX_HISTORY_ENTRIES * 2):
        agent.history.append(UserTurn("q%d" % i) if i % 2 == 0 else ModelTurn("a"))
    agent._trim_history()

    assert len(agent.history) <= MAX_HISTORY_ENTRIES
    assert isinstance(agent.history[0], UserTurn)


def test_non_hub_airports_are_named_sensibly():
    """The label was built by appending "hubs" to the tier, which reads fine for
    large/medium/small and produces "nonhub hubs" for everything else. It now
    comes from a single definition shared with the tools."""
    scores = score_all([_airport("ACK", tier="nonhub")])
    assert scores["ACK"].components[0].peer_group == "non-hub airports"
    scores = score_all([_airport("BOS", tier="large")])
    assert scores["BOS"].components[0].peer_group == "large hubs"


# --- the weights and the growth scale, pinned by behaviour -----------------
#
# Both were found unpinned by mutation testing: the component weights could be
# changed from 0.40/0.30/0.30 to anything, and the growth scale from 20% to
# 200%, and the whole suite stayed green. These assert the arithmetic those
# constants produce - a test that read the constant back would pass against any
# value at all.


def test_peak_saturation_outweighs_the_other_two_components():
    """0.40 / 0.30 / 0.30, pinned by the margin and not just the ordering.

    Two airports in one tier, mirror images: A leads on peak saturation, B on
    fullness by exactly as much, and their capacity delay is identical. With
    two members the percentiles are 75 and 25, so the gap between them is
    50 x (peak weight - fullness weight) = 50 x 0.10 = 5.0.

    Asserting only "A beats B" would survive any weighting where peak is the
    largest - including 0.60 - which is how mutation testing found this
    untested.
    """
    rows = [
        _airport("AAA", peak_saturation=0.9, fullness=0.50, capacity_delay=2.0),
        _airport("BBB", peak_saturation=0.1, fullness=0.90, capacity_delay=2.0),
    ]
    scores = score_all(rows)
    gap = scores["AAA"].congestion - scores["BBB"].congestion
    percentile_spread = 75.0 - 25.0
    expected = percentile_spread * (WEIGHTS["peak_saturation"] - WEIGHTS["fullness"])
    assert abs(gap - expected) < 1e-6, (gap, expected)
    assert abs(gap - 5.0) < 1e-6, gap        # the value the shipped weights give


def test_fullness_and_capacity_delay_carry_equal_weight():
    """0.30 each: leaders on those two components tie exactly."""
    rows = [
        _airport("FUL", peak_saturation=0.5, fullness=0.90, capacity_delay=2.0),
        _airport("DEL", peak_saturation=0.5, fullness=0.50, capacity_delay=9.0),
    ]
    scores = score_all(rows)
    assert abs(scores["FUL"].congestion - scores["DEL"].congestion) < 1e-6


def test_growth_reaches_full_effect_at_twenty_percent_cagr():
    """GROWTH_FULL_SCALE: +20% CAGR earns the whole +25%, +10% earns half."""
    assert growth_factor(0.20, 0.01) == GROWTH_MAX
    assert growth_factor(-0.20, -0.01) == GROWTH_MIN
    midpoint = 1.0 + (GROWTH_MAX - 1.0) / 2
    assert abs(growth_factor(0.10, 0.01) - midpoint) < 1e-9
    # beyond full scale it clamps rather than continuing
    assert growth_factor(0.80, 0.01) == GROWTH_MAX


def test_a_single_component_score_says_so():
    """52 airports are scored on one component, five of them in the overall top
    twenty. Renormalising one component is defensible arithmetic and a poor
    summary, so the caveat has to name it - found by auditing the top of the
    ranking, not by a failing test.
    """
    thin = _airport("THN", peak_saturation=None, capacity_delay=None, fullness=0.80)
    notes = " ".join(scoring_caveats(thin))
    assert "single component" in notes
    assert "fullness" in notes

    whole = _airport("WHL", peak_saturation=0.6, capacity_delay=2.0, fullness=0.80)
    assert "single component" not in " ".join(scoring_caveats(whole))

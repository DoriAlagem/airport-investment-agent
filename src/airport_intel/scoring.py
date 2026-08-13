"""The deterministic scoring core.

Pure functions over plain dictionaries: no database, no network, no model. Given
the same metrics this module returns the same numbers every time, which is what
makes the assignment's "deterministic scoring, not only LLM output" requirement
true by construction rather than by assertion (ADR-0007).

The thesis (ADR-0001): rank airports by demand that exists today but cannot be
served because the facility is too small, adjusted for whether that demand is
rising or dying.

    congestion = 0.40 * peak_saturation_pct
               + 0.30 * fullness_pct
               + 0.30 * capacity_delay_pct          (percentiles within tier)

    final      = congestion * clamp(growth_factor, 0.75, 1.25)

Every parameter below is a documented judgment call, not a derived constant.
They are gathered here rather than scattered so that a challenge to any of them
has a single answer: change it and re-run.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import MIN_ANNUAL_ENPLANEMENTS, tier_label

# --- tunable parameters ----------------------------------------------------

WEIGHTS = {
    # Peak saturation carries the extra weight because it is closest to the
    # thesis: fullness shows demand exists and delay shows strain, but only
    # saturation shows there is no room left (ADR-0006).
    "peak_saturation": 0.40,
    "fullness": 0.30,
    "capacity_delay": 0.30,
}

GROWTH_MIN, GROWTH_MAX = 0.75, 1.25
# The swing implied by the bounds. Derived rather than repeated: it appeared
# again as a literal 0.25 inside growth_factor, so widening the bounds would
# have moved one and not the other.
GROWTH_SWING = GROWTH_MAX - 1.0

# The CAGR at which the growth multiplier saturates, calibrated against the
# observed distribution: median US airport growth is ~0%, p75 is 10%, p90 is
# 20%. Setting full scale at 10% put a quarter of all airports at the cap,
# which makes the multiplier a blunt instrument. At 20% the cap is reached by
# roughly the top decile, which is what "exceptional growth" should mean.
GROWTH_FULL_SCALE = 0.20

# --- runway vs terminal ----------------------------------------------------
#
# A runway is consumed by arrivals as well as departures, but on-time data
# gives us departures only. Total movements are therefore approximated as
# departures x 2, since scheduled service is near-symmetric over a day: an
# aircraft that lands must also leave.
#
# This understates reality at cargo hubs, where freight movements are invisible
# to on-time data entirely (ADR-0014) - one more reason the bias flag matters.
MOVEMENTS_PER_DEPARTURE = 2.0

# Movements per EFFECTIVE runway per peak hour (ADR-0023). Now that the
# denominator counts usable streams rather than strips of pavement, these
# numbers carry their physical meaning: an independent runway sustains roughly
# 30-45 movements/hour.
#
# Recalibrated when the denominator changed. Under the old raw-runway count the
# same thresholds meant something different, and every large hub read as
# runway-limited. The check: San Diego runs ~50 movements/hour on a single
# runway and is genuinely runway-limited; Boston and JFK have airfield capacity
# to spare and are terminal-limited.
RUNWAY_LIMITED_ABOVE = 35.0
TERMINAL_LIMITED_BELOW = 20.0

# Below this congestion score an airport is not meaningfully constrained, and
# naming a constraint type would mislead: "terminal-limited" reads as "build a
# terminal here", when the honest answer is that nothing needs building.
#
# Set at the bottom third rather than the median. At the median, SFO - which
# scores near the middle of the large hubs and is famous for delays - was
# declared "not constrained" on a 0.2-point margin. Claiming an airport is fine
# is as strong a claim as calling it constrained, and needs the same distance
# from the boundary.
CONSTRAINED_ABOVE = 35.0

# Confidence thresholds. Coverage is the share of an airport's passenger
# departures visible in on-time reporting (ADR-0010).
#
# Coverage tops out near 0.8 even at ORD and ATL, because the T-100
# denominator includes foreign carriers and charter operators that fall outside
# the on-time reporting rule entirely. Thresholds are set against that observed
# ceiling rather than against a theoretical 1.0, so that a well-covered major
# hub is not labelled uncertain for a structural reason.
HIGH_COVERAGE, HIGH_MONTHS = 0.75, 10
MEDIUM_COVERAGE, MEDIUM_MONTHS = 0.50, 6


@dataclass
class Component:
    """One scoring input: what it measured, and where that ranks."""
    name: str
    raw: Optional[float]
    percentile: Optional[float]
    weight: float
    peer_group: str


@dataclass
class Score:
    code: str
    tier: str
    congestion: Optional[float]
    growth_factor: float
    final: Optional[float]
    components: List[Component] = field(default_factory=list)
    constraint_type: str = "unknown"
    confidence: str = "low"
    caveats: List[str] = field(default_factory=list)
    excluded: Optional[str] = None


# --- primitives ------------------------------------------------------------


def percentile_rank(values: Sequence[float], value: float) -> float:
    """Percent of peers this value meets or beats, 0-100.

    Percentiles are used rather than absolute thresholds so that no scoring
    bar has to be invented, units cancel, and one extreme airport cannot
    compress the scale for everyone else (ADR-0006).
    """
    if not values:
        return 0.0
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return 100.0 * (below + 0.5 * equal) / len(values)


def growth_factor(pax_cagr: Optional[float],
                  load_factor_change: Optional[float]) -> float:
    """Map the growth trend onto a bounded multiplier.

    Growth is not a reason to invest; it is a reason to trust or distrust the
    congestion signal. A multiplier scales a signal but cannot manufacture one,
    so an empty airport growing fast stays empty (ADR-0002).

    The asymmetric rule closes a loophole: a saturated airport can show flat or
    falling passengers *because* it is full. Penalising that would reintroduce
    the very inversion the thesis rejects. So a decline is only counted as
    decline when the planes are emptying too (ADR-0006).
    """
    if pax_cagr is None:
        return 1.0

    if pax_cagr < 0 and (load_factor_change is None or load_factor_change >= 0):
        # Fewer passengers but no drop in load factor: capacity was withdrawn
        # while demand held. Constrained, not dying. No penalty.
        return 1.0

    scaled = max(-1.0, min(1.0, pax_cagr / GROWTH_FULL_SCALE))
    return max(GROWTH_MIN, min(GROWTH_MAX, 1.0 + scaled * GROWTH_SWING))


def peak_movements_per_runway(peak_departures_per_runway: Optional[float]
                              ) -> Optional[float]:
    """Departures per runway converted to an estimate of total movements."""
    if peak_departures_per_runway is None:
        return None
    return peak_departures_per_runway * MOVEMENTS_PER_DEPARTURE


def constraint_type(peak_departures_per_runway: Optional[float],
                    congestion: Optional[float] = None) -> str:
    """Would a terminal actually help?

    An airport jammed because it cannot get aircraft airborne is not helped by
    more gates. Distinguishing the two is worth more than the ranking position,
    because it is the finding that stops money going to the wrong project.

    The question only has meaning for an airport that is actually constrained.
    An uncongested airport was previously labelled "terminal-limited" purely
    because its runways were quiet - which reads as a recommendation to build
    something. It now answers "not constrained" instead.

    Takes departures per runway and converts internally, so callers pass the
    metric as measured rather than a pre-adjusted figure.
    """
    if congestion is not None and congestion < CONSTRAINED_ABOVE:
        return "not constrained"
    movements = peak_movements_per_runway(peak_departures_per_runway)
    if movements is None:
        return "unknown"
    if movements >= RUNWAY_LIMITED_ABOVE:
        return "runway-limited"
    if movements < TERMINAL_LIMITED_BELOW:
        return "terminal-limited"
    return "mixed"


def confidence(carrier_coverage: Optional[float],
               months_present: Optional[int]) -> str:
    """How much of this airport did the hourly data actually see?

    Computed from the data rather than authored by the model: uncertainty that
    is not measured is not uncertainty, it is tone (ADR-0010).
    """
    if carrier_coverage is None or months_present is None:
        return "low"
    if carrier_coverage >= HIGH_COVERAGE and months_present >= HIGH_MONTHS:
        return "high"
    if carrier_coverage >= MEDIUM_COVERAGE and months_present >= MEDIUM_MONTHS:
        return "medium"
    return "low"


def caveats_for(row: Dict) -> List[str]:
    """Data-quality notes that must travel with the score, not the prose."""
    notes = []

    if row.get("cargo_bias_flag"):
        share = row.get("cargo_share") or 0.0
        notes.append(
            "Peak-hour and delay figures exclude cargo, which is %.0f%% of "
            "departures here. True utilisation is higher and this score is "
            "understated." % (100 * share)
        )

    coverage = row.get("carrier_coverage")
    if coverage is not None and coverage < HIGH_COVERAGE:
        notes.append(
            "On-time reporting covers %.0f%% of passenger departures here, so "
            "peak-hour figures may understate activity." % (100 * coverage)
        )

    if row.get("runway_count") in (None, 0):
        notes.append("Runway count unknown; constraint type cannot be determined.")

    if row.get("peak_saturation") is None:
        notes.append(
            "No peak-hour data for this airport: too few scheduled departures "
            "for any hour to average one flight a day. The score is computed "
            "from the remaining components and the busiest-hour picture is "
            "unknown."
        )

    span = row.get("growth_years")
    if span is not None and span < 2:
        notes.append("Growth trend spans under two years and is provisional.")

    # A score built from one component is not really a congestion score. 52
    # airports are in this position - all small - and five of them sit in the
    # overall top twenty, above airports measured on all three. Renormalising a
    # single component is defensible arithmetic (ADR-0010) and a poor summary,
    # so the answer has to say which one it rests on.
    present = [name for name in ("peak_saturation", "fullness", "capacity_delay")
               if row.get(name) is not None]
    if len(present) == 1:
        notes.append(
            "This score rests on a single component (%s); the other two are "
            "unavailable for this airport. Treat it as an indication, not a "
            "ranking position." % present[0].replace("_", " ")
        )

    return notes


# --- scoring ---------------------------------------------------------------


def _excluded_reason(row: Dict) -> Optional[str]:
    """Airports that leave the universe, with the reason kept (ADR-0012).

    Judged on passengers rather than flights: a busy cargo field or a bush strip
    can out-fly a regional jet airport while carrying almost no one, and the
    thesis is about passenger capacity (ADR-0022).
    """
    passengers = row.get("enplanements") or 0
    if passengers < MIN_ANNUAL_ENPLANEMENTS:
        return ("below the primary-airport threshold (%s passengers/year, "
                "minimum %s)" % (format(int(passengers), ","),
                                 format(MIN_ANNUAL_ENPLANEMENTS, ",")))
    if row.get("peak_saturation") is None and row.get("fullness") is None:
        return "no usable traffic data in the current window"
    return None


def score_all(rows: Sequence[Dict]) -> Dict[str, Score]:
    """Score every airport, ranking each within its own size tier.

    Comparing a medium hub against a mega-hub is not informative: the mega-hub
    wins every absolute metric. The investment question is whether an airport is
    constrained *relative to airports like it* (ADR-0009).
    """
    eligible, excluded = [], []
    for row in rows:
        reason = _excluded_reason(row)
        (excluded if reason else eligible).append((row, reason))

    # Peer pools, one per tier, per component.
    pools: Dict[str, Dict[str, List[float]]] = {}
    for row, _ in eligible:
        tier = row.get("tier") or "unknown"
        pool = pools.setdefault(tier, {k: [] for k in WEIGHTS})
        for metric in WEIGHTS:
            value = row.get(metric)
            if value is not None:
                pool[metric].append(value)

    results: Dict[str, Score] = {}

    for row, reason in excluded:
        results[row["code"]] = Score(
            code=row["code"], tier=row.get("tier") or "unknown",
            congestion=None, growth_factor=1.0, final=None,
            excluded=reason,
        )

    for row, _ in eligible:
        tier = row.get("tier") or "unknown"
        pool = pools[tier]

        components, weighted, used_weight = [], 0.0, 0.0
        for metric, weight in WEIGHTS.items():
            raw = row.get(metric)
            pct = percentile_rank(pool[metric], raw) if raw is not None else None
            components.append(Component(
                name=metric, raw=raw, percentile=pct,
                weight=weight, peer_group=tier_label(tier),
            ))
            if pct is not None:
                weighted += weight * pct
                used_weight += weight

        # Re-normalise across available components rather than treating a
        # missing metric as zero, which would silently penalise airports for
        # gaps in federal reporting.
        congestion = (weighted / used_weight) if used_weight else None

        factor = growth_factor(row.get("pax_cagr"), row.get("load_factor_change"))
        final = round(congestion * factor, 1) if congestion is not None else None

        results[row["code"]] = Score(
            code=row["code"],
            tier=tier,
            congestion=round(congestion, 1) if congestion is not None else None,
            growth_factor=round(factor, 3),
            final=final,
            components=components,
            constraint_type=constraint_type(row.get("peak_flights_per_runway"),
                                            congestion),
            confidence=confidence(row.get("carrier_coverage"),
                                  row.get("peak_months_present")),
            caveats=caveats_for(row),
        )

    return results

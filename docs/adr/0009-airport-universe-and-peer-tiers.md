# ADR-0009: Airport universe — volume floor, size tiers, and rank-within-tier / compare-on-raw

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0019](0019-us-territories-in-the-universe.md) — US territories are in the universe; [ADR-0022](0022-validating-two-unchecked-parameters.md) — the floor counts passengers, not departures
- **Follows:** [ADR-0006](0006-score-computation.md), [ADR-0007](0007-agent-architecture.md)

---

## Context

ADR-0006 normalises every scoring component to a percentile. Percentiles are computed
relative to a population, so **the choice of population silently determines every score.**
It must therefore be an explicit decision.

Three options were considered:

- **A. All US commercial airports (~350–400 primary).** Broad, but places an airport with
  three daily departures in the same pool as ATL. Peak saturation on trivially few flights
  produces meaningless extremes.
- **B. Top ~100 by passengers.** A clean peer group, but excludes most New England airports
  — which the assignment explicitly asks about.
- **C. All primary airports, with percentiles computed within size tiers.**

---

## Decision

**Option C, in three parts.**

### 1. Volume floor

Airports below a minimum departures threshold are excluded from the universe entirely. With
very few flights, a single flight carries disproportionate weight and can manufacture a
false 99th-percentile score.

### 2. Size tiers

Remaining airports are grouped into large / medium / small hub tiers — a classification the
FAA already defines (49 U.S.C. 47102) and which the BTS and OurAirports data supports.
Percentiles are computed **within tier**, not nationally.

### 3. Rank within tier, compare across tiers on raw metrics

- **Ranking** ("which New England airports are candidates for terminal expansion?") is
  performed within a tier and the tier is always named.
- **Cross-tier comparison** ("compare LA and Santa Ana") reports **raw metrics side by
  side** — actual load factor, actual peak-hour flights, actual NAS-delay minutes — with
  tier percentiles as secondary context.

`compare_airports` therefore returns both raw values and tier percentiles, and the agent
states which basis it is using.

---

## Rationale

Comparing BDL against ATL is not informative: ATL wins every absolute metric and BDL never
ranks. But the investment question is not *"is BDL busier than ATL?"* — it is **"is BDL
constrained relative to airports like it?"** A medium hub operating at its ceiling is a
genuine opportunity that can never out-score a mega-hub on absolute volume.

Tiering is also required by the brief: the New England airports are predominantly small and
medium hubs and would be invisible in a national percentile pool.

### The assignment's own questions cross tiers

*"Compare LA and Santa Ana airport congestion levels"* pairs a large hub with a smaller one.
A 90th-percentile score in each tier means two different things, so percentiles alone cannot
answer it. Hence the raw-metric comparison mode:

> LAX: 87.1% load factor, saturated 15 hrs/day — 82nd pct among large hubs.
> SNA: 89.4% load factor, saturated 11 hrs/day — 94th pct among medium hubs.
> SNA is more constrained *for its size*; LAX is larger in absolute terms.

---

## Consequences

- **Scores are not comparable across tiers.** "BDL 91, LAX 88" does not mean BDL is more
  constrained in absolute terms — it means BDL is more constrained *for its class*. The
  agent must name the peer pool in every ranking answer; failing to do so would be actively
  misleading.
- The volume floor excludes some airports from the product entirely. This is disclosed
  rather than silent — an out-of-universe airport returns an explicit "below the coverage
  threshold" response, not a score.
- Tier boundaries are inherited from an existing federal classification rather than invented,
  which removes one more arbitrary parameter from the design.

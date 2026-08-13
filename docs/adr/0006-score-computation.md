# ADR-0006: Score computation — percentile-normalised components, weighted, growth-adjusted

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0015](0015-calibration-against-real-data.md) — peak saturation and the constraint split were recalibrated; [ADR-0012](0012-question-trace-corrections.md) — cargo is treated per-component, not globally; [ADR-0022](0022-validating-two-unchecked-parameters.md) — weight sensitivity measured; [ADR-0023](0023-effective-runway-count.md) — capacity is usable runway streams, not strips
- **Follows:** [ADR-0002](0002-growth-as-bounded-multiplier.md), [ADR-0003](0003-congestion-components.md), [ADR-0004](0004-data-sources.md)

---

## Context

ADR-0003 fixed *which* signals measure congestion. This ADR fixes *how they are combined
into a single number*.

The components have incompatible units — load factor is a percentage, peak crowding is
flights per hour, NAS delay is minutes. They cannot be summed directly.

---

## Decision

### Step 1 — three raw metrics per airport

| Metric | Definition |
|---|---|
| **Fullness** | passengers ÷ available seats, averaged over the window, weighted by departures |
| **Peak saturation** | ~~share of daily operating hours running at ≥80% of that airport's own busiest hour~~ **superseded by [ADR-0015](0015-calibration-against-real-data.md): median operating hour ÷ peak hour.** The threshold count proved outlier-driven — one spike hour set the bar for the whole day |
| **Capacity delay** | NAS-delay minutes ÷ departures |

**Peak saturation measures flatness, not size.** An airport with one morning rush and a
quiet afternoon has hours available to grow into. An airport pinned near its own maximum
from early morning to late evening has nowhere to put another flight. Two airports can share
an identical busiest hour while one has abundant slack and the other none — a difference
invisible in daily totals or peak-hour counts alone.

### Step 2 — percentile-normalise each component (0–100)

Each metric is converted to its percentile rank across all in-scope US airports.

### Step 3 — weighted average

```
congestion = 0.40 × peak_saturation_pct
           + 0.30 × fullness_pct
           + 0.30 × capacity_delay_pct
```

### Step 4 — growth multiplier

```
final = congestion × clamp(growth_factor, 0.75, 1.25)
```

`growth_factor` derives from ~3-year passenger CAGR (T-100), with the asymmetry rule below.

### Alongside the score — constraint type (not part of the score)

```
peak_hour_flights ÷ runway_count  →  high : runway-limited (a terminal will not help)
                                     low  : terminal-limited (expansion is actionable)
```

> **Superseded by [ADR-0015](0015-calibration-against-real-data.md).** This counts
> departures, but a runway serves arrivals too. Movements are now estimated as
> departures × 2 and the thresholds recalibrated; as written here, LaGuardia —
> the most slot-constrained airport in the country — was classified "mixed".

---

## Rationale

### Why percentiles rather than absolute thresholds

- **No invented thresholds.** Absolute bars ("85% load factor is high") are judgment calls
  requiring individual defence. Percentiles are derived from the data.
- **Units disappear.** All three become 0–100 and are directly comparable.
- **Outlier-resistant.** A single extreme airport cannot compress the scale for the rest.
- **Legible.** "BOS is in the top 8% for peak-hour saturation" is immediately meaningful.

### Why peak saturation carries the extra weight

It is the closest of the three to the thesis itself. Fullness shows demand exists; delay
shows the system is straining; **peak saturation shows there is no room left** — which is
the actual investment question.

### Why growth uses passengers, not flights

A constrained airport that cannot add departures will add *seats*, by flying larger
aircraft. Measuring flights would read that as flat; measuring passengers captures it.

### The asymmetric growth rule — closing an inversion loophole

A saturated airport can show flat or declining passenger growth **because it is full**. A
naive multiplier would apply ×0.75 and penalise the airport for precisely the condition
being sought — reintroducing the inversion ADR-0001 rejected, this time through the
multiplier. Growth is therefore judged on two signals together:

| Passengers | Load factor | Reading | Factor |
|---|---|---|---|
| ↓ | ↓ | Genuine decline — demand is leaving | 0.75–1.0 |
| ↓ | ↑ or flat/high | **Constrained, not dying** — capacity withdrawn, demand held | 1.0 (neutral) |
| ↑ | any | Growing | 1.0–1.25 |

A passenger decline triggers a markdown only if the planes are also emptying.

### Window selection

The growth window is kept **post-pandemic** (approximately 2023 onward). Reaching into
2020–21 would generate large artefactual "growth" figures reflecting recovery rather than
demand.

---

## Consequences and stated limitations

- **The score is relative, not absolute.** If every US airport were uncongested, one would
  still rank in the 99th percentile. The score means "most constrained relative to US
  peers." Answers therefore carry at least one absolute figure (e.g. actual load factor)
  alongside the percentile.
- **The weights (0.40 / 0.30 / 0.30) are a judgment call**, not a derived result. They are
  exposed as parameters, sanity-checked against real output, and accompanied by a note on
  what reorders when they shift — a more honest answer than defending them as principled.
- **The 80% peak-saturation threshold is a choice**, and airlines schedule around peaks for
  commercial as well as physical reasons. Peak saturation is evidence, not proof. Recorded
  in the assumptions section.
- **The constraint-type split is a heuristic**, not an engineering capacity study. Its value
  is in flagging airports where a terminal investment would not help — a finding more
  useful than a ranking position.

---

## Illustrative output

> **BOS — final 87.** Peak saturation 94th pct (near-max ~14 hrs/day), fullness 88th
> (86.4%), capacity delay 71st. Growth ×1.09. Terminal-limited: 2 runways, moderate
> hourly load.

Every figure is traceable to a source metric; no arithmetic is performed by the LLM.

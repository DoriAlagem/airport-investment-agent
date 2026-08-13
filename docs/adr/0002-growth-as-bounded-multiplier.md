# ADR-0002: Growth enters the score as a bounded multiplier, not as an additive factor

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Follows:** [ADR-0001](0001-scoring-thesis.md)

---

## Context

ADR-0001 established congestion / suppressed demand as the spine of the score, with growth
retained only as a modifier. This ADR decides *how* growth enters the arithmetic.

**The problem growth solves.** Congestion is a snapshot. The investment is not — a terminal
takes years to build and pays back over decades. Two airports equally congested today are
not equally attractive if one sits in a growing catchment and the other in a shrinking one.
A pure congestion score cannot tell them apart.

**Three candidate mechanisms were considered:**

1. **Multiplier** — `final = congestion × growth_factor`, where `growth_factor` is centred
   on 1.0.
2. **Additive weighted factor** — `final = 0.7 × congestion + 0.3 × growth`.
3. **Narrative flag only** — rank on congestion alone; growth changes only what the agent
   *says*, never the number.

---

## Decision

**Growth is a bounded multiplier, clamped to the range 0.75 – 1.25, computed from a
multi-year trend rather than a single year-over-year change.**

```
final_score = congestion_score × clamp(growth_factor, 0.75, 1.25)
```

---

## Rationale

### Why a multiplier and not an additive term

Growth is not itself a reason to invest — it is a reason to **trust or distrust the
congestion signal**. A multiplier expresses exactly that: it scales a signal, it cannot
manufacture one. An empty airport growing 20% a year is still empty, and anything
multiplied by a small congestion score stays small.

An additive term does not have this property. Under `0.7 × congestion + 0.3 × growth`, an
uncongested but fast-growing airport can accumulate points on growth alone and climb the
ranking — reintroducing the exact inversion ADR-0001 rejected.

Option 3 (narrative flag) was rejected as too weak: it leaves the ranking blind to something
we have agreed is materially real.

### Why the bound is tight

The bound is where the sentence *"congestion decides, growth adjusts"* becomes arithmetic.

| Airport | Congestion | Growth | Final |
|---------|-----------|--------|-------|
| X | 80 | booming → ×1.25 | **100** |
| Y | 90 | declining → ×0.75 | **67.5** |
| Z | 40 | booming → ×1.25 | **50** |

- X overtakes Y: growth *does* reorder airports that are close on congestion. It is doing
  real work.
- Z still loses to Y (50 vs 67.5): a half-empty airport cannot climb over a jammed one on
  growth alone.

Without the bound — say a multiplier free to range 0.2–3.0 — Z would score 120 against Y's
72, and growth would silently become the dominant factor.

### Why a multi-year trend

A single year-over-year figure is noise: one airline dropping a route, one severe weather
season, one post-pandemic rebound artefact. A multi-year trend is signal. The cost is a
requirement for several years of history rather than a current snapshot, which constrains
data sourcing.

---

## Consequences

**The final score is an index on 0-125, not a percentage.** Congestion is a
percentile (0-100) and the multiplier reaches 1.25, so an airport that is both
highly congested for its tier and growing can exceed 100. Five do: EAT 124.3,
HGR 111.7, IAG 104.1, STC 101.6, YKM 100.9 - all non-hubs, where a small traffic
base makes strong three-year growth common.

This is deliberate rather than a defect: clamping to 100 would compress exactly
the airports the thesis is designed to surface. The system prompt states the
range explicitly so the model never reports a score as a percentage.

### Other consequences


- The ±25% bound is a **judgment call, not a derived constant.** This will be stated
  plainly in the design document rather than dressed up as principled. It is exposed as a
  tunable parameter, and a sensitivity check (what reorders at 15% vs 40%?) is the honest
  answer to any challenge on the number.
- Requires multi-year historical traffic data, not just current-state data.
- Every score remains explainable in one sentence: *"BOS scored 78 on congestion, adjusted
  up 15% because traffic has grown steadily for three years — final 90."*

---

## Open questions spawned by this decision

- The precise definition of `growth_factor` — which metric (passengers, operations, or
  both), over how many years, and how it maps onto the 0.75–1.25 range. Deferred until
  data sources are fixed (ADR-0003), since availability constrains the choice.

# ADR-0003: Congestion is measured from three observed signals — fullness, peak-hour crowding, and capacity-caused delay

- **Status:** Accepted (data availability verified — see ADR-0004)
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0004](0004-data-sources.md) — data availability verified; conditional status lifted
- **Follows:** [ADR-0001](0001-scoring-thesis.md), [ADR-0002](0002-growth-as-bounded-multiplier.md)

---

## Context

ADR-0001 fixed the thesis: rank airports by suppressed demand. That is a concept, not a
computation. This ADR decides which observable quantities stand in for it.

Four candidate signals were considered:

1. **Delay** — average departure/arrival delay, share of flights delayed beyond a threshold.
2. **Fullness** — passengers ÷ available seats (load factor).
3. **Peak-hour crowding** — operations concentrated in the busiest hours, rather than
   daily totals.
4. **Modelled spill** — estimate latent regional demand from population/income/economic
   activity and subtract served seats; the residual is suppressed demand.

---

## Decision

**The congestion score is composed of signals 1, 2 and 3. Signal 4 (modelled spill) is
rejected.**

Delay is used in a restricted form: **only the volume- and capacity-attributable portion**
of published delay, with weather and late-arriving-aircraft delay explicitly excluded
(see Rationale).

---

## Rationale

### The three signals answer three different questions, and together they *are* the explanation

| Signal | The question it answers |
|--------|------------------------|
| Fullness | Is the demand actually there? (planes leave full) |
| Peak-hour crowding | Is the *facility* the limit? (jammed exactly when people want to fly) |
| Capacity-caused delay | Is the limit already being hit? (the system is visibly failing) |

An airport scoring high on all three has a coherent, non-circular story: people want to
fly, at times the airport cannot absorb, and it is breaking under the load.

This decomposition is the direct answer to the assignment's *"What is the unmet flight
demand in SFO airport and why?"* — **no separate explanation engine is required, because
the components of the score are the reasons.** This is the main structural payoff of the
design.

### Why modelled spill is rejected

It is the most impressive-sounding option and the least defensible. It requires inventing a
demand model — catchment boundaries, propensity to fly, income elasticity — none of which
is measured. Under questioning, *"where did this demand curve come from?"* has no good
answer.

Signals 1–3 are **measured**; signal 4 is **assumed**. Given a one-day budget, the measured
set is both buildable and defensible. Dropped on scope grounds as well as principle.

### The delay objection, and the mitigation

The strongest objection to any delay-based metric:

> Delay is not the same as a capacity shortage. Airports are delayed by fog, thunderstorms,
> an airline's own poor scheduling, or by aircraft arriving late from an upstream airport
> that broke. None of those imply "build a new terminal."

This is correct and is the principal weakness of a naive delay score. Mitigation: US delay
statistics are published **decomposed by cause** (carrier, weather, national airspace
system, security, late-arriving aircraft). Only the volume/capacity-related portion is
used; weather and late-aircraft delay are discarded. This converts a misleading metric into
a defensible one.

---

## Consequences

- Requires per-cause delay data, not just aggregate delay. If only aggregate delay proves
  reachable, the delay component must be down-weighted and the limitation stated openly
  rather than papered over.
- Requires seat *and* passenger counts (for fullness) and flight-level scheduled times (for
  peak-hour crowding) — three distinct datasets rather than one.
- The score remains fully decomposable, which is what makes conversational "why" answers
  deterministic rather than LLM-improvised.

---

## Status caveat: data availability — RESOLVED

> **Resolved by [ADR-0004](0004-data-sources.md).** All three components were
> verified against live sources on 2026-08-12 and are buildable. The delay
> mitigation is stronger than assumed here: `NASDelay` is a published field
> isolating exactly the volume/capacity bucket. The original caveat is kept
> below as the record of what was uncertain at the time.

This ADR was accepted **on the assumption** that US federal aviation data provides, for US
airports: delay statistics broken down by cause, passenger and seat counts, and
flight-level scheduled departure times.

That assumption has not been checked against live sources. Exact endpoints, field names,
granularity, freshness and rate limits are unverified. If any component proves unreachable
or unusably stale, this ADR is revised rather than quietly worked around — the affected
component is dropped and the gap disclosed in the design document.

Verification is the next action (ADR-0004).

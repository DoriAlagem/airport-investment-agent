# ADR-0023: Effective runway count — capacity is usable streams, not strips of pavement

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amends:** [ADR-0006](0006-score-computation.md), [ADR-0015](0015-calibration-against-real-data.md)

---

## Context

The runway-vs-terminal split divides peak-hour movements by the number of
runways. ADR-0015 fixed the numerator — arrivals were missing — but left the
denominator as a raw count, and flagged the consequence as a known, unfixed
limitation:

> **Runway count overstates capacity where runways are not independent.** SFO's
> closely-spaced parallels cannot be used independently in poor visibility…
> SFO's score is likely understated as a result.

SFO has four runways arranged as two pairs **747 ft and 748 ft apart** (measured
from the data, matching the published ~750 ft). In poor visibility each pair
collapses to a single usable strip, so SFO behaves like a two-runway airport.
Dividing its traffic by four made it look like it had airfield capacity to
spare.

This is not an SFO problem. Los Angeles, Seattle, Philadelphia, Charlotte and
Detroit all have parallels closer than the separation standard.

---

## Decision

Capacity is measured in **independent streams**, computed from runway geometry.
No airport is special-cased.

1. **Exclude non-runways** — helipads and water landing areas, identified by
   their non-numeric designators — plus closed runways, those without
   coordinates, and strips under 4,000 ft, which cannot take the aircraft this
   thesis concerns.
2. **Group by alignment**, within 20°. The tolerance is generous because
   designators round to the nearest ten degrees, so one physical alignment can
   appear as both "08" and "09" — as it does at Atlanta.
3. **Project each threshold onto the axis perpendicular to the alignment**,
   giving a one-dimensional position, and sort. Sorting by position is what
   makes the result **order-independent**; a chain of pairwise comparisons in
   arbitrary input order would not be.
4. **Split into clusters** wherever the gap reaches the separation minimum.
5. **Sum across alignments.**

### The separation threshold

**2,500 ft**, the FAA minimum below which parallel runways cannot be operated as
separate streams under any procedure.

The full simultaneous-independent-approach standard is ~4,300 ft, and applying
that **collapsed Atlanta to two effective runways when it demonstrably runs
three arrival streams**. 2,500 ft is the conservative bar and reproduces
Atlanta correctly.

A **5% tolerance** is applied because separation is measured between runway
*threshold* coordinates rather than centrelines, so a pair built exactly to the
standard can measure tens of feet under it. Seattle is the case: its outer
parallels measure 2,462 ft against a 2,500 ft design, and it runs two
independent streams.

### Verified against real airfields

| Airport | Runways | Effective | Check |
|---|---|---|---|
| SFO | 4 | **2** | Two pairs 747 ft apart |
| LAX | 4 | **2** | Two complexes, each internally close |
| ATL | 5 | **3** | Triple simultaneous approaches |
| ORD | 8 | **6** | |
| DFW | 7 | **5** | |
| SEA | 3 | **2** | Outer parallels at the standard |
| SAN | 1 | **1** | Single runway |

---

## The thresholds had to move with the denominator

Shrinking the denominator raised movements-per-runway across the board, and the
ADR-0015 thresholds — calibrated against raw counts — immediately classified
**almost every large hub as runway-limited**, including airports scoring in the
thirties.

Recalibrated to **≥35 movements/hour runway-limited, <20 terminal-limited**.
Now that the denominator counts usable streams, these carry their physical
meaning: an independent runway sustains roughly 30–45 movements/hour.

The external check:

| | mv/hr per effective runway | Type | Sanity |
|---|---|---|---|
| SAN | 49.5 | runway-limited | Busiest single-runway airport in the US |
| LAX | 47.4 | runway-limited | |
| ATL | 46.1 | runway-limited | |
| **SFO** | **36.0** | **runway-limited** | The airport this ADR exists for |
| BOS | 18.6 | terminal-limited | Airfield capacity to spare |
| JFK | 13.5 | terminal-limited | |

**A parameter change that invalidates a downstream threshold is not finished
until the threshold is re-derived.** The denominator changed and the old numbers
silently meant something new.

---

## Known limitations

- **Crossing runways are counted separately** though they cannot be used
  simultaneously. Boston's six runways yield four effective streams; the true
  simultaneous figure is lower. This overstates capacity at airfields with
  intersecting layouts.
- **Geometry is not declared capacity.** Real capacity also depends on approach
  procedures, terrain, noise rules and equipment. FAA airport capacity
  benchmarks would replace this heuristic outright; this is a large improvement
  over counting pavement, not a substitute for an engineering study.
- **Weather is not modelled.** The count reflects the constrained (poor
  visibility) configuration. SFO in clear weather runs closer to four.

---

## Consequences

- `runway_count` is retained alongside `effective_runway_count`, so answers can
  show both and the reduction is visible rather than hidden.
- Ten focused tests cover the geometry, including order-independence over
  permutations, that effective never exceeds the real count, and that an offset
  *along* a runway is not separation *across* it.
- SFO now reports **runway-limited**, which is the correct and materially
  different investment conclusion: at SFO a new terminal would not relieve the
  binding constraint.

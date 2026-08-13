# ADR-0012: Corrections arising from tracing the assignment's four sample questions

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0014](0014-cargo-blind-spot-in-peak-hour-data.md) — correction 6b is unimplementable; cargo is absent from hourly data
- **Amends:** [ADR-0006](0006-score-computation.md), [ADR-0007](0007-agent-architecture.md), [ADR-0011](0011-storage-and-build-order.md)

---

## Context

Before committing to the design, each of the assignment's four sample questions was traced
end to end on paper — which tools fire, what data is required, and where the design fails.
The exercise found seven gaps. None were fatal; all were cheap to close, and several would
have been expensive to discover mid-build.

The traces are recorded here because *why* these rules exist is otherwise invisible.

---

## Q1 — "Which airports in New England are strong candidates for terminal expansion?"

### Correction 1 — regional rankings are grouped by tier, never merged

New England spans all three hub tiers: BOS is a large hub, BDL/PVD/MHT are medium, PWM/BTV
are small. ADR-0009 computes percentiles *within* tier, so a single 1-to-7 list would rank
numbers that do not mean the same thing.

Answers are therefore grouped, with the basis stated:

> Among large hubs: BOS (81). Among medium hubs: BDL 88, PVD 84, MHT 71.
> Scores compare each airport to peers of its own size — BDL's 88 does not mean it is
> busier than BOS.

Less satisfying than one ranked list, and the only honest presentation.

### Correction 2 — `constraint_type` is promoted above the UI in the build order

ADR-0011 placed the runway-vs-terminal split in the cut list. **That was wrong.** The
question does not ask which airports are congested; it asks which are congested *in a way a
terminal fixes*. Without `constraint_type` the system answers a nearby question instead of
the one asked.

Revised cut order: voice → realtime → tier granularity → narrow universe → shorten window.
`constraint_type` is no longer cuttable.

### Correction 3 — volume-floor exclusions are reported, not silent

New England's smaller airports sit closest to the ADR-0009 volume floor. Silently dropping
them narrows a required question invisibly. Excluded airports are returned with a reason:
*"BTV excluded: below coverage threshold (N departures/month)."*

---

## Q2 — "Compare LA and Santa Ana airport congestion levels"

### Correction 4 — `resolve_airports` returns a primary match plus alternates, generally

"LA" is ambiguous across LAX, BUR, LGB and ONT. Note the question pairs it with Santa Ana —
the other LA-basin airport — so the asker may mean the basin as a system.

The tool returns a primary match and its metro alternates, and the agent proceeds on a
**stated** assumption rather than stopping to ask:

> Reading "LA" as **LAX**. Burbank, Long Beach and Ontario also serve the LA basin — say the
> word and I'll include them.

This is deliberately **general, not special-cased for Los Angeles**: it covers New York,
Chicago, Washington, Houston and the Bay Area, all likely follow-ups. OurAirports already
provides the metro grouping.

This behaviour is also the assignment's "communicate assumptions" requirement appearing as
visible product behaviour rather than documentation.

*No correction needed for the cross-tier comparison itself — ADR-0009 already specifies raw
metrics side by side with tier percentiles as context.*

---

## Q3 — "What is the percentage of long haul flights out of Anchorage?"

### Correction 5 — long-haul is defined as ≥3,000 statute miles

No industry-standard definition exists, so the threshold must be chosen and disclosed.
Distance is computed great-circle from OurAirports coordinates — data already held.
Duration-based definitions would require flight-time data needed for nothing else. The
answer states the definition inline.

### Correction 6 — passenger and cargo are computed separately, always; surfaced when material

T-100 includes freight-only flights. **Anchorage is one of the world's largest cargo hubs** —
a transpacific refuelling stop — so a blind count would be dominated by freighters and
report something like "68% long-haul": true, and badly misleading for a passenger-capacity
thesis.

- **Always computed separately** — same query cost either way.
- **Both surfaced only when cargo is material** (>15% of departures); otherwise a single
  clause ("cargo is 4% here, excluded"). Reporting both everywhere would be noise at the
  95% of airports where cargo is trivial.

> Passenger flights: 12% long-haul. Cargo: 71%. ANC is a major transpacific freight hub, so
> any blended figure is dominated by cargo.

### Correction 6b — cargo's treatment in the score is per-component, not global

This amends ADR-0006. Freighters consume runway slots and ramp space, so they compete for
the same physical capacity — but they carry no passengers.

| Component | Cargo treatment |
|---|---|
| Peak saturation | **Included** — a freighter at 08:00 blocks a slot as effectively as any flight |
| Capacity delay | **Included** — same reasoning |
| Fullness (load factor) | **Excluded** — freighters have no seats; including them breaks passengers ÷ seats |
| Growth | **Excluded** — passengers only, per ADR-0006 |

Rule: **cargo counts where it consumes capacity, and is excluded where the metric is about
people.**

### Correction 7 — answers mixing sources are trimmed to the common data window

T-100 Domestic publishes roughly two months in arrears; T-100 International roughly three
months later still. Anchorage's long-haul flights are mostly international and its
short-haul mostly domestic, so an untrimmed ratio would divide one time period by another.

Any answer combining both sources is trimmed to the shorter window, and says so. **A correct
number on older data beats a wrong number on newer data.**

---

## Q4 — "What is the unmet flight demand in SFO airport, and why?"

### What already works

The **"why"** requires no new machinery — the score's components *are* the reasons, which is
the payoff of ADR-0003:

> SFO: fullness 91st pct (86.8% load factor), peak saturation 96th pct (near-max ~15
> hrs/day), capacity delay 89th pct. Demand is present, the day has no slack, and the system
> is visibly straining. Terminal-limited.

### Correction 8 — the quantity question is reframed, not silently substituted

The question asks what the unmet demand **is** — a quantity, in flights or passengers.
ADR-0003 rejected modelled spill, so no absolute figure can be produced. Strictly, the
design answers *"how constrained is SFO, and why"* — adjacent to, but not identical with,
*"how much demand is unmet."*

**The failure to avoid is answering a quantity question with a percentile and hoping the
substitution passes unnoticed.**

The agent therefore states the limit explicitly:

> We don't estimate absolute spilled passengers — that requires a demand model we would be
> inventing. What we can show is strong evidence of suppression: [components].

**Optional upgrade if time allows — a bounded counterfactual.** Pure arithmetic over
measured inputs: *"if SFO's saturated hours were relieved to the tier median, at current
load factors that is room for approximately X additional passengers annually."* This is a
capacity calculation, not a forecast — every input is measured and nothing is assumed about
behaviour. It must be framed as such or it becomes the demand model we rejected.

---

## Consequences

- Seven corrections, none requiring rework of the thesis, data sources, or architecture —
  evidence the earlier ADRs held up.
- The single substantive error found was ADR-0011's cut order, which would have removed a
  capability a required question depends on. Tracing questions against the design before
  building is retained as a practice.

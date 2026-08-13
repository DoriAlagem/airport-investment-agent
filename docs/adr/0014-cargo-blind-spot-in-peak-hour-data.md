# ADR-0014: Peak-hour metrics are cargo-blind — disclose per airport, do not silently absorb

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amends:** [ADR-0012](0012-question-trace-corrections.md) correction 6b

---

## Context

ADR-0012 correction 6b specified that cargo flights should be **included** in
peak saturation and capacity delay, on the reasoning that a freighter occupies a
runway slot as effectively as any passenger flight. Inspecting the real data
shows that rule cannot be implemented as written.

### What the data shows

T-100's `CLASS` field separates passenger from cargo cleanly (January 2023):

| CLASS | Departures | Seats | Meaning |
|-------|-----------|-------|---------|
| F | 722,803 | 101,178,922 | Scheduled passenger |
| G | 49,585 | **22,541** | Scheduled all-cargo |
| L | 14,834 | 898,075 | Charter passenger |
| P | 11,309 | **1,846** | Non-scheduled cargo |

Near-zero seats across ~61,000 departures confirms G and P are freighters. The
passenger/cargo split of correction 6 therefore works exactly as designed.

### The blind spot

The two datasets carry different things:

| Dataset | Contains cargo? | Has clock times? |
|---------|----------------|------------------|
| T-100 | **Yes** | **No** — monthly totals only |
| On-Time | **No** | **Yes** — per-flight scheduled times |

Peak saturation and capacity delay both require clock times, so both are
computed from on-time data. On-time reporting is mandatory only for carriers
above 0.5% of domestic **passenger** revenue (14 CFR Part 234); pure freight
carriers have no passenger revenue and fall outside the rule.

**Cargo flights are therefore absent from every hourly metric — by construction,
not by choice.** We know ANC flew N cargo departures last January; we cannot know
that any of them left at 08:00.

This is not fixable by us: the dataset is collected under federal regulation. We
are consumers of what BTS publishes.

---

## Decision

**1. Correction 6b is amended.** Cargo cannot be included in peak saturation or
capacity delay. Those metrics are passenger-flight-only, and this is stated as a
property of the data rather than left implicit.

**2. The bias is quantified per airport.** T-100 gives cargo's share of
departures for every airport. Where that share is material (>15%, matching the
threshold in ADR-0012 correction 6), it is attached to the score itself — not
merely to prose:

> ANC — peak saturation 71st pct. **Cargo excluded (38% of departures); true
> utilisation is higher and this score is understated.**

**3. The disclosure attaches to the score, not the narration.** Peak saturation
is a scoring component, so at cargo-heavy airports the *score* is computed on
incomplete traffic and is biased low. Flagging it only in the prose would leave
the ranking quietly wrong.

---

## Rationale

The bias is **known, quantified, one-directional, and confined to an
identifiable set of airports** — Anchorage, Memphis, Louisville, Ontario (CA)
and a handful of others. At the large majority of airports cargo is a few
percent and the effect is immaterial.

That is a materially better position than a vague caveat: the agent can name
which airports are affected, in which direction, and by roughly how much.

**Anchorage is the sharp case** — and it is the airport in the assignment's own
sample question. Its score will understate true runway utilisation, and the
answer must say so.

---

## Alternative considered and deferred: OpenSky ADS-B

OpenSky Network provides free ADS-B data — aircraft transponder broadcasts
collected by volunteer receivers — covering **all** traffic including freight,
with real timestamps. It would fix the metric rather than annotate it.

Estimated cost: roughly half a day.

| Work | Effort |
|------|--------|
| Auth and API integration | ~1 hr |
| Historical departures per airport (rate-limited, paged) | 2–4 hrs |
| ICAO/IATA airport code matching | ~1 hr |
| **Reconciling observed takeoffs against BTS scheduled departures** | 1–2 hrs, and the risky part |

Rejected for this build on four grounds:

1. Half a day out of one, to improve one component at roughly five airports.
2. The reconciliation problem is genuinely hard — ADS-B counts observed
   takeoffs, BTS counts scheduled operations. They will disagree by several
   percent on the same airport, and an unexplained discrepancy could make the
   data *worse*, not better.
3. ADS-B coverage is uneven — strong over populated areas, thinner in remote
   Alaska, which is precisely where the sharpest case sits.
4. ADR-0011's standing rule: nothing optional before the required deliverables
   are complete.

**Recorded as the top item in further work — ahead of voice.** If time remains,
this is built first.

---

## Consequences

- Every airport carries a `cargo_share` figure derived from T-100.
- Airports above the materiality threshold carry a bias flag on peak saturation
  that travels with the score through ranking, comparison and explanation.
- The limitation is specific enough to be actionable: *"peak saturation excludes
  cargo; OpenSky ADS-B would close it; the hard part is reconciling observed
  against scheduled departures."*

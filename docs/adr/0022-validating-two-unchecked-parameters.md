# ADR-0022: Validating two parameters that were never checked

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amends:** [ADR-0006](0006-score-computation.md), [ADR-0009](0009-airport-universe-and-peer-tiers.md)

---

## Context

Two earlier ADRs made promises that were never kept:

1. **ADR-0006** described the component weights as "sanity-checked against real
   output, and accompanied by a note on what reorders when they shift — a more
   honest answer than defending them as principled." No such check was run.
2. **ADR-0009** defined a volume floor to keep tiny airports out of the
   percentile pools, but never fixed or validated the number. A value of 100
   departures/month was chosen while writing the config and never revisited. It
   excluded **938 of 1,311 airports** — 72% of the dataset.

An unverified claim in a design document is worse than no claim: it invites the
question and has no answer. Both were run.

---

## 1. Weight sensitivity — the weights matter less than expected

The full scoring pass was re-run under six weightings and the resulting rankings
compared against the base (0.40 / 0.30 / 0.30).

**Large hubs**, base top ten: EWR, LGA, ATL, MCO, BOS, JFK, ORD, MIA, DFW, MSP

| Weighting | Top-10 overlap | New #1 |
|---|---|---|
| Equal 33/33/33 | **10 / 10** | EWR |
| Peak-heavy 60/20/20 | 9 / 10 | LGA |
| Fullness-heavy 20/60/20 | 9 / 10 | EWR |
| Delay-heavy 20/20/60 | 8 / 10 | EWR |
| Peak only 100/0/0 | 6 / 10 | LGA |

Medium hubs behave the same way: 7–10 of 10 retained, and **PBI is first under
every single weighting**.

**Finding: the shortlist is robust; only its internal order moves.** Even
discarding two of the three components entirely retains six of the top ten. The
first place is EWR or LGA in every scheme tested.

This is the answer to "why 0.40?" — not a defence of the number, but evidence
that the number is not load-bearing. **Which airports get flagged is a property
of the data; the ordering within the shortlist is a property of the weights.**
Answers should therefore lean on membership and treat fine-grained rank
differences as soft.

The weights are unchanged.

---

## 2. The volume floor was measuring the wrong thing

The floor counted **departures**. Departures cannot distinguish a regional jet
airport from an Alaskan village served by nine-seat bush planes.

| Excluded by the old floor | Passengers/yr | Admitted by the old floor | Passengers/yr |
|---|---|---|---|
| **TTN** Trenton Mercer | **156,151** | PKA Napaskiak | **1,194** |
| **PBG** Plattsburgh Intl | 86,052 | ILI Iliamna | 1,860 |
| **PSM** Portsmouth (NH) | 82,727 | SVA Savoonga | 4,139 |
| **FSM** Fort Smith Regional | 60,775 | AFW Fort Worth Alliance | 894 |

Trenton carries 134 passengers per departure; Napaskiak carries one. The thesis
is about **passenger** capacity, so the floor must be denominated in passengers.

**PSM Portsmouth, New Hampshire — 82,727 passengers — is in New England**, and
was being silently dropped from the assignment's own regional question.

### Decision

The floor is **10,000 annual passenger boardings**, replacing the departures
test.

That figure is not invented: it is the federal definition of a **primary
airport** (49 U.S.C. 47102) — the same statute the hub tiers already come from.
The change therefore *removes* an arbitrary parameter rather than substituting
another.

Effect: **+104 real commercial airports** admitted (Trenton, Ponce, Plattsburgh,
Portsmouth, Niagara Falls, Fort Smith…), **−87 removed** that fly a great deal
while carrying almost nobody (Fort Worth Alliance at 894 passengers on 8,899
departures; Wilmington Airpark at zero; Alaskan bush strips).

Every New England airport of any commercial significance is now retained.

---

## Consequences

- `MIN_MONTHLY_DEPARTURES` is replaced by `MIN_ANNUAL_ENPLANEMENTS`, and the
  exclusion message now names the federal threshold rather than a private one.
- A regression test asserts the distinction directly: a cargo field with 8,899
  departures and 894 passengers is excluded, while a regional airport with 1,160
  departures and 156,151 passengers is scored.
- Cargo-only airports leave the passenger universe entirely. This is consistent
  with ADR-0014, which already holds that cargo is invisible to the hourly
  metrics — an airport that is *only* cargo cannot be scored on a passenger
  thesis, and saying so is better than scoring it badly.

---

## Note on method

Neither problem was visible in the code. The weights looked reasonable and were;
the floor looked reasonable and was measuring the wrong quantity entirely. Both
took a few minutes to check and one of them was wrong.

The generalisable point: **a parameter that has never been looked at is not a
decision, it is an accident that has not been noticed yet.**

# Design — AI.I, Airport Investment Intelligence

The question behind the product is *where would a renovation pay off*, and the
honest answer is not "the busiest airport". It is the airport with **demand it
cannot serve**: full aircraft, a schedule with no slack, delays caused by
capacity rather than weather — and a terminal, not a runway, as the binding
constraint.

Everything below follows from that. The 28 records in [adr/](docs/adr/) hold the
detail, including the approaches that were tried and rejected.

---

## What was asked, and where it is

| Requirement | Where |
|---|---|
| Answer the four named questions | All four verified end to end, in one conversation |
| Use public APIs for airport data | BTS T-100, BTS On-Time, OurAirports, FAA NAS Status |
| Rank or compare on defined logic | [Scoring methodology](#scoring-methodology) below |
| Explain its reasoning | Prose plus an evidence card per answer: components, percentiles, raw values, tool calls |
| Conversational follow-up | Verified over eight turns |
| **Deterministic scoring, not only LLM** | `scoring.py` — pure functions, no I/O, no model. [Where AI is used](#where-ai-is-used) |
| Chat interface (voice a bonus) | Both. Voice is English and Hebrew, continuous, interruptible |
| Communicate assumption, uncertainty, scoping | Computed, not narrated — see [Where AI is used](#where-ai-is-used) and [Limits](#limits) |

**The three things that matter most, if you read nothing else:**

1. **The model never produces a number.** It picks which questions to ask of the
   data; `scoring.py` decides what is true. A harness traces every figure in
   every answer back to a tool result and fails on any it cannot source.
2. **Congestion is measured within an airport's own size tier**, because "is
   this airport constrained for what it is" is the investment question — not
   "is it big".
3. **Constraint type is the finding that changes decisions.** A runway-limited
   airport does not need a terminal, however congested it is. That is the
   difference between a ranking and advice.

---

## Architecture

```
BTS T-100 · BTS On-Time · OurAirports        public datasets, downloaded once
        │
        ▼  ETL (DuckDB)                      36 and 12 month windows
   data/airports.db                          SQLite, 7.9 MB, ships with the source
        │
        ▼  scoring.py                        pure functions — the deterministic core
   396 scored airports
        │
        ▼  six tools                         the only way the model touches data
   agent.py  ←→  Gemini                      chooses tools, writes prose
        │
        ▼
   chat  ·  voice (bonus)
```

A fuller version of this diagram, with the voice shell and the checks that
keep it honest, is in [docs/architecture.md](docs/architecture.md).

A **batch snapshot**, not live API calls per question ([ADR-0005](docs/adr/0005-batch-snapshot-architecture.md)).
Three reasons: an analyst asking "rank New England" needs all of them scored,
not one; percentiles are only meaningful against the whole cohort; and an
answer must be reproducible tomorrow. The cost is staleness, so the snapshot
carries its own dates and every answer states the window it rests on.

---

## Scoring methodology

**Congestion** — three components, each a **percentile within the airport's own
FAA hub tier**, then weighted:

| Component | Measures | Weight |
|---|---|---|
| Peak saturation | median hour ÷ peak hour — is the whole day busy, or one spike? | 0.40 |
| Fullness | passengers ÷ seats — is the demand real, or empty aircraft? | 0.30 |
| Capacity delay | NAS delay minutes per departure — delay the airport causes | 0.30 |

**Growth is a multiplier, not a fourth component:**

```
final = congestion × clamp(3-year passenger CAGR scaled, 0.75, 1.25)
```

Growth is not itself a reason to invest — a fast-growing empty airport is still
empty. It is a reason to **trust or distrust** the congestion signal, so it can
move a score by ±25% and no more ([ADR-0002](docs/adr/0002-growth-as-bounded-multiplier.md)).
One asymmetry is deliberate: falling passengers only penalise an airport if the
load factor is falling too. Fewer, fuller flights is a constrained airport, not
a dying one.

**Constraint type decides whether the answer is actionable at all:**

```
peak movements ÷ effective runways   →  runway-limited   a terminal will not help
                                        terminal-limited expansion is actionable
```

This is worth more than the ranking position, because it is what stops money
going to the wrong project. Two corrections were needed to make it true.
Movements count arrivals *and* departures — on departures alone LaGuardia read
as terminal-limited at 14.9 per runway; counting both directions puts it at 29.9
and "mixed". And runways are counted as **usable streams, not strips**: SFO has
four, but two pairs sit closer than the FAA's 2,500 ft minimum for independent
operations, so it has two. Dividing by four made the most constrained airfield
in California look comfortable ([ADR-0023](docs/adr/0023-effective-runway-count.md)).

**Two properties of the output that are easy to misread.** Scores compare
**only within a tier** — SNA's 76.8 against LAX's 42.1 means SNA is more
constrained relative to its peers, not busier. And the final score is an
**index on 0–125**, not a percentage, because a 0–100 percentile times a 1.25
multiplier can exceed 100.

**The external check:** EWR 88.3, LGA 84.7, ATL 81.0 lead the large hubs.
Newark and LaGuardia coming out on top matches what the industry already knows,
and nothing was tuned to produce it.

---

## Key tradeoffs

**Percentiles within tier, not absolute numbers.** A percentile answers "how
constrained is this airport for its size", which is the investment question.
The cost is that scores are not globally comparable, and the interface has to
say so on every cross-tier comparison — so it does.

**A one-day snapshot, not a live feed.** Reproducible and fast, and stale by
construction. Mitigated by making the data window part of every answer rather
than a footnote.

**Three components, not ten.** Each is defensible from public data and testable.
More components would look more sophisticated and would mostly add
unfalsifiable weighting. Sensitivity was measured: shifting the weights moves
the internal order but leaves the shortlist stable ([ADR-0022](docs/adr/0022-validating-two-unchecked-parameters.md)).

**No spilled-demand model.** "Unmet demand" could be estimated with a gravity
or spill model. Any such number would be an invention wearing a decimal point,
so the agent describes the constraint and states plainly that it does not
estimate the count. Refusing to answer is part of the product.

**Cargo is excluded from hourly metrics and flagged, not hidden.** T-100
separates freight; the on-time feed does not. At Anchorage (57% of departures),
Memphis (65%) and Louisville (68%) the peak-hour score is understated. The flag
travels with the score ([ADR-0014](docs/adr/0014-cargo-blind-spot-in-peak-hour-data.md)).

**One scraped source.** T-100 is not served by a REST API — it requires posting
an ASP.NET form with a scraped token. The alternative was dropping passenger and
seat data, which the fullness component depends on. It fails loudly if BTS
redesigns the page.

---

## Where AI is used

**Three places, all at the edges. None of them touch a number.**

| Layer | Model | Job |
|---|---|---|
| Reasoning | Gemini `3.5-flash-lite` (+ fallback chain) | Decide which tools to call; write the prose |
| Listening | Groq `whisper-large-v3` | Speech → text, before the agent |
| Speaking | OS speech synthesis (OpenAI as fallback) | Text → speech, after the agent |

**The boundary is the point of the design.** The model chooses *what to ask*;
`scoring.py` decides *what is true*. Every figure in an answer comes from a tool
result, the tools return raw values alongside percentiles, and the interface
shows the arithmetic beside the prose. The model is never asked to compute,
compare or estimate.

This is enforced rather than requested. A harness (`scripts/evaluate.py`) asks
the agent real questions and **traces every number in the prose back to a tool
result**, failing on any figure it cannot source. That check exists because the
recurring failure in this project was never a crash — it was a fluent, confident,
wrong answer that reads perfectly.

**Uncertainty is computed, not narrated.** Confidence and caveats are derived
from coverage and missing components in Python, then handed to the model as
facts it must repeat ([ADR-0010](docs/adr/0010-uncertainty-as-computed-metadata.md)).
An airport with 40% of its score missing says so, in its own answer, without the
model deciding how confident to sound.

**Where AI was deliberately not used:** scoring, ranking, percentile
computation, geography resolution, the confidence level, and anything numeric.

---

## Limits

Stated here because the agent states them in its answers too — an unqualified
number from a partial dataset is the failure this design is built against.

- **US airports only**, ≥10,000 passengers a year (the federal "primary airport"
  definition). A question about Heathrow is answered as out of scope, not as
  "not found".
- **Unmet demand is not modelled.** The agent describes the constraint and says
  plainly that it does not estimate how many passengers an airport turns away.
- **Cargo is invisible to hourly metrics** — Anchorage 57% of departures,
  Memphis 65%, Louisville 68%. Those peak-hour scores are understated and carry
  the flag with them.
- **63 of the 396 scored airports are missing a component**, and 52 of those are
  scored on **one** — fullness alone. Renormalising is defensible arithmetic
  (ADR-0010) and a poor summary, so every such score is reported as low
  confidence and names the component it rests on. Several of them still sit in
  the overall top twenty, above airports measured on all three; within a tier,
  which is how the tools present rankings, they stay among their own kind. PSM
  is the sharp case in a tier anyone will ask about: top of New England with
  40% of its score absent, and it says so.
- **Two data windows** — 12 months for delay, 36 for traffic — which answers
  must distinguish rather than blend.
- **Place names resolve in English only**, including inside a Hebrew
  conversation.

# ADR-0015: Four parameters recalibrated against the real distribution

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amends:** [ADR-0006](0006-score-computation.md)
- **Amended by:** [ADR-0023](0023-effective-runway-count.md) — effective runway count replaces the raw count

---

## Context

ADR-0006 fixed the scoring formula with parameters chosen on reasoning alone,
before any data existed. Running the first full build against 12 months of
on-time data and 36 months of T-100 showed four of them were wrong — not
marginally, but by enough to make the output misleading.

They are corrected here, with the evidence, rather than quietly edited.

---

## 1. Peak saturation: threshold counting → median-to-peak ratio

**As specified:** the share of operating hours reaching 80% of the airport's
own busiest hour.

**What went wrong.** The metric is set by a single outlier hour. LAX schedules
a large 08:00 spike; the rest of its day runs at roughly half that. Because the
bar is 80% of the spike, almost no hour cleared it and LAX scored **0.11** —
close to the bottom of all large hubs — despite operating 600–1,200 flights an
hour from 06:00 to 23:00. An airport busy all day was being measured as empty.

**The correction:** peak saturation is now `median operating hour / peak hour`.

It measures the same property — how close a typical hour runs to the busiest —
without depending on one hour, and it **removes the arbitrary 80% threshold
entirely**, deleting a parameter rather than retuning it.

| | old (80% of max) | new (median ÷ peak) |
|---|---|---|
| LGA | 0.38 | 0.76 |
| ATL | 0.28 | 0.71 |
| ORD | 0.27 | 0.60 |
| LAX | 0.11 | 0.53 |

Both orderings agree that LGA is flattest and LAX peakiest, and that ordering is
correct: **LaGuardia is slot-controlled, so the FAA caps movements per hour and
literally flattens the profile.** That flatness is the signature of a capacity
ceiling. LAX genuinely has slack off-peak; its problems are landside, not
airfield.

The 80% count is retained in the data as `near_peak_hours` — useful for
explanation ("N hours a day run close to the peak"), but no longer scored.

## 2. Growth full scale: 10% → 20% CAGR

Observed passenger CAGR across the eligible universe: median ~0%, p75 10%,
p90 20%. With full scale at 10%, **97 of 373 airports (26%) sat at the maximum
multiplier**, making growth a blunt instrument that could no longer distinguish
strong growth from exceptional growth.

At 20% the cap is reached by roughly the top decile, which is what "exceptional"
should mean. Airports at the cap fell to 24 of 373.

## 3. Constraint type: departures per runway → estimated movements per runway

**As specified:** runway-limited above 20 departures per runway in the peak
hour.

**What went wrong.** The observed distribution has a median of 1.5 and a
maximum of 24.8, so the thresholds classified **248 airports terminal-limited
against 1 runway-limited** — a field carrying no information. Worse, LaGuardia
— two intersecting runways, the most slot-constrained airport in the country —
was classified "mixed".

**The error was conceptual, not numeric.** A runway is consumed by arrivals as
well as departures, but on-time data reports departures only. Total movements
are now approximated as **departures × 2**, justified by scheduled service being
near-symmetric over a day: an aircraft that lands must also leave.

Thresholds are set against realistic movement rates — an independent runway
sustains roughly 30–45 movements/hour — at **≥25 runway-limited, <15
terminal-limited**. LGA now lands in the runway-limited band and Boston, which
has airfield capacity to spare, in the terminal-limited band.

## 4. Confidence thresholds: 0.85/0.60 → 0.75/0.50 coverage

Carrier coverage tops out near **0.8 even at ORD and ATL**, because the T-100
denominator includes foreign carriers and charter operators that fall outside
the on-time reporting rule entirely. A 0.85 bar therefore labelled every major
hub "medium confidence" for a structural reason rather than a data-quality one.

Thresholds are now set against the observed ceiling.

---

## 5. Constraint type is only asserted for constrained airports

**Added after the change above.** With movements-per-runway fixed, the label was
still wrong at the other end of the scale: **Lihue scored 12.5 — thoroughly
uncongested — and was labelled "terminal-limited"**, because its runways were
quiet. Nineteen airports scoring under 30 carried that label.

"Terminal-limited" reads as *build a terminal here*. At an airport with no
congestion the honest answer is that nothing needs building, so below a
congestion score of 35 the type is reported as **"not constrained"**.

The threshold was first set at 50 — the median of each tier — and that was too
aggressive: **SFO, which scores near the middle of the large hubs and is famous
for delays, was declared "not constrained" on a 0.2-point margin.** Claiming an
airport is fine is as strong a claim as calling it constrained and needs the
same distance from the boundary. At 35 (the bottom third) SFO returns to
"mixed" and Lihue is correctly described.

## 6. Missing components are named, not merely scored around

Sixty-three scored airports have **no peak-hour data at all** — too few
scheduled departures for any hour to average one flight a day. Their scores are
computed from the remaining two components and renormalised (ADR-0010), which is
correct, but the reader was only told confidence was "low".

Portsmouth (PSM) makes the case: it is the **highest-scoring airport in New
England at 90.7**, and 40% of that score — the peak-saturation component — does
not exist. A caveat now names the missing component explicitly rather than
leaving it to a confidence label.

---

## A limitation this exposed — since fixed by [ADR-0023](0023-effective-runway-count.md)

> **Resolved.** Capacity is now computed from runway geometry as independent
> streams rather than counted as pavement. SFO's four runways resolve to two and
> it reports runway-limited. The original limitation is kept below as written.

**Runway count overstates capacity where runways are not independent.** SFO's
closely-spaced parallels cannot be used independently in poor visibility, so its
effective capacity is far below its four-runway count; the same applies to
intersecting layouts. The heuristic reads such airports as having more airfield
capacity than they do, and SFO's score is likely understated as a result.

Fixing this needs FAA airport capacity benchmarks — real declared capacity per
airport rather than a runway count. Recorded in further work.

---

## Consequences

- Large-hub ranking now reads: EWR 88.3, LGA 84.7, ATL 81.0, MCO 80.7, BOS 79.6
  — the two most congested airports in the country at the top, which is the
  strongest available external check on the whole model.
- One parameter (the 80% threshold) was **deleted** rather than retuned. Fewer
  knobs is a better outcome than better-tuned knobs.
- Every change here came from looking at the distribution rather than reasoning
  about it. The parameters in ADR-0006 were defensible in the abstract and three
  of the four were wrong in practice.

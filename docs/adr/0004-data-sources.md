# ADR-0004: Data sources — BTS T-100, BTS On-Time Performance, OurAirports, FAA NAS Status

- **Status:** Accepted (verified against live sources 2026-08-12)
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Follows:** [ADR-0003](0003-congestion-components.md)

---

## Context

ADR-0003 was accepted conditionally: it assumed US public data provides delay broken down by
cause, passenger and seat counts, and flight-level scheduled departure times. That assumption
has now been verified against live sources.

---

## Decision

Four sources, each mapped to a specific job.

| Source | Provides | Feeds |
|---|---|---|
| **BTS T-100 Segment** (Domestic 28DS + International 28IS) | Monthly, per carrier × origin × destination × aircraft: passengers, available seats, scheduled and performed departures, load factor | Fullness, growth trend, long-haul share |
| **BTS Airline On-Time Performance** | Flight-level rows, 1987–present. `CRSDepTime`, `DepTimeBlk`, and delay decomposed into `CarrierDelay` / `WeatherDelay` / `NASDelay` / `SecurityDelay` / `LateAircraftDelay` (cause fields since June 2003) | Peak-hour crowding, capacity-caused delay |
| **OurAirports** (`airports.csv`, `runways.csv`) | Public domain, refreshed nightly, ~80k airports: coordinates, region/state, plus runway count and length | Geography resolution ("New England", "the LA airports"); runway-vs-terminal constraint split |
| **FAA NAS Status** `https://nasstatus.faa.gov/api/airport-status-information` | Live, no API key, XML, refreshes every 1–2 minutes: active ground delay programs, ground stops, closures, airspace flow programs | Current-conditions context **only** |

### The delay-cause mitigation is confirmed, not hoped for

`NASDelay` — the National Airspace System bucket — is specifically the volume and
capacity-attributable portion of delay. ADR-0003's mitigation against the "delay ≠ capacity
shortage" objection is therefore a precise instrument rather than a proxy. Weather and
late-aircraft delay are excluded by construction.

### The FAA live feed is deliberately excluded from the score

The feed reports only *currently active* disruptions and stores no history; on a normal day
it is largely empty. It is therefore unusable as a scoring input for two reasons:

1. It would make the ranking **non-deterministic** — the same question would score
   differently an hour later, violating the assignment's determinism requirement.
2. One day's weather is not an investment signal.

It is exposed as a separate `current_conditions(airport)` tool, clearly labelled live and
kept distinct from the historical score.

---

## Verified caveats

1. **On-Time Performance reporting coverage is broad but not total.** Filing is mandatory
   for carriers above **0.5%** of domestic scheduled passenger revenue (lowered from 1% in
   2018), and reportable airports were expanded from the top 30 to **any US large, medium,
   small or non-hub airport**. Codeshare flights operated by regionals under a mainline code
   must also be filed. The residual gap is airports served exclusively by very small
   independent operators. Coverage is checked per airport at build time and reported as
   blank rather than imputed.
   **T-100 has no such threshold** — all carriers file it — so fullness and growth cover
   small airports fully. Only the delay and peak-hour signals carry this gap.

2. **Publication lag.** T-100 domestic publishes roughly two months after month end;
   international roughly three months later still. The agent describes recent conditions,
   not today, and states its data window in answers.

3. **Long-haul lives in a different file.** The on-time database is domestic-oriented, so
   international route questions (e.g. Anchorage long-haul share) are answered from T-100
   International, with its longer lag.

4. **Authoritative data is bulk files, not query APIs.** TranStats is a form-driven CSV/zip
   download. A Socrata JSON API exists on `data.transportation.gov` (e.g. dataset
   `56fa-sf82`), but it appears to expose summary tables rather than the flight-level rows
   required for peak-hour and delay-cause analysis, and its last update showed as January
   2025. It is therefore not relied upon.

---

## On the assignment's "use public APIs" requirement

The brief asks for public APIs; the authoritative US aviation data is published as bulk
files. This is addressed rather than argued around:

- All ingest is **programmatic** — scripted HTTP requests, no manual download steps.
- The **FAA NAS Status API** is a genuine live public API doing real work in the system.
- The constraint is **disclosed in the design document** under "key tradeoffs", which the
  assignment explicitly asks for: the authoritative data is published in bulk, so ingest is
  batch and live APIs serve current status.

---

## Consequences

- ADR-0003's conditional status is lifted; all three congestion components are buildable.
- Bulk, lagging, flight-level-large data forces a batch snapshot architecture rather than
  per-request fetching — see [ADR-0005](0005-batch-snapshot-architecture.md).

---

## Sources consulted

- BTS TranStats On-Time Performance field list — https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ
- BTS Data Bank 28DS (T-100 Domestic Segment) — https://www.bts.gov/browse-statistical-products-and-data/bts-publications/data-bank-28ds-t-100-domestic-segment-data
- 14 CFR Part 234 (Airline Service Quality Performance Reports) — https://www.ecfr.gov/current/title-14/chapter-II/subchapter-A/part-234
- BTS Technical Directive 31, on-time reporting — https://www.bts.gov/topics/airlines-and-airports/number-31-technical-directive-time-reporting-effective-jan-1-2019
- OurAirports open data — https://ourairports.com/data/
- FAA NAS Status User Guide — https://nasstatus.faa.gov/static/media/NASStatusUserGuide.cccc6d48.pdf

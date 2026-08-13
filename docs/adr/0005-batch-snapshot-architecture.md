# ADR-0005: Batch snapshot architecture — ingest once into a local store, never fetch per request

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0013](0013-split-ingest-windows.md) — ingest windows differ by source; [ADR-0017](0017-interface-makes-determinism-visible.md) — the data window travels with each answer, not the page chrome
- **Follows:** [ADR-0004](0004-data-sources.md)

---

## Context

The system could either (a) fetch source data live on each user question, or (b) ingest
once into a local store that the agent queries.

Option (a) is not mechanically viable with these sources. TranStats cannot be queried for a
single airport-month; it builds a zip of everything matching the selected months and fields.
Flight-level on-time data runs to hundreds of thousands of rows per month — tens of
megabytes zipped. Downloading and unpacking that inside a chat turn is impossible, and it
would be re-downloaded for every question.

---

## Decision

**Two clearly separated stages.**

```
BUILD  (once, offline, minutes)
    download scoped CSV slice  →  clean/filter  →  aggregate per airport  →  local DB
         (large)                                                              (small)

CHAT   (per question, milliseconds)
    user  →  LLM selects a tool  →  tool queries DB + computes score  →  LLM explains
```

**The aggregation is the essential step.** Millions of flight-level rows collapse to roughly
one row per airport per month, carrying peak-hour distribution, NAS-delay share, load factor,
passengers and seats. The result is megabytes, small enough to commit to the repository.

**Scope of the download:** a bounded window (approximately the most recent three years —
enough to support the multi-year growth trend of ADR-0002) and only the required columns.
Not the full 1987-present archive.

**The LLM never reads raw rows and never performs arithmetic.** It calls tools such as
`score_airport(code)` or `rank_region(region)`; those tools query the DB, compute scores
deterministically, and return numbers plus components. The LLM only narrates the result.
This separation is what makes the assignment's "deterministic scoring, not only LLM output"
requirement true by construction rather than by assertion.

---

## Rationale

- **Determinism.** A frozen local snapshot means the same question yields the same score,
  and the scoring logic is unit-testable against fixed inputs. A live-fetch design cannot
  guarantee this.
- **Latency.** Conversational follow-ups must feel instant; local queries are milliseconds.
- **Demo robustness.** If TranStats is slow or unavailable during review, the application
  still works.

---

## Refresh strategy

The build stage is a re-runnable script parameterised by date window
(`build.py --start YYYY-MM --end YYYY-MM`); no years are hardcoded. The database
records its windows in the `meta` table — `built_at`, plus `ontime_window_start`
/ `ontime_window_end` and the same pair for `t100`, because the two sources do
not cover the same months (ADR-0013). **The agent states the relevant window in
its answers**, so a stale snapshot announces itself rather than silently
misleading.

**Deliberately not built:** scheduled/cron refresh, incremental month appends, and
auto-detection of newly published months. All are straightforward; none demonstrates
anything the design does not already show. They belong in "further work".

The risk that matters is not "does it auto-update" but "does it quietly misrepresent how
current it is". A visible data window addresses that; automation is an operational concern.

---

## Consequences

- The shipped dataset is a snapshot and goes stale between builds. Acceptable: the source
  data is already 2–5 months old at publication (ADR-0004), so freshness was never
  achievable.
- Live current-conditions questions are served by the FAA NAS Status tool, which sits
  outside the snapshot and outside the score.
- Repository ships with a prebuilt aggregate so reviewers can run the chat interface
  without executing a lengthy ingest.

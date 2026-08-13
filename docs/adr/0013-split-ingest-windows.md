# ADR-0013: Split ingest windows — 12 months of on-time, 36 months of T-100

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amends:** [ADR-0005](0005-batch-snapshot-architecture.md), [ADR-0011](0011-storage-and-build-order.md)

---

## Context

ADR-0005 specified a single ~3-year ingest window across all sources. Building
the downloader exposed a constraint that makes that impossible in the available
time.

### Measured, not assumed

- **BTS throttles to ~42 KB/s per connection.** Measured directly: a 27 MB
  on-time zip takes roughly 11 minutes. A 36-month window is **6–7 hours** of
  download alone.
- **The throttle is per-connection, not per-IP.** Four concurrent downloads each
  sustained ~42 KB/s independently, giving near-linear scaling.
- **T-100 is ~0.5 MB/month** — roughly 50× smaller than on-time.

### The asymmetry that resolves it

The two sources feed different parts of the score, with different history needs:

| Source | Size/month | Feeds | Needs history? |
|---|---|---|---|
| On-Time | ~27 MB | Peak saturation, NAS delay | **No** — both are current-state measures |
| T-100 | ~0.5 MB | Load factor, growth trend | **Yes** — 3-year trend per ADR-0002 |

**The expensive source is the one that does not need history.** Peak saturation
and capacity delay describe how an airport runs *now*; the three-year
requirement of ADR-0002 applies only to the growth multiplier, which is computed
from passengers in T-100.

---

## Decision

| Source | Window | Rationale |
|---|---|---|
| **On-Time** | 12 months | Full seasonality (summer peaks, winter weather) without a multi-hour download |
| **T-100** | 36 months | The growth trend, unchanged from ADR-0002 |
| **Concurrency** | 8 workers for on-time; T-100 serial | Each T-100 POST needs its own freshly scraped `__VIEWSTATE`, and the files are small enough that concurrency buys nothing |

Total: ~324 MB + ~18 MB, roughly 15–20 minutes once, against 6–7 hours for the
original plan.

Eight workers is deliberately modest — this is a public government server, and
the goal is to clear the per-connection throttle, not to extract maximum
throughput.

---

## What is given up

No **delay or peak-hour trend** over three years — only current state, plus the
3-year passenger trend. This costs nothing against the design as specified:
ADR-0006 never used delay history, and the growth multiplier is defined on
passengers alone.

It does close off one future extension — "is congestion at this airport getting
worse?" — which would need a longer on-time window. Recorded as further work
rather than silently lost.

---

## Consequences

- `config.py` carries two windows (`ONTIME_*`, `T100_*`) rather than one, each
  independently overridable from the CLI.
- Answers drawing on peak-hour or delay data state a **different, shorter data
  window** than answers drawing on growth. The per-response `data_window` of
  ADR-0010 already accommodates this; it is now load-bearing rather than
  precautionary.
- The downloader must survive stalls: BTS connections were observed hanging
  indefinitely without closing, so a per-read timeout is required. A total
  request budget would kill healthy-but-slow transfers instead.

---

## Note on method

This decision came from measuring rather than estimating. The original
single-window plan was reasonable on paper and wrong in practice by two orders
of magnitude in wall-clock time. Discovering it during the ADR-0011 thin
vertical slice — before any scoring or agent code existed — is the slice
justifying itself.

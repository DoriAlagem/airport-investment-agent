# ADR-0011: Storage layout, build/refresh model, and delivery order

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0012](0012-question-trace-corrections.md) — constraint_type promoted out of the cut list; [ADR-0013](0013-split-ingest-windows.md) — split ingest windows
- **Follows:** [ADR-0005](0005-batch-snapshot-architecture.md)

---

## Storage layout

```
data/raw/*.zip|csv     raw TranStats + OurAirports downloads — large, gitignored
        │
        │  DuckDB: filter → aggregate → join   (build time only, persists nothing)
        ▼
data/airports.db       SQLite — small, committed to the repository
        │
        ▼
tools → agent → chat
```

### Tables in `airports.db`

| Table | Contents |
|---|---|
| `airports` | Metadata: code, name, coordinates, state/region, hub tier, runway count |
| `airport_metrics` | Per airport per month: load factor, peak-hour distribution, NAS-delay minutes, passengers, seats, departures |
| ~~`airport_scores`~~ | *Considered and not built.* Scores are computed in `scoring.py` at load time, so weights stay tunable without a rebuild. A cache table would have been a second place for the numbers to live, and the load takes well under a second for 396 airports. |
| `meta` | Data window, build date, coverage statistics |

### Why SQLite for serving

Standard-library support in Python, no setup, a single file, and a trivial query load — a
few hundred pre-aggregated rows. A database server would be infrastructure for a demo that
needs none. Committing the file lets a reviewer run the chat interface without executing an
ingest.

### Why DuckDB for the build

DuckDB is an embedded engine that runs SQL **directly over CSV files** and streams data
larger than memory, where pandas would load everything into RAM. The on-time files run to
hundreds of thousands of rows per month.

It performs three jobs: **filter** (keep only required columns and months), **aggregate**
(collapse millions of flight rows to roughly one row per airport per month), and **join**
(stitch on-time, T-100 and OurAirports data on airport code). Millions of rows in, a few
thousand out.

**DuckDB persists nothing.** It runs during `build.py` and exits; the only saved artefact is
the SQLite file. It is a **build-time dependency only** — running the chat against a
committed `airports.db` does not require it. Requirements files are split accordingly.

If the aggregation proves to fit comfortably in memory, pandas alone would suffice and
DuckDB can be dropped. This is an implementation detail, not an architectural commitment.

### Scores are computed, not frozen

Scoring runs in Python from `airport_metrics` at query time rather than being baked into a
table. This keeps the scoring logic unit-testable and the weights tunable without a rebuild.
**The database stores facts; the code computes judgments.**

---

## Build and refresh model

| Action | Frequency | Requires download + DuckDB? |
|---|---|---|
| Use the chat | Any time | No |
| Refresh to newer months | Occasionally | Yes |
| Add a new metric or column | When the design changes | Yes |

The SQLite snapshot persists indefinitely — a week or a year later the chat runs unchanged.
A rebuild is required only for a **different date range** or **different fields**, and
overwrites `airports.db`.

The `meta` table records which window the file was built from, so the agent continues to
state "based on data through May 2026" rather than implying currency (ADR-0005).

---

## Delivery order

1. **Thin vertical slice** — three airports, one month, hardcoded. Prove the joins work and
   a score emerges end to end.
2. **Widen data** — full airport universe, three-year window, size tiers, volume floor.
3. **Complete scoring** — all three components, growth multiplier, constraint type,
   confidence metadata.
4. **Agent** — six tools, conversation loop.
5. **UI** — chat page.
6. **Design document** — assembled from these ADRs.
7. **Voice** — bonus.

### Why a vertical slice before layers

Building layer by layer means discovering at 6pm that the on-time columns do not join to
T-100 as assumed, with nothing that runs. A slice surfaces that at 11am against a working
skeleton, after which every remaining step is widening rather than building.

### Cut order under time pressure (from the bottom)

voice → realtime anything → constraint-type split → narrow the universe → shorten the data
window.

### Never cut

Deterministic scoring, confidence metadata, the design document. These are the graded items.

**Standing rule: the design document is written before voice.** It is a required
deliverable; voice is a bonus. The reverse is an easy mistake to make late in the day.

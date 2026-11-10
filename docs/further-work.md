# Further work

Ordered by value, not by effort. Everything here was consciously scoped out of
the one-day build; each entry says what it fixes and what makes it hard.

---

## 1. Close the cargo blind spot with OpenSky ADS-B

**The gap.** Peak saturation and capacity delay are computed from BTS On-Time
data, which by federal rule (14 CFR Part 234) covers only carriers above 0.5% of
domestic *passenger* revenue. Pure freight carriers are outside it, so **no
cargo flight appears in any hourly metric**. At cargo hubs — Anchorage, Memphis,
Louisville, Ontario (CA) — the peak-saturation score is biased low.

**The fix.** OpenSky Network publishes free ADS-B data covering all traffic,
freight included, with real timestamps. It would repair the metric rather than
annotate it.

**Why it wasn't done:** roughly half a day, and the hard part is not the
integration — it is reconciling **observed takeoffs** (ADS-B) against
**scheduled departures** (BTS). The two disagree by several percent on the same
airport, and an unexplained discrepancy could degrade the data rather than
improve it. ADS-B coverage is also thinner in remote Alaska, precisely where the
sharpest case sits.

**Current mitigation:** cargo share is computed per airport from T-100, and
airports above the materiality threshold carry an explicit downward-bias flag on
the score itself. See [ADR-0014](adr/0014-cargo-blind-spot-in-peak-hour-data.md).

---

## 2. Bounded counterfactual for unmet demand

The agent currently answers *"how constrained is this airport, and why"* rather
than *"how much demand is unmet"*, and says so plainly. A defensible upgrade is
pure arithmetic over measured inputs: *"relieving saturated hours to the tier
median would accommodate approximately X additional passengers annually at
current load factors."*

Must be framed as a capacity calculation, never a forecast — otherwise it
becomes the demand model rejected in [ADR-0003](adr/0003-congestion-components.md).

---

## 3. Congestion trend over time

[ADR-0013](adr/0013-split-ingest-windows.md) ingests 12 months of on-time data
against 36 months of T-100, because on-time is ~50× larger and BTS throttles to
~42 KB/s per connection. The consequence: we can show a 3-year *passenger* trend
but not a 3-year *congestion* trend, so the agent cannot answer "is this airport
getting more constrained?"

Fixing it is only download time — roughly 6 hours at current throughput, or less
with more parallelism.

---

## 4. Scheduled refresh

The build script is re-runnable and parameterised by date window, but refresh is
manual. Automation would mean a scheduler, incremental month appends, and
detection of newly published months. Deliberately skipped: the risk that matters
is a snapshot silently misrepresenting its currency, which the `meta` table and
per-answer data window already address. See
[ADR-0005](adr/0005-batch-snapshot-architecture.md).

---

## 5. Realtime speech-to-speech

The shipped voice layer uses the browser Web Speech API — a thin shell at the
edges that the agent and scoring never see. Realtime speech-to-speech was
estimated at 3–5 hours if cooperative and potentially a full day if not: it
replaces request/response with a streaming session and requires tool calling to
work *inside* an audio stream, where failures are slow to diagnose. See
[ADR-0008](adr/0008-stack-and-interface.md).

---

## 6. Weight calibration against outcomes

The scoring weights (0.40 peak saturation / 0.30 fullness / 0.30 capacity delay)
are a judgment call, documented as such. With a dataset of actual airport
expansion projects and their outcomes, the weights could be fitted rather than
chosen. That is a research project, not a feature — but it is the honest answer
to "why 0.40?".

---

## 7. Runway-level capacity modelling

**Partly done** — see [ADR-0023](adr/0023-effective-runway-count.md). Capacity is
now computed from runway geometry: parallels closer than the FAA separation
minimum collapse into one usable stream, so SFO's four runways resolve to two.

What remains: crossing runways are still counted separately though they cannot
be used simultaneously, and geometry is not declared capacity. FAA airport
capacity benchmarks — real published movement rates per airport, per weather
configuration — would replace the heuristic outright.

---

## 8. Duplicated spoken-text trimming (open decision)

The logic that prepares an answer to be read aloud — strip markdown, drop
tables, cut at ~420 characters on a sentence boundary that is not a decimal
point — exists **twice**:

- `src/airport_intel/speech.py` → `spoken_summary()`, used by `/api/speak`
- `web/index.html` → `speakable()`, used by the browser voice

They agree today. Nothing enforces that: no test compares them and no build
step notices. The decimal-truncation bug (`74.2` read as `74.`) had to be fixed
by hand in both, from memory.

**Three ways out, undecided:**

1. **Delete the Python copy.** Speech output moved to the browser (ADR-0028),
   and `/api/speak` survives only as the fallback for when the browser refuses
   to speak (Safari, outside a click). Least code, and the duplication
   disappears — but it also discards that fallback.
2. **Have the browser call the server** to trim. One implementation, at the cost
   of a network round-trip for string manipulation.
3. **Keep both, add a conformance test** that runs the same inputs through each
   and asserts identical output. Cheapest to do, does not reduce the code.

Both copies are live, so option 1 costs the Safari fallback. Option 3 is the
cheap way to make the agreement enforced rather than remembered.


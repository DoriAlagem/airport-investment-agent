# ADR-0001: The scoring thesis — rank by suppressed demand, not by growth or a blended index

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor

---

## Context

The assignment asks for an agent that identifies "airports where renovations will be most
profitable based on increased flight and passenger capacity."

The core difficulty: **renovation profitability is not observable in any public dataset.**
There is no ROI field, no capex figure, no forward revenue projection available through a
public aviation API. Whatever the agent ranks on is therefore a **proxy**, and the quality
of the deliverable depends less on the sophistication of the math than on whether the proxy
is honestly chosen and clearly defended.

Three candidate proxies were considered.

### Option A — Constraint relief ("this airport is full")

Rank airports by evidence that the existing facility is a binding constraint: delays,
schedule congestion, aircraft load factors, demand that cannot be accommodated. Renovation
is profitable because the demand already exists and is being turned away.

### Option B — Growth trajectory ("this airport is growing")

Rank airports by year-over-year increases in passengers and operations. Renovation is
profitable because it front-runs demand that is arriving regardless.

### Option C — Blended investability index

A composite of six or seven weighted factors: size, growth, delays, carrier diversity,
international share, hub status, etc.

---

## Decision

**Option A is the spine of the score.** The agent ranks airports by *suppressed demand* —
demand that exists today but cannot be served because of facility constraints.

Option B is retained only as a **modifier**, not as a primary factor (see ADR-0002).

Option C is explicitly rejected.

The agent's one-line claim is:

> Airports are ranked by demand that exists today but cannot be served because the
> facility is too small — adjusted for whether that demand is rising or falling.

---

## Rationale

1. **It is what the assignment actually says.** "Profitable based on increased flight and
   passenger capacity" is a constraint-relief statement. Profit arrives when capacity is
   the binding constraint and the renovation removes it.

2. **It unifies the scoring model with the Q&A surface.** One of the assignment's own
   sample questions is *"What is the unmet flight demand in SFO airport and why?"* — that
   question **is** Option A, stated aloud. If the ranking were built on B or C, the score
   and that question would be two unrelated systems, and the "why" would have to be
   answered by a separate ad-hoc mechanism. Under A, the score's components *are* the
   answer to "why".

3. **Growth alone inverts the signal.** A saturated airport often shows *flat* growth
   precisely because there is no room to add flights — not because demand is absent. Using
   growth as the primary factor would rank the most constrained airports *lowest*, which is
   backwards for this investment thesis.

4. **A blended index is unfalsifiable.** A seven-factor weighted score with hand-tuned
   coefficients cannot answer "why is this weight 0.15?" Two factors that can be defended
   are worth more than seven that cannot. This also keeps the deterministic logic small
   enough to be genuinely deterministic and auditable.

---

## Consequences

**Accepted costs:**

- Measuring "how constrained is this airport" is materially harder than looking up a
  passenger count. It requires delay, schedule, and capacity data rather than a single
  traffic statistic. Data sourcing becomes the main engineering risk (see ADR-0003).
- Suppressed demand is inherently an *inference*, not a measurement. The agent must state
  this uncertainty explicitly rather than presenting the score as fact.

**Benefits:**

- Every ranking is explainable by decomposition: the score's inputs are literally the
  reasons.
- The deterministic core stays small, testable, and defensible under questioning.

---

## Open questions spawned by this decision

- **The role of growth (Option B) as a modifier** — resolved in ADR-0002.
- **Whether suppressed demand is reported as a single number or decomposed by cause**
  (terminal/gate-constrained vs. runway/airspace-constrained). This matters because the
  assignment asks specifically about *terminal expansion* in New England, and an airport
  whose true constraint is runway capacity would not be helped by a new terminal.
  Deferred to a later ADR.

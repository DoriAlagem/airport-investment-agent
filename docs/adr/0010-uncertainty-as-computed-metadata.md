# ADR-0010: Uncertainty is computed metadata carried by every tool response, never model-generated

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Follows:** [ADR-0007](0007-agent-architecture.md), [ADR-0009](0009-airport-universe-and-peer-tiers.md)

---

## Context

The assignment explicitly requires the agent to *"clearly communicate assumption,
uncertainty and scoping."* Three approaches were considered:

- **A. Static disclaimer** in the documentation and a UI banner.
- **B. Model-generated caveats** — instruct the model in the system prompt to mention
  uncertainty where appropriate.
- **C. Computed confidence metadata** attached to every tool response, which the model is
  required to relay.

---

## Decision

**Option C, with A as a backstop.**

Every tool response carries data-quality fields alongside its result:

| Field | Example |
|---|---|
| `data_window` | 2023-06 → 2026-05 |
| `carrier_coverage` | 0.94 — share of departures flown by reporting carriers |
| `months_present` | 34 of 36 |
| `confidence` | high / medium / low, derived deterministically from the above |
| `caveats` | `["international data lags ~3 months"]` |

The system prompt enforces two rules: **never state a score without its confidence, and
never fill a null.**

Example output:

> PVD ranks 2nd among New England medium hubs (score 84) — **medium confidence**: on-time
> reporting covers 78% of departures here, so peak-hour figures may understate activity.

---

## Rationale

### Why model-generated caveats (B) are rejected

If the model authors its own uncertainty, that text is exactly as reliable as any other
generated text — it will hedge where the data is sound and sound confident where the data is
thin. **Uncertainty that is not computed is not uncertainty; it is tone.**

### The uncertainty is about the data, not the model

This distinction governs the whole design. The model never estimates an answer. It reports
what tools return, in three cases:

1. **Data complete** → score returned with `confidence: high`; stated plainly.
2. **Data partial** → score returned *with the gap*. The number is genuine, computed from
   the data that exists; the agent reports it **and** what is missing.
3. **Data absent** → tool returns null; the agent says so and stops. No estimation, no
   interpolation, no fallback to the model's general knowledge about airports.

There is therefore never a case of "the model is unsure, so it improvises."

### The failure mode being designed against

An agent that reports *"PVD scores 84"* with full confidence when that figure was computed
from three-quarters of the flights. The number is not wrong — presenting it without the gap
is.

---

## Consequences

- Confidence thresholds (what coverage level maps to high/medium/low) are one more explicit
  parameter, documented rather than hidden.
- A documentation requirement becomes **visible product behaviour** in the chat itself,
  which is materially more persuasive in review than a paragraph in a README.
- Out-of-universe airports (ADR-0009) and out-of-scope non-US airports return explicit
  refusals with reasons, rather than scores.

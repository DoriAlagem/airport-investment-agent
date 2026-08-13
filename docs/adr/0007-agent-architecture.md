# ADR-0007: Agent architecture — tool-calling loop over a small fixed tool set

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extended by:** [ADR-0024](0024-response-style.md) — the prose carries judgement, the card carries the numbers
- **Follows:** [ADR-0005](0005-batch-snapshot-architecture.md), [ADR-0006](0006-score-computation.md)
- **Amended by:** [ADR-0012](0012-question-trace-corrections.md) — `resolve_airports` returns primary match plus metro alternates

---

## Context

Two architectures were considered for connecting the language model to the deterministic
core:

**A. Intent router.** Classify each question into a fixed type (rank / compare / stat /
explain), then execute hardcoded logic for that type.

**B. Tool-calling loop.** Expose a small set of functions; the model selects which to call,
possibly several in sequence, and narrates the returned results.

---

## Decision

**Option B — a tool-calling loop over six tools.**

| Tool | Responsibility |
|---|---|
| `resolve_airports(query)` | Fuzzy geography → airport codes. "New England" → the regional set; "LA airport" → LAX, flagging BUR / LGB / ONT as alternates |
| `score_airport(code)` | Full score with all components |
| `rank_airports(codes)` | Ordered list with scores |
| `compare_airports(codes)` | Side-by-side component breakdown |
| `route_profile(code)` | Long-haul share, international mix, top routes |
| `current_conditions(code)` | FAA NAS Status live feed |

---

## Rationale

### Why a tool-calling loop rather than a router

The assignment requires **conversational follow-up**. A router fails on *"and what about
the second one?"* — there is no intent class for a reference to prior context. A
tool-calling loop handles it natively: the conversation history is already in context, and
the model simply calls the same tool with a different argument.

### Why the tool set is small

Six tools cover all four of the assignment's sample questions. A larger surface increases
mis-selection and makes behaviour harder to reason about without adding capability.

### `resolve_airports` is the load-bearing tool

It is what makes "New England", "Santa Ana", and "the LA airports" work at all. It is also
where the language model contributes genuine value: **fuzzy human geography is precisely
what deterministic code handles badly and an LLM handles well**. The division of labour is
therefore natural rather than contrived — the model interprets language, the code computes
numbers.

It earns its keep twice: it also absorbs mangled speech-to-text input from the voice
interface (see ADR-0008).

---

## The hard boundary

**Tools return numbers and structured components. The model composes prose from them.**

The model never computes, never estimates, and never fills a gap with a plausible figure.
Where a tool returns null, the agent reports the data as missing rather than inferring it.

This is the mechanism by which the assignment's "deterministic scoring, not only LLM output"
requirement holds by construction: the arithmetic lives entirely in tested code, and the
model's contribution is language.

---

## Consequences

- Scoring logic is unit-testable independently of the model.
- The same question yields the same numbers regardless of model, provider, or temperature —
  only the wording varies.
- Model mis-selection of tools becomes the main failure mode, mitigated by the small tool
  surface and by clear tool descriptions.

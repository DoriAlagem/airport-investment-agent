# ADR-0017: The interface exists to make determinism visible

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extended by:** [ADR-0024](0024-response-style.md) — what the prose says versus what the card shows
- **Amended by:** [ADR-0021](0021-visual-language.md) — visual language taken from the client's site
- **Extends:** [ADR-0008](0008-stack-and-interface.md)

---

## Context

ADR-0008 chose the stack — FastAPI and a single vanilla HTML page — but said
nothing about what the page should show. Treated as "a chat window", it would
have been a text box that prints model output, which is precisely the artefact
the assignment's "deterministic scoring, not only LLM output" requirement exists
to distinguish this from.

A reviewer reading a fluent paragraph of numbers has no way to tell whether the
figures came from a scoring engine or from the model's imagination. **That
distinction is the entire product, and prose cannot demonstrate it.**

---

## Decision

The interface is designed around one job: showing that every number came from a
deterministic tool call.

### 1. Evidence cards, not raw JSON

Each answer renders the tool results as structured cards beneath the prose:

- `score_airport` — hero score, status badges, the three components as
  percentile bars with their raw values, and the arithmetic spelled out:
  `congestion 47.7 × growth ×1.05 = 50.2`.
- `rank_airports` — grouped by tier with a bar per airport, because a single
  merged ranking would misrepresent within-tier percentiles (ADR-0012).
- `compare_airports` — a KPI row plus per-metric bars for each airport.
- `route_profile` — long-haul stat tiles, passenger and cargo separate.

The reader can check the narrative against the numbers without trusting either.

### 2. A full trace is always one click away

Under every answer: *"analysis — N deterministic tool calls"*, expanding to each
call, its arguments, and its complete JSON result. Not a debug affordance — the
proof.

### 3. Status colour never carries meaning alone

Every badge ships a coloured dot **and** a word ("Terminal-limited", "High
confidence"), so meaning survives colourblindness, greyscale printing and
forced-colours mode. The categorical palette was checked with a validator rather
than by eye: the blue/orange pair used for two-airport comparisons passes
lightness, chroma, CVD separation, normal-vision separation and contrast in both
light and dark modes.

### 4. Bar length and percentile are separate quantities

In a cross-tier comparison the bar shows relative magnitude *between the two
airports*; the percentile describes an airport against *its own tier*. An early
version labelled the former as the latter — rendering "LAX load factor 100th"
when it meant "100% of the larger of the two". That is the exact confusion the
tier system exists to prevent, reintroduced in the presentation layer. They are
now separate parameters and a comparison prints no percentile at all.

### 5. The data window travels with the answer, not the chrome

An earlier version pinned both windows permanently in the header. That was
dropped for a cleaner landing page, and the requirement is met a better way:
**every tool result carries its own `data_window`, and the agent states it in
the answer** ("congestion and delay cover January to December 2025, while growth
spans 2023 to 2025").

This is stronger than a header chip, not weaker. The two sources cover different
periods (ADR-0013), so a single global label was always an approximation — an
answer about growth and an answer about congestion do not rest on the same
months. Per-answer disclosure states the window that actually applies, and it
travels with the text if it is copied elsewhere.

The requirement from ADR-0005 — that a stale snapshot must never look current —
is therefore satisfied by ADR-0010's computed metadata rather than by page
furniture.

---

## Rationale

The requirement is not "have a chat interface" — it is to show that the ranking
is computed rather than generated. **Every element above is a way of proving
that claim to someone who does not trust it**, which is the correct assumption
about a reviewer.

The alternative, a plain chat window, would have been faster to build and would
have made the strongest part of the system invisible.

---

## Consequences

- The page is larger than a minimal chat: roughly 30 KB with a small markdown
  renderer and four card renderers. Still one file, no build step, no CDN.
- Card renderers are coupled to tool output shapes. A tool that changes its
  payload needs its renderer updated; unknown tools fall back to the raw trace,
  so nothing breaks silently.
- Rendering was verified by screenshotting the real page in both themes rather
  than by reading the code. That caught three defects invisible in source: an
  infinite loop in the markdown renderer on malformed tables, an ordinal bug
  ("32th"), and the mislabelled comparison bars above.

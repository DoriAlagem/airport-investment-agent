# ADR-0024: The prose carries judgement; the card carries the numbers

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extends:** [ADR-0007](0007-agent-architecture.md), [ADR-0017](0017-interface-makes-determinism-visible.md)

---

## Context

Answers were running 150–200 words and reading like generated reports: every
component, every percentile, every raw value, confidence and growth multiplier,
recited for each airport in turn.

The cause was not a missing instruction to be brief. **The system prompt
demanded the length.** It carried four unconditional rules — always state
confidence, always name the peer group, always state the data window, always
pass on caveats. Asked about five New England airports, the model wrote twenty
clauses. It was obeying instructions.

The second cause was duplication with the interface. ADR-0017 renders an
evidence card under every answer showing all three components with percentiles,
raw values, badges and the arithmetic. Prose repeating those figures says
everything twice: once in a sentence the reader must parse, once in a table they
can scan.

---

## Decision

**Two to four sentences. Lead with the answer. Let the card carry the detail.**

The division of labour:

| | Carries |
|---|---|
| **Card** (rendered from tool output, model cannot alter it) | Every component, percentile, raw value, badge, arithmetic |
| **Prose** (model) | What it means and what follows — the part a table cannot do |

### The four "always" rules became conditions

They were not deleted; they were made contingent on changing the reader's
conclusion. Confidence is stated when it is medium or low, with what is missing.
Caveats when material — 40% cargo matters, 3% does not. The data window once,
not per airport.

### Brevity never costs the answer itself

Shortening over-corrected on the first pass: the New England answer dropped the
constraint type and contained no figures at all. Three things are therefore
mandatory regardless of length:

1. **At least one figure.** A judgement with no number is an opinion.
2. **The constraint type when the question names a kind of work.** "Candidates
   for *terminal* expansion" is answered by terminal-limited vs runway-limited.
   An airport constrained by its runways is not a candidate however congested,
   and omitting this answers a different, easier question.
3. **A caveat that changes the reading of a figure just given** — the 2.4%
   long-haul share at Anchorage is meaningless without the sentence saying
   cargo is 55% of departures.

### Worked examples, not adjectives

The prompt carries a good answer and a bad one, labelled. "Be concise" is an
adjective and models negotiate with adjectives; a demonstrated voice is copied.

### The answer still stands alone

An API consumer or a voice listener sees no card. Standing alone means a clear
conclusion with its reason — not a recital of every figure.

---

## Result

| Question | Before | After |
|---|---|---|
| New England | ~150 words | 72 |
| Anchorage long-haul | ~90 words | 52 |
| LA vs Santa Ana | ~160 words | 89 |

All three still carry what they must: the terminal-limited finding, the cargo
caveat, the cross-tier warning and the confidence gap.

---

## Consequences

- Follow-ups are explicitly shorter than first answers. "Why that one?" wants
  three sentences about that airport, not the original answer again.
- Style now depends on the card existing. If the interface stopped rendering
  evidence, the prose would be too sparse — the two were designed together and
  should change together.
- Nothing here touches what the model may claim. The boundary of ADR-0007 is
  unchanged: tools produce numbers, the model produces sentences.

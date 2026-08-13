# ADR-0018: A small model, a fallback chain, and retry as a first-class path

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extends:** [ADR-0008](0008-stack-and-interface.md)

---

## Context

ADR-0008 chose Gemini behind a thin adapter and deferred the specific model. Free
-tier reality settled the rest, and none of it was foreseeable on paper:

- `gemini-2.0-flash` returns 404 — retired.
- `gemini-2.5-flash-lite` is closed to new API keys.
- The free tier allows **5 requests per minute** on some models, and a single
  question costs one request per tool round — six or more.
- Models intermittently return `UNAVAILABLE` under load, unrelated to quota.

A naive one-model client fails on all four.

---

## Decision

**Primary model: `gemini-3.5-flash-lite`.**
**Fallback chain: `gemini-3.1-flash-lite` → `gemini-3.6-flash` → `gemini-2.5-flash`.**

Retry policy:

| Condition | Response |
|---|---|
| `RESOURCE_EXHAUSTED` | Sleep for the delay the API itself states, then retry |
| `UNAVAILABLE` / `INTERNAL` / `DEADLINE_EXCEEDED` | Short backoff, then retry, then move down the chain |
| Anything else | Fail immediately with the message |

Up to three attempts per model before moving on. The model that actually served
a request is reported to the interface.

---

## Rationale

### Why a small model is not a compromise

The model does exactly one thing: choose a tool, fill its arguments, and narrate
the result. **It performs no arithmetic** (ADR-0007). Every figure comes from
tested Python against a fixed snapshot.

So model size cannot affect the accuracy of any number — only the fluency of the
sentence around it. A larger model would cost more requests against a per-minute
quota to produce identical figures. Choosing the small model is the correct
engineering decision here, not a budget concession.

This is the same property that makes the provider swappable in one file:
**changing the model cannot change the answer, only the wording.**

### Why retry is a normal path, not error handling

At five requests per minute against six-plus tool rounds, hitting the quota is
the *expected* case, not an exception. The API states how long to wait; waiting
is the correct response. Failing the user's question because a free tier is
doing its job would be a bug in our client.

### Why a chain rather than one model

Model availability on free tiers is not stable — two of the four models
originally tried were retired or closed to new keys within the build. A demo
that dies because one endpoint is momentarily busy is worse than one that
quietly answers on a sibling model, and since the models are interchangeable for
this workload, falling through costs nothing.

---

## Consequences

- Answers can be slow when the quota is exhausted: the client waits rather than
  failing. Acceptable for a demonstration; a paid tier removes it.
- The active model is surfaced per response, so behaviour differences are
  attributable rather than mysterious.
- Model IDs will rot. The chain is a single list at the top of `llm.py`, and the
  failure mode is a clear error naming the status and message.
- Provider comparison remains cheap: replacing `llm.py` swaps vendor entirely,
  and no number in the system moves.

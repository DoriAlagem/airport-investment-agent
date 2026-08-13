# ADR-0008: Stack and interface — Python core, FastAPI + vanilla JS chat, Gemini behind an adapter, voice as an edge shell

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0016](0016-voice-to-voice-and-multilingual-input.md) — voice-to-voice replaces the browser Web Speech shell; [ADR-0017](0017-interface-makes-determinism-visible.md) — interface design principles; [ADR-0018](0018-model-selection-and-fallback.md) — model selection and fallback
- **Follows:** [ADR-0007](0007-agent-architecture.md)

---

## Decision

| Layer | Choice |
|---|---|
| Data pipeline & scoring | Python (pandas) |
| API / chat backend | FastAPI |
| Chat UI | Single vanilla HTML/JS page |
| Model provider | Google Gemini free tier, behind a thin adapter |
| Voice (bonus) | Browser Web Speech API |

---

## Rationale

### Why FastAPI + vanilla JS rather than Streamlit

Streamlit would produce a working chat in roughly thirty lines and is the faster path in
isolation. **Voice is the deciding factor.** The Web Speech API is browser JavaScript; in
Streamlit it must be smuggled in through a custom HTML component, and returning the
transcript into Python is fiddly enough to consume an afternoon. On a plain HTML page it is
a `<script>` tag.

Secondary benefits: response streaming is straightforward, and the result presents as a
product rather than a data-science demo.

**Fallback rule:** if the data pipeline overruns, drop to Streamlit *and* cut voice. Do not
attempt both under time pressure.

### Why Gemini rather than Groq

The system asks exactly one thing of the model: select the correct tool, populate its
arguments, and keep doing so across multi-turn follow-ups. No arithmetic, no long-form
generation. **Tool-calling reliability is therefore the only capability that matters.**

Groq's advantage is inference speed, but speed is not the bottleneck — tools query a local
database in milliseconds, and the difference between a 400 ms and 900 ms reply is not
material to this application.

Function calling is a first-class, well-tuned feature of Gemini. Open-weight models served
through Groq support tool calling, but are generally more prone to tool mis-selection,
malformed arguments, and losing the thread on context-dependent follow-ups such as *"and
what about the second one?"* — which is precisely the required behaviour.

**This is a judgment call, not a measured result**, and is held loosely. The adapter makes
the provider a one-file swap. The plan is to build against Gemini and then re-run the same
five benchmark questions against Groq; if Groq holds up, take the speed. That comparison is
itself reportable in the design document — it demonstrates a measured choice rather than an
assumed one.

Because the model performs no arithmetic (ADR-0007), **changing provider cannot change any
number the system produces** — only the wording.

### Voice is an edge shell, not an architectural component

```
🎤 → transcript → [existing chat pipeline, unchanged] → answer text → 🔊
```

Speech-to-text sits in front of the pipeline, text-to-speech behind it. The agent, tools,
and scoring are unaware voice exists.

**Realtime speech-to-speech was considered and rejected for this build.** Estimated 3–5
hours if cooperative and potentially the entire day if not: it replaces request/response
with a streaming WebSocket/WebRTC session, requires audio buffering and interruption
handling, and — critically — requires tool calling to work *inside* an audio stream, where
failures are slow to diagnose. Free-tier availability and rate limits for realtime voice are
also tighter and unverified.

**Governing rule: the bonus is never built before the required parts are finished.** A
polished realtime voice demo attached to a half-built scoring engine presents worse than a
solid engine with a simple microphone button. Realtime remains a documented stretch goal.

### Known voice failure mode

Speech recognition reliably mangles airport codes ("SFO" → "S F O", "Essef Oh"). Mitigated
by a transcript normalisation pass before the agent, and by `resolve_airports` already being
tolerant of fuzzy input (ADR-0007).

---

## Consequences

- Two deliverable tiers: required (pipeline, scoring, chat) and bonus (voice), with an
  explicit cut order under time pressure.
- Provider is swappable in one file; a provider comparison is planned and reportable.

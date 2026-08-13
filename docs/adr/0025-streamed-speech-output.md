# ADR-0025: Speech output is streamed TTS, with the browser voice as fallback

- **Status:** Superseded by [ADR-0028](0028-speech-output-returns-to-the-browser-voice.md)
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Reverted by:** [ADR-0028](0028-speech-output-returns-to-the-browser-voice.md) — the slice bookkeeping caused every voice fault; the browser voice speaks again
- **Amends:** [ADR-0016](0016-voice-to-voice-and-multilingual-input.md)

---

## Context

ADR-0016 moved speech output into the browser after measuring the first TTS
attempt at **10–30 s per reply against a ~10 request/minute quota** — it failed
more often than it worked. The browser's own voice is instant and unmetered.

It is, however, plainly synthetic, and Hebrew has exactly one system voice. The
question was whether a dedicated provider could give a better voice without
reintroducing the wait.

**Hebrew is the binding constraint.** Most low-latency TTS is English-first.

---

## Decision

**OpenAI `gpt-4o-mini-tts`, streamed. The browser voice remains the fallback.**

| | |
|---|---|
| Voice | `coral` — multilingual, so one voice serves both languages |
| Format | raw PCM, so the stream can be cut at any byte boundary |
| First audio | **~0.5 s** |
| Cost | ~$0.015/min of audio — about **20 cents an hour** of real use |

### Streaming is the whole point

Synthesis time scales with the length of the reply; time to the *first chunk*
does not. Measured on the same sentence:

| | First audio | Total |
|---|---|---|
| Buffered | 2.35 s | 3.71 s |
| **Streamed** (`stream_format: "audio"`) | **0.56 s** | 1.50 s |

Without `stream_format` the endpoint buffers before sending — same audio, four
times later. Each PCM slice is given its own WAV header so chunks stay
independently decodable, and the browser schedules them back to back as they
land.

### The voice is not chosen per language

OpenAI's voices are multilingual, so there is nothing to select from the script
of the answer and nothing to keep in sync when the agent switches language.

### The browser stays as fallback, not as dead code

`/api/speak/stream` emits either audio chunks or `{"provider": "browser"}`. The
page reads the answer with its own voice when no key is configured **or when
the call fails mid-stream**, which is why the signal is in-band rather than an
HTTP status — a status code cannot be changed once streaming has begun.

A finished answer is never lost to a speech failure.

---

## Consequences

- Speech is a paid dependency, unlike the rest of the free-tier stack. At ~20
  cents an hour this is not a meaningful constraint, and it removes the quota
  failures that made the earlier attempt unusable.
- The provider sits behind one function in `speech.py`, the same seam that
  transcription uses (ADR-0016). The agent, tools and scoring remain unaware
  speech exists.
- Playback moved from an `<audio>` element to Web Audio. Autoplay policy blocks
  an element whose `play()` is called seconds after the click, and priming it
  with a silent clip proved unreliable; an AudioContext resumed during the
  gesture stays unlocked for the life of the page.

# ADR-0016: Voice-to-voice — Whisper via Groq listens, the browser speaks

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0020](0020-hands-free-conversation.md) — hands-free conversation and barge-in; [ADR-0025](0025-streamed-speech-output.md) — streamed TTS, since reverted; [ADR-0026](0026-only-questions-reach-the-agent.md) — what reaches the agent; [ADR-0028](0028-speech-output-returns-to-the-browser-voice.md) — restores the browser voice
- **Extends:** [ADR-0008](0008-stack-and-interface.md)

---

## Context

ADR-0008 specified voice as a thin shell at the edges, built on the browser Web
Speech API, and treated it as a bonus to be cut first. Two things changed that:

1. The requirement grew from dictation to **voice-to-voice** — speak a question,
   hear the answer.
2. The target language is **Hebrew**, which the browser API handles poorly and
   which raises questions the English-only design never had to answer.

The architectural principle from ADR-0008 is unchanged and is what makes this
cheap: audio becomes text before the agent sees it, and text becomes audio after
the agent is done. **The agent, the tools and the scoring are unaware voice
exists.** Nothing in the deterministic core was touched to add a second language.

---

## Decision

```
🎤 → 16 kHz mono WAV (browser) → Whisper (Groq) → text
                                                   ↓
                            [ existing agent + tools + scoring, unchanged ]
                                                   ↓
   🔊 ← browser speech synthesis ← spoken summary ← answer text
```

| Stage | Provider | Why |
|---|---|---|
| Listening | **Groq `whisper-large-v3`**, Gemini fallback | Measurably better Hebrew (below) |
| Reasoning | Gemini | Unchanged |
| Speaking | **Browser speech synthesis**, Gemini TTS on demand | Instant and unmetered; Gemini costs 10-30s against a small quota (below). Groq serves no speech-output model at all |

---

## Why Whisper listens

Both were run on the same Hebrew sentence — *"Which airports in New England are
suitable for terminal expansion"*:

| Listener | Transcript |
|---|---|
| Groq / Whisper | אילו שדות תעופה ב**ניוונגלנד** מתאימים להרחבת טרמינל |
| Gemini | איזה שדות תעופה ב**ארצות הברית** נכללים להרחבת טרמינל |

Whisper is essentially correct — it only runs "New England" into one word, a
transcription artefact the agent recovered from unaided.

**Gemini silently replaced "New England" with "the United States."** Not a
garbled word: a fluent, plausible, wrong region. The agent would have ranked the
entire country and nothing in the output would have hinted that the question had
been altered. It also changed "suitable" to "included".

That is the exact failure this project has been designed against throughout —
confident text with no signal that it is wrong — appearing in a new layer. It
settled the choice.

**Groq serves only two models relevant here** (`whisper-large-v3` and
`whisper-large-v3-turbo`), verified against the live account rather than assumed.
Both are recognition-only: Whisper cannot generate audio, so speech output must
come from elsewhere regardless.

The listener is a seam, not a hard dependency: with no `GROQ_API_KEY` the system
falls back to Gemini and still runs on one key. A Groq failure at request time
degrades to Gemini rather than losing the question.

---

## Design consequences

### Language is auto-detected; the reply matches the question

No language selector. Whisper detects the language; the system prompt instructs
the model to answer in the language it was asked in. English and Hebrew work
identically — Hebrew was simply the harder case to get right.

**Tool arguments stay English.** A Hebrew speaker asking about ניו אינגלנד
causes `resolve_airports("New England")` — the model translates place names when
calling tools, because the geography tables are English. Airport codes and
numbers stay in Latin script in every language.

### Audio is encoded to WAV in the browser, not MediaRecorder

MediaRecorder produces WebM/Opus, which Groq does not accept. The alternatives
were transcoding server-side (an ffmpeg dependency for one feature) or encoding
client-side. The browser captures raw PCM and writes a 16 kHz mono WAV directly
— roughly forty lines, and it removes the container question entirely.

Verified end to end in a real browser with a fake microphone device, not only
against the API.

### Speech output is the browser, not the API — measured, not assumed

The first build synthesised every reply through Gemini TTS and the wait was
unusable. Profiling located it precisely, and not where expected:

| Stage | Time |
|---|---|
| Agent: 3 tool rounds, end to end | **3.5 s** |
| Gemini TTS synthesis | **10–30 s**, plus retries |

**The agent was never the bottleneck.** Speech synthesis was — and it carries
its own ~10-request/minute quota, separate from the chat model's, so under any
real use it fails and each retry sleeps ~27 seconds.

Chrome ships a Hebrew voice (כרמית) and an English one. Browser synthesis is
**instant, unmetered and offline**. Its timbre is plainer than Gemini's, and
that trade is not close: **half a minute of silence is a worse answer than a
plainer voice that starts immediately.**

Speech output therefore runs in the browser, full stop. A "higher-quality
voice" control was built and then removed: on the free tier the quota is reached
within a few answers, so the control failed more often than it worked, and a
button that usually errors is worse than no button.

`/api/speak` is retained server-side — the synthesis code, its retry policy and
the PCM-to-WAV wrapping are all sound, and on a paid tier the control is one
small addition. The interface simply does not call it.

End-to-end voice-to-voice, measured: **~5.5 seconds** from the end of speech to
a spoken answer, against roughly thirty before.

### The spoken reply never blocks the written one

Transcription, agent rounds and synthesis in one blocking call once exceeded
**five minutes**. The written answer returns as soon as it exists; speech
follows independently. A finished answer must never wait on its own narration.

### Text direction follows the answer, not the question

An early version set right-to-left from the language of the *transcript*, which
rendered English answers to Hebrew questions right-aligned with misplaced
punctuation. Direction is now detected from the text actually being displayed.
Evidence cards stay left-to-right inside an RTL answer: they are airport codes
and numbers, which read left-to-right in every language.

---

## Consequences

- Two API keys in the deployed configuration, one of which is optional.
- The system speaks and understands Hebrew without a single change to the
  scoring, the tools, or the agent — which is the ADR-0008 edge-shell principle
  paying off rather than being asserted.
- Speech quality is traded for latency and reliability. The better voice exists
  in the codebase but is not exposed, because free-tier quota makes it fail more
  often than it succeeds.
- Realtime speech-to-speech (a live streaming session) remains out of scope for
  the reasons in ADR-0008. What ships is voice-to-voice by round trip, which
  delivers the user-visible behaviour without putting tool calling inside an
  audio stream.

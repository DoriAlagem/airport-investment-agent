# ADR-0028: Speech output returns to the browser voice, and nothing may hang

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Reverts:** [ADR-0025](0025-streamed-speech-output.md) — streamed OpenAI TTS
- **Restores:** [ADR-0016](0016-voice-to-voice-and-multilingual-input.md) — the browser speaks

---

## Context

ADR-0025 replaced the browser's voice with streamed OpenAI TTS for its markedly
better Hebrew, cutting each reply into ~20 PCM slices so playback could start at
~0.5 s instead of waiting for the whole file.

Every voice fault in the following session came from those slices, and none from
the model:

- `decodeAudioData` is asynchronous and **its promises do not resolve in call
  order**, but the timeline position was assigned inside `.then` — so half a
  second of speech could be scheduled before the half second preceding it.
- The end of an utterance was inferred from a counter of slices still
  *decoding*, which reached zero long before the audio had *played*. The
  utterance therefore "ended" early and then once per slice that finished —
  **29 endings for one answer**, each reopening the microphone mid-sentence.
- When that counter never reached zero, the utterance never ended at all: the
  microphone never reopened and the conversation was dead after one question,
  with nothing in any log.
- Because `speaking` went false almost immediately, **barge-in was dead** for
  the rest of every answer.

Each was fixed in turn, and each fix was correct. The pattern is the point: a
class of bug that keeps producing new instances is a design problem, not a
sequence of coding errors.

Measured alternatives, on the same replies:

| Approach | To first word | Ordering | Ending |
|---|---|---|---|
| Streamed OpenAI (ADR-0025) | 0.5 s | must be reconstructed | must be inferred |
| Single-file OpenAI | 2.5–3.5 s | n/a | one `onended` |
| Browser voice | instant | n/a | one `onend` |

The single-file measurement is on a fresh API key. On the exhausted one it was
5–6 s with a 16 s outlier — **latency there was account throttling, not text
length**: 180 characters and 420 characters had the same median.

---

## Decision

### 1. The browser speaks

`say()` calls `speakLocally()`. One `speak()`, one `onend`, one `cancel()` to
interrupt. There is no ordering to reconstruct and no ending to infer, which
removes the entire class of fault above rather than fixing instances of it.

The cost is real and is accepted: macOS offers exactly **one** Hebrew voice,
`Carmit`, and it is concatenative rather than neural. Verified against the
actual 184-voice list on the development machine — a Hebrew answer selects
Carmit, an English one selects a preferred non-novelty voice, and the novelty
voices score −100 so a Hebrew reply can never land on one called Bubbles.

The server keeps `/api/speak` and `speech.synthesize()`: OpenAI single-file
synthesis, tested and working, reachable by one call in `say()`. It is retained
deliberately as the measured alternative for anyone who wants the better Hebrew
and can accept the wait.

### 2. Speech is unlocked during the click

Safari ignores `speechSynthesis.speak()` outside a user gesture, and a reply
arrives seconds after the click — so Safari heard the question, answered it, and
silently refused to say it aloud. A single silent utterance during the mic click
unlocks it for the life of the page, and also prompts Safari to enumerate its
voices, which it does not do until asked.

### 3. Barge-in opens the microphone without starting a turn

`listenWhileSpeaking()` calls `ensureMicrophone()`, not `startRecording()`. The
frame handler processes frames whenever `speaking` is true, so a turn was never
needed — and starting one flipped the orb to "Listening" in the middle of the
answer and captured the assistant's own voice.

### 4. Ending the conversation always works

`endConversation()` is its own function and aborts the in-flight request. It
used to be `mic.click()`, and `sendVoice()` disables the mic button while a
request is in flight — so a slow answer left **no way out of the conversation at
all**. An abort is the user's decision, so it removes the pending bubble rather
than writing a failure into the transcript.

### 5. A model call has a waiting budget

`RETRY_BUDGET_SECONDS = 20`. The API asks for a specific quota delay and the
retry loop obeyed it across four fallback models, which turned a one-word
greeting into a **179-second wait** with the interface stuck on "Thinking".
Past the budget the call stops waiting and says the models are rate-limited.
Measured after: 8.9 s and 11.8 s for the same questions, on the fallback model.

---

## Rationale

**Why not keep OpenAI as a single file.** It is genuinely better Hebrew and it
is tested. The deciding factor is what the feature is for: a live demo where a
silent or stuck assistant is a worse outcome than a plainly synthetic one, and
where the machine it runs on may not be this one. Reliability first, voice
second — recorded here so the choice can be defended, and reversed, on evidence.

**Why not another TTS vendor.** ElevenLabs, Azure and Google Cloud would all
plug into the same playback and capture code and inherit the same failures. The
measurements show synthesis was never the bottleneck.

---

## Consequences

- Hebrew output is Carmit: reliable, instant, and plainly synthetic.
- Barge-in and continuous conversation are unaffected and verified.
- Nothing in the interface can wait indefinitely: a rate-limited model now
  produces a message in ~20 s instead of a hang, and the user can always leave.
- The OpenAI path remains in the codebase, measured and documented, one line
  from being the default again.

# ADR-0020: Hands-free conversation — silence detection, barge-in, and a state you can see

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amended by:** [ADR-0027](0027-voice-detection-measured-not-assumed.md) — the detector recalibrated from measurements; [ADR-0026](0026-only-questions-reach-the-agent.md) — only a question reaches the agent
- **Extends:** [ADR-0016](0016-voice-to-voice-and-multilingual-input.md)

---

## Context

ADR-0016 delivered voice-to-voice, but each question cost two clicks: one to
start recording and one to stop. That is dictation with a speaker attached, not
a conversation.

The reference point is Gemini Live and ChatGPT voice mode: start once, then
talk. Three properties make those feel live — the microphone closes itself when
you stop talking, it reopens when the assistant finishes, and you can interrupt
mid-sentence.

---

## Decision

**Turn-based continuous conversation, with barge-in.** One control starts and
ends the whole session.

```
click 🎤 ──▶ listening ──(you stop talking)──▶ thinking ──▶ speaking ──┐
                 ▲                                                     │
                 └──────────── mic reopens automatically ◀─────────────┘
                        (or you interrupt, and it stops speaking)
```

### 1. Silence detection closes the microphone

Root-mean-square amplitude is measured per audio frame. After ~1.3 s below the
speech threshold, recording stops and the question is sent.

Thresholds are deliberately forgiving — cutting someone off mid-sentence is a
much worse failure than waiting an extra beat — and auto-stop requires a
minimum number of *speech* frames, not merely elapsed frames. An earlier version
counted total frames, so a cough armed the detector and the following silence
auto-sent a recording of nothing.

Verified against four cases: stops after speech, ignores a mid-sentence pause,
never fires on silence alone, ignores a cough.

### 2. Barge-in keeps the microphone open while the assistant talks

Sustained speech above a higher threshold cancels playback, and the interrupting
words become the next question.

This is only possible because the microphone is opened with
`echoCancellation` — without it the recorder hears our own synthesised voice and
the assistant interrupts itself. The barge threshold is set well above ordinary
speech detection: echo cancellation suppresses our voice but does not erase it,
and a false trigger cuts the assistant off for no reason.

### 3. An orb, because the state must be visible without a keyboard

A full-screen overlay shows one of three states — listening, thinking,
speaking — as an animated sphere of drifting gradient layers.

**It scales with live microphone amplitude**, so it responds to the speaker's
actual voice rather than animating on a timer. Each state also carries its own
motion, so the state reads without the label. The transcript appears beneath it,
because the chat log is behind the overlay and a mishearing must still be
visible.

In a hands-free session the single most important thing a user needs to know is
whether the microphone is open. A label alone does not carry that at a glance.

---

## Rationale

### Why not the Gemini Live API

True realtime — a bidirectional streaming session — was estimated at 3–5 hours
in ADR-0008 and rejected because tool calling has to work *inside* an audio
stream, where failures are slow to diagnose. That reasoning still holds.

What was built delivers the user-visible behaviour of a live conversation —
start once, talk, interrupt, keep talking — while every question still passes
through the same deterministic tool path as a typed one. The remaining
difference is that responses are not streamed: the assistant thinks silently
before speaking rather than beginning to answer as it composes.

### Why this was cheap

Because voice is an edge shell (ADR-0008), continuous conversation is entirely a
browser-side loop. **No change was needed to the agent, the tools, or the
scoring.** The whole feature is recording state, an amplitude threshold, and
what happens when a spoken reply ends.

---

## Consequences

- Barge-in quality depends on the browser's echo cancellation and on speaker
  volume. Headphones make it reliable; loud speakers may cause self-interruption.
  The thresholds are two constants at the top of the file.
- The orb overlay hides the chat log and its evidence cards while a conversation
  is running. Ending the conversation reveals the full transcript, scores and
  tool traces — nothing spoken is lost, only deferred.
- `hidden` on a flex container does not hide it — `display:flex` overrides it —
  so an invisible overlay silently swallowed every click on the page until
  `.stage[hidden] { display: none }` was added. Worth remembering: an element
  that is invisible is not necessarily gone.

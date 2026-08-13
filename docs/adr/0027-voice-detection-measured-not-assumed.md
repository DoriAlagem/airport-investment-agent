# ADR-0027: The voice detector is calibrated from measurements, and the microphone is always released

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Amends:** [ADR-0020](0020-hands-free-conversation.md)

---

## Context

ADR-0020 chose an adaptive speech detector over a fixed threshold, after a fixed
one proved unreachable on a quiet microphone. The adaptive version was never
measured on a real device either. When it finally was, it had not been adapting
at all.

Diagnostics were added to the page and posted to the server log — every
recording reporting its own levels. The first session gave this:

```
MIC {"event":"sent","seconds":27.5,"speechFrames":322,"frames":322,
     "peak":0.187,"noiseFloor":0,"speechBar":0.01,"rate":48000}
MIC {"event":"sent","seconds":28.1,"speechFrames":327,"frames":329, ...}
MIC {"event":"rejected","seconds":28.4,"speechFrames":0,"peak":0.0006, ...}
HEARD 'Lalalalalalala...'
HEARD 'The'
HEARD ''
```

Three facts, none of which had been guessed correctly:

**Sensitivity was never the problem.** Speech peaked at **0.10–0.25** against a
bar of 0.010. The suspicion that the bar was too high for this microphone —
which had motivated the previous round of work — was simply wrong.

**`noiseFloor` was 0 on every single recording.** The floor was an all-time
running minimum. A stream that has just opened delivers frames of true digital
silence, so the minimum went to zero on the first recording and, since it only
ever fell, stayed there for the life of the page. `noiseFloor * 3` was therefore
always 0, and the bar was always the fixed floor. **The adaptive detector was
never adaptive.**

**`speechFrames` equalled `frames`.** Every frame of every recording counted as
speech. With `autoGainControl: true` the browser lifts a quiet room until its
tone sits at ~0.012–0.016 — *above* the 0.012 ceiling the bar was clamped to. So
the pause was never detected, recording ran to the ~28 s cap every time, and
~28 seconds of mostly nothing went to Whisper. Whisper answered it the way it
answers nothing: `Lalalalalalala...`, `The`, `''`.

**And the buffer was never emptied between turns.** The microphone stays open
while the assistant talks — that is what makes barge-in possible — and every one
of those frames was appended to the capture buffer. When speech ended,
`finishedSpeaking()` flipped the state to listening and cleared nothing. So the
next clip sent for transcription was *the assistant's answer followed by the
user's question*. This log line is not the user speaking:

```
HEARD 'SFO, LAX, BOS, JFK, LGA, EWR, ANC, SNA, ORD, ATL.'
```

That is the assistant's own spoken answer, transcribed back and entered into the
conversation as a turn. It also explains the recordings that were already over
the cap before anyone spoke.

That is the whole user-visible fault. Speak, then wait half a minute, then be
told nothing was heard — or be answered as though you had read out a list of
airport codes.

Separately, and visible in the macOS menu bar: **the microphone stayed live
after the conversation ended.** `stopRecording()` returns early when not
recording, and it was the only place that stopped the media tracks, so ending
the conversation while the assistant was speaking or thinking released nothing.
Only a page reload cleared the indicator.

---

## Decision

### 1. The bar is adaptive between two limits, and both are load-bearing

```
speechBar = clamp(noiseFloor × 3, 0.010, 0.030)
```

- **The floor** (0.010) stops the bar collapsing onto room tone, which is what
  made silence look like speech in ADR-0020.
- **The ceiling** (0.030) stops the bar running away. Without it a recording
  that opens mid-word — after a barge-in — takes its "room" reading from the
  voice itself and lands at three times normal speech, silencing the speaker
  completely. Simulation against the measured levels caught this in the first
  version of this fix, before it shipped.
- The old ceiling was **0.012**, below where an AGC-lifted room actually sits.
  That single number is why every frame read as speech.

Frames below `DEAD_FRAME_RMS` (0.0002) are not counted as room: they are a
stream that has not started. This is what stops the floor collapsing to zero.

### 2. End-of-speech is judged relative to the utterance

A second bar answers a different question. The speech bar asks *is anyone
talking*; this one asks *have they stopped*:

```
quietBar = max(speechBar, peak × 0.18)
```

It has to be relative, because with gain control the room itself clears any
fixed bar. Against the measured levels, a pause after speech at 0.13 puts the
quiet bar at 0.023, comfortably above room tone at 0.016 — so the pause is seen.
`SILENCE_FRAMES` (~1.2 s) still protects a pause mid-sentence.

### 3. Nothing waits out a full recording of silence

If no frame has crossed the speech bar after 5 seconds, the recording stops and
says so. The cap drops from ~28 s to 20 s. The old behaviour — 28 seconds of
waiting before "I did not catch anything" — reads as a hung interface.

### 4. A turn starts empty

One `resetCapture()` clears the buffer and every counter, called when a
recording starts and when the assistant stops speaking with the microphone still
open. Barge-in keeps only the interrupting frames, as before.

### 5. The presence test is floored, not a plain multiple

Deciding whether a recording contains a voice at all has to separate a flat
lifted room (0.012–0.016) from a *quiet* speaker, and those are far closer
together than a room is from ordinary speech. A plain multiple of the bar failed
here twice in simulation — at 2× it demanded a peak of 0.060 and rejected a soft
voice outright, at 1.2× it still rejected one at 0.034. The test is
`peak >= max(0.020, speechBar)`: the bar is already three times the room, so the
absolute floor is what does the separating.

### 6. The microphone is released on every exit path

One `releaseMicrophone()`, safe to call twice, called when recording stops, when
the conversation ends **whatever state it is in**, when the microphone fails,
and when a new conversation is started. Holding the device open after the user
has visibly finished is a privacy fault, not an untidiness.

---

## Rationale

**Why simulate before shipping.** The fix was replayed as whole turns — the
assistant speaking, then the user — against synthetic frame sequences built from
the *measured* levels — normal speech, a quiet speaker,
starting mid-word, a pause mid-sentence, room tone alone, a dead stream, and a
floor already poisoned to zero. The first version passed the obvious cases and
silenced the speaker in the barge-in case. Eyeballing the code would not have
caught it; the previous three rounds of eyeballing did not.

**Why diagnostics are staying in.** `/api/diag` and the `MIC` log lines cost
nothing and are the only reason this was diagnosable at all. Three rounds of
plausible reasoning about this detector produced three wrong answers; one
session of measurement produced the right one.

---

## Consequences

- The assistant's own voice is no longer transcribed as the user's next turn.
- Recordings end on the pause, ~1.2 s after speech stops, instead of at a cap.
- Silence is reported in 5 s rather than 28.
- Whisper is no longer asked to transcribe 28 seconds of room tone, which
  removes most of the sign-off hallucinations ADR-0026 exists to catch. The two
  defences are independent on purpose.
- The microphone indicator goes out when the conversation ends.
- Every threshold here is calibrated to **one** microphone in **one** room. The
  diagnostics remain so the next room can be measured rather than guessed at.

# ADR-0026: Only a question reaches the agent, and a non-answer is not an answer

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extends:** [ADR-0016](0016-voice-to-voice-and-multilingual-input.md), [ADR-0020](0020-hands-free-conversation.md)

---

## Context

ADR-0020 made the microphone reopen automatically after every reply. That is
what the interface needed, and it is also what turned a harmless transcription
artefact into a self-sustaining fault.

Observed live, in one session:

```
ANALYST   ⚠ No speech detected. Try again, a little closer to the mic.
ANALYST   ⚠ No speech detected. Try again, a little closer to the mic.
YOU       the
ANALYST   נראה שהשאלה נקטעה. איזה שדה תעופה תרצו לבדוק?
YOU       sound
ANALYST   נראה שהשאלה נקטעה. האם אתם מתכוונים לאזור סיאטל ובאגט' סאונד?
ANALYST   ⚠ No speech detected. Try again, a little closer to the mic.
```

Nobody said "the" or "sound". Three separate faults compose here.

**1. A failure to hear was rendered as something the analyst said.** The page
creates the assistant's bubble before the request and fills it with whatever
comes back, so `{"error": …}` — including "no speech detected", which is not an
error at all — was written into the transcript, attributed to the analyst,
permanently, with no user turn above it. Three of them stacked in one screen.

**2. Single-word noise passed every gate.** The client gate is energy-based: a
loud-enough frame count over a calibrated floor (ADR-0020). A keystroke clears
it. So does the assistant's own voice leaking past echo cancellation — the
microphone is deliberately open while it speaks, so barge-in works. Whisper then
does what it always does with a fragment: it returns a plausible word. The
server's second line of defence was an exact-match list of about ten phrases.
"the" and "sound" are not on it, and no list of phrases ever will be — the space
of things a 300 ms burst of noise can be transcribed as is not enumerable.

Exact matching failed a second time, and more expensively, on the phrase it was
built for. Whisper's training was full of captioned video, so what it produces
from silence is a video sign-off. The list held `"thank you"` and
`"thanks for watching"`; what actually arrived was:

```
YOU       Thank you for watching! Please subscribe to my channel!
ANALYST   You're welcome. Let me know which US airports you would like to analyze.
```

Nobody said it. It passed — it is five words, so the word-count gate lets it by,
and it matched no list entry exactly. Worse than the wasted turn: the reply was
in **English**, in a conversation being held in Hebrew, and it was long enough to
clear `DECISIVE_ENGLISH_CHARS`, so the conversation language flipped permanently
(ADR-0016). One phantom turn changed the language of everything after it.

**3. The junk turn then poisoned the conversation.** This is the part that
matters. A wasted round trip is a cost; a wasted round trip that *enters the
history* is a fault, because the next turn is answered against it. "the"
produced "which airport did you mean?", which framed everything after it — by
the second fragment the agent was guessing at Puget Sound. Under ADR-0020 the
microphone reopens each time, so the loop feeds itself with no user input at
all.

A fourth, quieter fault sat underneath: the client already had a `hint()` line
for exactly this, but reopening the microphone repaints that line from the
state machine. The explanation was written and erased in the same frame. The
user only ever saw the red boxes.

---

## Decision

### 1. Sign-offs are matched as patterns, and judged by what is left

The artefact family — thanking, subscribing, saying goodbye, crediting a caption
service — is small and closed. Its **wordings are not**, so it is matched by
pattern rather than by string.

A transcript is an artefact when **nothing remains once the sign-offs are
removed**. That test is what keeps real turns safe: "thanks, and what about
Boston?" still has a question in it after the strip, and survives. So does
"תודה, ומה לגבי בוסטון".

### 2. A single word is not a question unless it earns its place

Every artefact in this class shares one shape: **one word**. Someone asking this
interface something says more than one. So:

- **Two or more words always pass.** The gate must never swallow a real
  question, however terse — "Anchorage long-haul?" goes straight through. Only
  the single-word case is guarded, because only the single-word case is where
  the evidence is.
- **One word passes** only if it answers what was just asked (`yes`, `why`,
  `again`, `כן`, `למה`, and a greeting, per the rule below) or names an airport.

The airport half of that vocabulary is **built from the snapshot**, not written
in the module: every code, plus city names of four letters or more. A new
airport in the data is understood without editing any code.

City names, not full airport names. Taking every word of every name back would
readmit precisely the generic noise this exists to stop — "field",
"international", and, exactly, "sound", which is a real place in the snapshot
and also what the assistant's own voice was transcribed as. Those words are
listed and excluded.

Greetings still pass, consistent with ADR-0016: "hello" and "שלום" are things a
person actually says to open a conversation.

### 3. "I did not hear you" is not an error, and is not an answer

The endpoint returns `unheard` rather than `error`. The interface removes the
empty assistant bubble, puts the reason on the hint line, and reopens the
microphone. Nothing enters the transcript, because nothing was said and nothing
was answered.

The reason includes what was actually heard — *I heard only "sound"* — for the
same reason the transcript of a real turn is displayed: a mishearing must be
visible, not silent.

### 4. A reason survives the state change that follows it

Hint text set before the microphone reopens is carried through the next state
repaint instead of being overwritten by it.

---

## Rationale

**Why the word count and not a confidence score.** Whisper's `avg_logprob` and
`no_speech_prob` are available and would be the obvious instrument. They were
not used: thresholding them is another calibration with no ground truth here,
and the failing cases are not low-confidence — Whisper is entirely confident
that a keystroke is "the". Word count needs no calibration and its failure mode
is legible.

**Why not just make the energy gate stricter.** That is the ADR-0020 tradeoff,
and it was already tuned against a real microphone in a real room. Raising the
bar to exclude a keystroke starts excluding a quiet speaker, which is the fault
this project spent a day fixing. The gates are deliberately different in kind:
one asks *was there sound*, the other asks *was it a question*.

**Why the vocabulary comes from the store.** The alternative is a hand-written
list of airport words in `speech.py`, which is a second place for the universe
to be defined and a guaranteed source of drift (ADR-0009 put that definition in
one place for the same reason).

**What this costs.** A genuine one-word utterance that is neither an airport nor
a listed conversational word is rejected. The user is told exactly what was
heard and can repeat it. That is a strictly better outcome than the current one,
where the fragment is answered and the answer contaminates the conversation.

---

## Consequences

- Noise cannot start a conversation, and cannot continue one.
- The transcript contains turns, not diagnostics.
- `speech.is_substantive` is pure and takes its vocabulary as an argument, so it
  is tested without a database (five tests in `tests/test_speech.py`).
- The single-word list is bilingual and hand-written, so it will need additions
  as real usage exposes them. This is a known, bounded maintenance cost, and the
  failure mode when a word is missing is a visible "I heard only X", not a
  wrong answer.

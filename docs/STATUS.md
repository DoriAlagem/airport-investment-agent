# Project status — handoff

Last updated: 2026-08-12, end of the working session.

---

## What this is

**AI.I — Airport Investment Intelligence.** An agent that ranks US airports by
**suppressed demand** — traffic that exists today but cannot be served because
the facility is too small — to find where renovation would pay off.

**Read [docs/adr/](adr/) first.** Twenty-eight ADRs record every design decision
with its reasoning, including the ones that turned out wrong and why.

---

## State: complete except the design document

**83 tests passing.** Server: `chat gemini-3.5-flash-lite`, `voice groq/whisper-large-v3`,
speech via the browser voice with OpenAI as fallback (ADR-0028).

| Part | State |
|---|---|
| Data acquisition (BTS, OurAirports, FAA) | ✅ |
| ETL → SQLite snapshot | ✅ 396 airports scored |
| Deterministic scoring | ✅ 55 tests |
| Agent + 6 tools | ✅ |
| Chat interface | ✅ |
| Voice (bonus) | ✅ continuous EN + HE, barge-in, orb; browser voice with OpenAI fallback |
| Answer evaluation harness | ✅ 7/7 |
| **Design document** | ❌ **the only outstanding deliverable** |
| README | ❌ |

The design document must cover: **scoring methodology, key tradeoffs, where and
how AI is used.** All the material exists in the ADRs; it needs assembling into
one readable piece.

---

## Running it

```bash
# chat interface (--reload picks up code changes; without it you will test stale code)
PYTHONPATH=src python3 -m uvicorn airport_intel.web:app --port 8000 --reload --reload-dir src

python3 -m pytest tests/ -q                      # 83 tests, no API calls
PYTHONPATH=src python3 scripts/evaluate.py       # answer quality, uses live API

PYTHONPATH=src python3 -m airport_intel.ingest.download   # ~35 min, already done
PYTHONPATH=src python3 -m airport_intel.etl.build         # ~2 min
```

Keys live in `.env` (gitignored):

| Key | Job | Limit that bites |
|---|---|---|
| `GEMINI_API_KEY` | reasoning (text answers) | free tier; retries + model fallback chain |
| `GROQ_API_KEY` | Whisper transcription | **20 requests/minute** — waits rather than degrading |
| `OPENAI_API_KEY` | `gpt-4o-mini-tts` speech out | paid, ~20 cents/hour of use |

**All three were pasted into a chat transcript and must be rotated before submission.**

---

## How the scoring works, in one screen

```
congestion = 0.40 x peak saturation   (median hour / peak hour - is the day flat?)
           + 0.30 x fullness          (passengers / seats - is demand real?)
           + 0.30 x capacity delay    (NAS delay minutes per departure)
                                       ... each as a percentile WITHIN its hub tier

final      = congestion x clamp(growth, 0.75, 1.25)     3-year passenger CAGR

alongside  constraint type = peak movements / EFFECTIVE runways
                             runway-limited -> a terminal will not help
                             terminal-limited -> expansion is actionable
```

Universe: US airports with ≥10,000 annual passengers (the federal "primary
airport" definition). Tiers: FAA large/medium/small/non-hub.

Current large-hub top five: **EWR 88.3, LGA 84.7, ATL 81.0, MCO 80.7, BOS 79.6.**
Newark and LaGuardia leading is the strongest external check available — nothing
was tuned to produce it.

---

## Layout

```
src/airport_intel/
  scoring.py        THE DETERMINISTIC CORE - pure functions, no I/O
  tools.py          the six tools the model may call
  agent.py          tool-calling loop
  llm.py            provider adapter (Gemini + fallback chain)
  prompts.py        system prompt and tool schemas
  speech.py         Whisper transcription in, OpenAI synthesis out (fallback)
  store.py          SQLite access, scores computed once at load
  geography.py      "New England", "the LA airports" -> codes
  web.py            FastAPI
  ingest/           downloader (BTS form-scraping lives here)
  etl/              t100, ontime, runways, airports, metrics, build
web/index.html      the entire front end, one file, no build step
scripts/evaluate.py answer-quality harness
tests/              83 tests
docs/adr/           28 ADRs
docs/further-work.md  8 deferred items, each with what it fixes
```

---

## Things that will bite you

1. **SQL strings use Python `%` formatting.** A literal `%` anywhere in the SQL,
   *including in a comment*, breaks the build with a confusing error. Cost two
   builds already.
2. **Python 3.9.** No `match`, no `X | Y` unions.
3. **Restart the server after code changes** — or run with `--reload`. A fixed
   FAA parser was tested against a stale process and looked broken.
4. **T-100 is scraped, not downloaded.** It requires POSTing an ASP.NET form
   with a freshly scraped `__VIEWSTATE`. If BTS redesigns that page it breaks,
   with a clear error saying so.
5. **BTS throttles to ~42 KB/s per connection**, not per IP. Hence 8 workers.
   `data/raw/` took ~35 minutes; do not re-download casually.
6. **Two different data windows** — on-time 12 months, T-100 36 months. Answers
   must state which they rest on.
7. **Cargo is invisible to hourly metrics.** At ANC (57%), MEM (65%), SDF (68%)
   the peak-hour score is biased low; the flag travels with the score.
8. **Not a git repo.** Deferred by the user.
9. **`data/raw/` and `data/work/` are gitignored** and must not be shipped. Only
   `data/airports.db` (7.9 MB) goes with the source.

---

## Voice: how it works, and every trap in it

```
click mic once
  -> browser records, encodes 16 kHz WAV
  -> auto-sends when you pause (or tap the orb)
  -> Groq Whisper            transcribe          ~1.0 s
  -> Gemini + the six tools  answer               2-5 s   (unchanged from typing)
  -> browser speech          speak               instant  (OpenAI if it refuses)
  -> mic reopens automatically
```

The agent is the whole wait now: speech is instant because it is local.
Carmit (Enhanced) speaks Hebrew, Lee (Premium) English — both chosen by the
script of the answer, both neural where macOS offers it (ADR-0028).

**Every voice bug today came from a fixed threshold meeting a real microphone.**
Synthetic `say` audio never reproduced any of them.

- **Speech detection** used a fixed RMS bar. A quieter mic never crossed it, so
  recording never stopped and nothing was ever sent — with no manual way to
  submit. Now adaptive, with an absolute floor, a 30 s cap, and a tappable orb.
- **Barge-in** used a fixed 0.045, unreachable on that same mic, so interrupting
  was impossible. Now a multiple of the calibrated bar.
- **Silence was being sent**, and Whisper does not return an empty string for
  silence — it returns a phrase from training. "Thank you" / "תודה" turned a
  recording of nothing into three turns of small talk. Rejected on both sides
  now; greetings deliberately still pass.
- **Language flipped mid-conversation.** Whisper's language *label* is a guess
  and wrong on short clips; its *script* is not. Language is decided by script
  and is sticky per conversation — an established Hebrew conversation only
  switches on a genuinely long English sentence.
- **Autoplay** blocked an `<audio>` element created seconds after the click.
  Playback goes through an AudioContext resumed during the gesture, and Safari
  additionally refuses `speechSynthesis.speak()` outside a gesture, so speech is
  unlocked with a silent utterance during the click.
- **Streaming speech was the mistake.** It gave 0.56 s to the first word against
  2.35 s buffered, and cost far more than it bought: ~20 slices per answer that
  had to be ordered, counted and watched for an ending. Slices played out of
  order, the utterance "ended" once per slice, and when a counter never reached
  zero it never ended at all. Reverted to one local `speak()` (ADR-0028).
- **A rate-limited model looked like a hang.** The API asks for a quota delay
  and the retry loop obeyed it across four fallback models — 179 seconds for a
  one-word greeting, with no way to cancel. Now a 20 s budget, and ending the
  conversation aborts the request.
- **Noise could start a conversation.** The energy gate asks *was there sound*,
  not *was that a question*. A keystroke came back as "the", the speaker leaking
  past echo cancellation as "sound" — each bought an agent round trip and then
  sat in the history, so the next fragment was answered against it. A
  single-word transcript is now rejected unless it names an airport or answers
  the previous turn (ADR-0026). Related: "no speech detected" used to render as
  an **analyst turn** in the transcript, and the hint explaining it was erased
  by the state repaint that immediately followed.
- **Safari** produced three failures Chrome never did (permission prompt every
  time, `Load failed`, and a `SyntaxError` from a non-JSON 500). **Demo in
  Chrome.**

---

## The bugs worth knowing about, because they recurred

Every one produced a **plausible wrong answer** rather than an error:

- Peak saturation set by a single spike hour — LAX, busy 17 hours a day, scored
  as though empty (ADR-0015).
- The volume floor counted flights, not passengers — Trenton (156k passengers)
  excluded while an Alaskan village (1,194) was kept (ADR-0022).
- The FAA tool matched tag names ending in "closure"; the real tag is
  `Airport_Closure_List`, so it reported "no active programs" always.
- `"New England"` resolved to **LAX** — the metro key `la` matched inside
  "eng-**la**-nd".
- Runway count treated SFO's four strips as four streams; they are two.
- Removing dead TTS code dropped an import the *transcription* fallback still
  used — `NameError`, a non-JSON 500, and an unrelated-looking browser error.

`scripts/evaluate.py` exists because of this pattern. It traces every number in
an answer back to a tool result, and catches invented figures that read as
entirely plausible.

---

## Open calibration questions

- Component weights (0.40/0.30/0.30) are a documented judgment call. Sensitivity
  was measured (ADR-0022): the **shortlist is stable**, only the internal order
  moves. Answers should lean on membership, not fine rank differences.
- 63 scored airports have no peak-hour data at all; their scores use two of
  three components, renormalised, and say so. **PSM is the sharp case — top of
  New England at 90.7 with 40% of the score absent.**

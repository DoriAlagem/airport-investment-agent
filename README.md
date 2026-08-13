# AI.I — Airport Investment Intelligence

An agent for analysts at a firm investing in US airport modernisation. It ranks
airports by **suppressed demand** — traffic that exists today but cannot be
served because the facility is too small — and says where a terminal would
actually help.

Ask it things like:

- *Which airports in New England are strong candidates for terminal expansion?*
- *Compare LA and Santa Ana airport congestion levels.*
- *What is the percentage of long haul flights out of Anchorage airport?*
- *What is the unmet flight demand in SFO airport and why?*

Follow-ups work: *"What about Providence?"* → *"Is that one runway-limited or
terminal-limited?"*

**Every number in an answer comes from a deterministic calculation, never from
the model.** The model chooses which questions to ask of the data and writes the
prose; the arithmetic lives in `scoring.py` and is covered by tests.

---

## Quick start

Requires **Python 3.9+**. The snapshot (`data/airports.db`, 7.9 MB) ships with
the source, so there is nothing to download.

```bash
pip install -r requirements.txt

cp .env.example .env          # add GEMINI_API_KEY - free at aistudio.google.com
                              # GROQ_API_KEY optional, but see the note below

PYTHONPATH=src python3 -m uvicorn airport_intel.web:app --port 8000
```

Open **http://127.0.0.1:8000** and ask a question.

`GEMINI_API_KEY` alone runs everything, including voice — verified on a copy of
this project with no other key set.

`GROQ_API_KEY` is strongly recommended for voice input. Without it, transcription
falls back to Gemini, which on the same Hebrew sentence silently replaced "New
England" with "the United States" — a fluent, plausible, wrong question that the
agent would then have answered ([ADR-0016](docs/adr/0016-voice-to-voice-and-multilingual-input.md)).

---

## What it knows

| | |
|---|---|
| Universe | **396 US airports** scored, from 1,311 in the data — the cut is the federal "primary airport" definition, ≥10,000 passengers a year |
| Congestion & delay | 12 months, **2025-01 to 2025-12** |
| Traffic & growth | 36 months, **2023-01 to 2025-12** |
| Sources | BTS T-100 Segment, BTS On-Time Performance, OurAirports, FAA NAS Status |

The two windows differ because the sources publish differently, and answers
state which window they rest on ([ADR-0013](docs/adr/0013-split-ingest-windows.md)).

---

## How the scoring works

```
congestion = 0.40 × peak saturation    median hour ÷ peak hour — is the day flat?
           + 0.30 × fullness           passengers ÷ seats — is the demand real?
           + 0.30 × capacity delay     NAS delay minutes per departure
                                        …each a percentile WITHIN its hub tier

final      = congestion × clamp(growth, 0.75, 1.25)      3-year passenger CAGR

alongside  constraint type = peak movements ÷ EFFECTIVE runways
                             runway-limited  → a terminal will not help
                             terminal-limited → expansion is actionable
```

Two things worth knowing before reading any score:

**Scores are only comparable within a tier.** Each component is a percentile
against airports of the same FAA hub size, so SNA's 76.8 and LAX's 42.1 do not
mean SNA is busier — they mean SNA is more constrained *relative to its peers*
than LAX is to its own.

**The final score is an index on 0–125, not a percentage.** Congestion is
0–100 and the growth multiplier reaches 1.25, so a few small airports exceed
100.

Current large-hub leaders: **EWR 88.3, LGA 84.7, ATL 81.0, MCO 80.7, BOS 79.6.**
Newark and LaGuardia coming out on top is the strongest external check
available — nothing was tuned to produce it.

The full reasoning, including the approaches that were rejected, is in
**[DESIGN.md](DESIGN.md)** and the 28 ADRs in [docs/adr/](docs/adr/).

---

## Interface

**Chat** is the primary interface. Every answer shows the prose plus an evidence
card: the components, their percentiles, the raw values, the confidence, and the
tool calls behind them. The numbers are visible so a wrong one is visible too.

**Voice** is a bonus and works in English and Hebrew. Click the microphone once
and talk; it detects when you stop, answers, speaks, and reopens the microphone.
Speaking over it interrupts it. The language is decided by the *script* of what
you said, not by a detector's guess, and it is sticky per conversation.

Voice needs a browser with `getUserMedia` and speech synthesis — **Chrome or
Safari on macOS**. Speech output uses the operating system's voice: instant,
offline, and free. If the browser refuses to speak — Safari does, for any
utterance not started by a click — it falls back to OpenAI when
`OPENAI_API_KEY` is set, and to silence with the text still on screen when it is
not ([ADR-0028](docs/adr/0028-speech-output-returns-to-the-browser-voice.md)).

---

## Tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q                    # 83 tests, no API keys, no network
```

There is a second harness that checks the *answers* rather than the code:

```bash
PYTHONPATH=src python3 scripts/evaluate.py     # 7 cases, uses live API calls
```

It asserts what each answer must and must not contain, then traces **every
number in the prose back to a tool result**. That check exists because the
recurring failure in this project was never a crash — it was a confident,
fluent, wrong answer. Reading the sentence does not reveal an invented figure;
tracing it does.

---

## Layout

```
src/airport_intel/
  scoring.py        the deterministic core — pure functions, no I/O
  tools.py          the six tools the model may call
  agent.py          tool-calling loop
  llm.py            Gemini adapter, retries, model fallback
  prompts.py        system prompt and tool schemas
  speech.py         transcription in, synthesis out
  store.py          SQLite access; scores computed once at load
  geography.py      "New England", "the LA airports" → airport codes
  web.py            FastAPI
  ingest/           downloaders (the BTS form-scrape lives here)
  etl/              t100, ontime, runways, airports, metrics, build
web/index.html      the entire front end — one file, no build step
scripts/evaluate.py answer-quality harness
DESIGN.md           scoring methodology, tradeoffs, where AI is used
docs/adr/           28 architecture decision records
```

---

## Rebuilding the snapshot

Not needed to run the agent. To rebuild from source data:

```bash
pip install -r requirements-build.txt
PYTHONPATH=src python3 -m airport_intel.ingest.download    # ~35 min, ~390 MB
PYTHONPATH=src python3 -m airport_intel.etl.build          # ~2 min
```

BTS throttles to roughly 42 KB/s **per connection**, which is why the downloader
runs eight of them. `data/raw/` and `data/work/` are intermediate and are not
part of the deliverable.

---

## Scope and limits

The agent states its own limits in its answers, and they are argued in full in
**[DESIGN.md](DESIGN.md#limits)**. In short: **US airports only**, no
spilled-demand model, cargo invisible to hourly metrics, 63 of the 396 scored
airports missing a component (52 of them scored on one), and place names matched
in English.

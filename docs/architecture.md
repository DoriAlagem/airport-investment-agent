# Architecture

```mermaid
flowchart TB

  subgraph SRC[" public data sources "]
    T100["BTS T-100 Segment<br/>passengers, seats, freight<br/>ASP.NET form scrape"]
    ONTIME["BTS On-Time<br/>flight-level, delay causes"]
    OURAIR["OurAirports<br/>runways, coordinates, hub tier"]
    FAA["FAA NAS Status<br/>live ground stops, closures"]
  end

  DL["ingest/download.py<br/>8 workers - BTS throttles<br/>per connection, not per IP"]
  RAW[("data/raw<br/>~390 MB")]
  ETL["etl/ - DuckDB<br/>t100, ontime, runways,<br/>airports, metrics"]
  DB[("data/airports.db - 7.9 MB<br/>ships with the source<br/>facts only, no scores")]

  T100 --> DL
  ONTIME --> DL
  OURAIR --> ETL
  DL --> RAW
  RAW --> ETL
  ETL --> DB

  subgraph CORE[" deterministic core - no model touches this "]
    STORE["store.py<br/>loads once, scores once"]
    SCORE["scoring.py<br/>0.40 peak saturation<br/>0.30 fullness<br/>0.30 capacity delay<br/>percentile WITHIN hub tier<br/>x growth, clamped 0.75-1.25"]
    CONSTRAINT["constraint type<br/>peak movements / EFFECTIVE runways<br/>runway-limited = a terminal will not help"]
  end

  DB --> STORE
  STORE --> SCORE
  SCORE --> CONSTRAINT

  TOOLS["tools.py - six tools<br/>resolve, score, rank, compare,<br/>route_profile, current_conditions<br/>the only way the model sees data"]
  AGENT["agent.py<br/>tool-calling loop, max 6 rounds<br/>provider-neutral turns<br/>history trimmed at a real question"]
  GEMINI{{"Gemini 3.5-flash-lite<br/>picks tools, writes prose<br/>NEVER produces a number"}}

  SCORE --> TOOLS
  CONSTRAINT --> TOOLS
  FAA --> TOOLS
  TOOLS <--> AGENT
  AGENT <--> GEMINI

  WEB["web.py - FastAPI"]
  UI["web/index.html<br/>one file, no build step<br/>prose + evidence card per answer"]

  AGENT --> WEB
  WEB --> UI

  subgraph VOICE[" voice - bonus - the agent is unaware of it "]
    WHISPER{{"Groq whisper-large-v3<br/>language decided by SCRIPT,<br/>not by the detector"}}
    GATE["what reaches the agent<br/>sign-offs stripped<br/>single words gated"]
    SPEAK["browser voice<br/>Carmit (he) / Lee (en)<br/>OpenAI as fallback"]
  end

  UI -- "16 kHz WAV" --> WHISPER
  WHISPER --> GATE
  GATE --> AGENT
  UI --> SPEAK

  EVAL["scripts/evaluate.py<br/>traces EVERY number in the prose<br/>back to a tool result"]
  TESTS["102 tests<br/>14 of 14 mutations caught"]

  AGENT -.-> EVAL
  SCORE -.-> TESTS

  classDef model fill:#f7f7f7,stroke:#555,stroke-dasharray:3 3
  class GEMINI,WHISPER model
```

## What the arrows mean

**Solid** — data flowing through the system. **Dashed** — the checks that keep
it honest, which run outside a request.

The boundary that matters is the deterministic core. Everything inside it is
pure Python with no model in the path: the same snapshot produces byte-identical
scores on every load, verified three times over. The model sits to the right of
`tools.py` and can only ask questions of it.

Build time (`ingest` → `etl` → `airports.db`) runs once and is not part of
answering a question. That is
[ADR-0005](adr/0005-batch-snapshot-architecture.md): an analyst asking "rank New
England" needs all of them scored, not one, and percentiles are only meaningful
against the whole cohort.

Voice is drawn as a shell around the edges because that is exactly what it is
([ADR-0008](adr/0008-stack-and-interface.md)) — audio becomes text before the
agent sees it, and text becomes audio after it is done. The agent, the tools and
the scoring are unaware any of it exists, which is why the interface speaks
Hebrew without a single change to the core.

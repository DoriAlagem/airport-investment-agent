# ADR-0029: The agent loop speaks its own types; tools carry their own schemas

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** Dor
- **Refines:** [ADR-0007](0007-agent-architecture.md) — tool-calling loop over a small fixed tool set

---

## Context

The loop of ADR-0007 worked, but three things about how it was built had become
liabilities:

1. **Each tool was defined twice.** Its JSON schema lived in `prompts.py`, its
   dispatch entry in `agent.py`. Adding a tool meant editing both, and missing
   one failed only when the model called it.
2. **The loop thought in Gemini's wire format.** History entries were Gemini
   `contents` dicts, and tool results were `"user"` turns whose parts happened
   to be `functionResponse`. The history-trimming bug that killed conversations
   on about the fourth question came straight from that: a tool result looked
   like a user turn. `llm.py` claimed that swapping provider meant
   replacing one file; in practice `agent.py` would have had to change too.
3. **Tool calls in one round ran one after another**, so a round that scored
   four airports and checked the FAA's live feed waited for the sum of them.

A framework (LangGraph, PydanticAI) was considered and rejected, for the reason
already given in `llm.py`: the loop is a few dozen lines, and the one thing
worth asserting — which tool ran with which arguments — is what a framework
hides.

## Decision

- **`messages.py`** defines the conversation in neutral terms: `UserTurn`,
  `ModelTurn` (text, tool calls, and the provider's `raw` parts), and
  `ToolResultsTurn`. The agent reads and writes only these.
- **`llm.py`** translates them to and from Gemini's format, and nothing else
  does. An `LLM` protocol states what the agent needs: `generate(turns, system,
  tools) -> ModelTurn`. The model's own parts are kept in `raw` and echoed back
  verbatim, so thought signatures survive.
- **`toolbox.py`** holds one `Tool` per function — name, description, parameter
  schema and handler together — and the schemas the model sees are derived from
  it. `Toolbox.run_all` runs one round's calls concurrently, returning results
  in call order. Failures stay results, never exceptions.
- **`Store`** takes a lock around queries on its shared SQLite connection, which
  parallel tools and FastAPI's request threads both use.
- **A question the model never answered is rolled back** out of the history, so
  a quota error does not leave a half-finished exchange to be re-sent.

## Consequences

- History trimming is a type check — open the window on a `UserTurn` — rather
  than a rule about which `"user"` turns are really users.
- Another provider is a new class with the same `generate`; the loop, the
  trimming and the tests do not change.
- The loop now has tests of its own, driven by a scripted model: results reach
  the model before it answers, the round limit produces an answer, follow-ups
  see earlier turns, failed questions leave no trace, and one round really runs
  in parallel. The Gemini translation is tested separately on the wire.
- The response shape of `/api/chat` and `/api/voice` is unchanged, so neither
  the page nor `scripts/evaluate.py` needed to change.

"""Provider adapter.

Deliberately thin and framework-free: the whole agent loop is a few dozen lines,
and a framework would be larger than what it wraps while hiding exactly which
tool fired with which arguments - the one thing worth being able to assert
(ADR-0008).

The agent speaks in the neutral turns of messages.py; this file alone knows
Gemini's wire format. Swapping provider means writing another class with the
same `generate` - nothing in the loop changes (ADR-0029). Because the model
performs no arithmetic, that cannot change any number the system produces -
only wording.
"""
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

import requests

from .messages import ModelTurn, ToolCall, ToolResultsTurn, Turn, UserTurn

log = logging.getLogger(__name__)

# A lighter model is the default because the free tier is rate-limited per
# minute, and a single question costs several requests - one per tool round.
# The model only selects tools and writes prose; it performs no arithmetic, so
# a smaller model costs nothing in accuracy of the figures (ADR-0008).
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# Tried in order when the primary is overloaded. Free-tier capacity fluctuates
# by model, and a demo that dies because one endpoint is busy is worse than one
# that quietly answers on a sibling model. All are equivalent for this workload:
# the model only picks tools and writes prose.
FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-3.6-flash"]

ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "%s:generateContent?key=%s")

REQUEST_TIMEOUT_SECONDS = 90

# Low but not zero: tool selection should be stable, while leaving the prose
# some freedom. Temperature cannot affect any figure - those come from the
# tools (ADR-0018).
TEMPERATURE = 0.2

# How much of a provider error to keep. Enough to identify it, not enough to
# bury the log in a stack trace.
ERROR_EXCERPT_CHARS = 200
BODY_EXCERPT_CHARS = 300

# Added to the wait the API asks for, so a retry never lands on the same
# second the quota resets.
RETRY_MARGIN_SECONDS = 2.0

# The most time a single call may spend waiting on quota before giving up and
# saying so. Chosen against the interface: a person will wait a few seconds for
# an answer and will not wait three minutes without being told why.
RETRY_BUDGET_SECONDS = 20.0

MAX_RETRIES = 3
DEFAULT_BACKOFF = 20.0
OVERLOAD_BACKOFF = 3.0

# Transient by nature: waiting or moving model is the right response, failing
# the user's question is not.
RETRYABLE = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"}


def load_api_key(project_root: Optional[Path] = None,
                 env_var: str = "GEMINI_API_KEY") -> Optional[str]:
    """Environment first, then a local .env. Never committed either way."""
    key = os.environ.get(env_var)
    if key:
        return key.strip()
    root = project_root or Path(__file__).resolve().parents[2]
    env = root / ".env"
    if env.exists():
        prefix = env_var + "="
        for line in env.read_text().splitlines():
            if line.startswith(prefix):
                return line.split("=", 1)[1].strip() or None
    return None


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    """What the agent needs from a model, whoever provides it."""

    active_model: Optional[str]

    def generate(self, turns: Sequence[Turn], system: str,
                 tools: Optional[List[Dict]] = None) -> ModelTurn:
        ...


# --- Gemini wire format ------------------------------------------------------
#
# Gemini has no role for tool results: they travel as "user" turns whose parts
# are functionResponse objects, and each must immediately follow the model turn
# that asked for it. Keeping that rule here is what lets the agent treat a tool
# result as its own kind of turn.

def to_gemini_contents(turns: Sequence[Turn]) -> List[Dict[str, Any]]:
    contents = []
    for turn in turns:
        if isinstance(turn, UserTurn):
            contents.append({"role": "user", "parts": [{"text": turn.text}]})
        elif isinstance(turn, ModelTurn):
            # Echoed verbatim when we have it: the parts carry thought
            # signatures, and rebuilding them would drop those.
            parts = turn.raw if turn.raw is not None else _model_parts(turn)
            contents.append({"role": "model", "parts": parts})
        elif isinstance(turn, ToolResultsTurn):
            contents.append({"role": "user", "parts": [
                {"functionResponse": _strip_none({
                    "id": r.call.id, "name": r.call.name,
                    "response": {"result": r.result}})}
                for r in turn.results]})
        else:
            raise TypeError("Not a conversation turn: %r" % (turn,))
    return contents


def from_gemini_content(content: Dict[str, Any]) -> ModelTurn:
    parts = content.get("parts") or []
    text, calls = [], []
    for part in parts:
        if "functionCall" in part:
            fc = part["functionCall"]
            calls.append(ToolCall(name=fc.get("name", ""),
                                  args=fc.get("args") or {}, id=fc.get("id")))
        elif part.get("text"):
            text.append(part["text"])
    return ModelTurn(text="".join(text), tool_calls=calls, raw=parts)


def _model_parts(turn: ModelTurn) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = []
    if turn.text:
        parts.append({"text": turn.text})
    for c in turn.tool_calls:
        parts.append({"functionCall": _strip_none(
            {"id": c.id, "name": c.name, "args": c.args})})
    return parts


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class Gemini:
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or load_api_key()
        if not self.api_key:
            raise LLMError(
                "No GEMINI_API_KEY. Set the environment variable or put it in .env"
            )
        self.model = model
        self.active_model = model

    def generate(self, turns: Sequence[Turn], system: str,
                 tools: Optional[List[Dict]] = None,
                 timeout: int = REQUEST_TIMEOUT_SECONDS) -> ModelTurn:
        """One model turn, from and to the neutral conversation types.

        The returned turn keeps Gemini's own parts in `raw`, so the next request
        echoes them back unchanged: Gemini attaches a thought signature to
        them, and stripping it degrades multi-step tool use.
        """
        return from_gemini_content(
            self._request(to_gemini_contents(turns), system, tools, timeout))

    def _request(self, contents: List[Dict], system: str,
                 tools: Optional[List[Dict]], timeout: int) -> Dict:
        """POST with retries and model fallback; returns the candidate content."""
        payload: Dict = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": TEMPERATURE},
        }
        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]

        last_error = None
        # A quota wait is only worth taking if it is short. The API will happily
        # ask for 40 seconds, four models deep, and obeying that turned a
        # greeting into a 179-second wait with the interface stuck on
        # "Thinking" and no way to cancel. Past this budget the answer is that
        # the model is busy - said quickly, so the user can decide (ADR-0028).
        deadline = time.time() + RETRY_BUDGET_SECONDS
        for model in [self.model] + [m for m in FALLBACK_MODELS if m != self.model]:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = requests.post(ENDPOINT % (model, self.api_key),
                                         json=payload, timeout=timeout,
                                         headers={"Content-Type": "application/json"})
                    body = resp.json()
                except (requests.RequestException, ValueError) as exc:
                    last_error = "transport error: %s" % exc
                    time.sleep(OVERLOAD_BACKOFF)
                    continue

                error = body.get("error")
                if not error:
                    candidates = body.get("candidates") or []
                    if not candidates:
                        raise LLMError("No candidates returned: %s"
                                       % json.dumps(body)[:BODY_EXCERPT_CHARS])
                    self.active_model = model
                    return candidates[0].get("content", {})

                status = error.get("status")
                last_error = "%s: %s" % (status, error.get("message", "")[:ERROR_EXCERPT_CHARS])
                if status not in RETRYABLE:
                    raise LLMError(last_error)
                log.warning("%s on %s (attempt %d)", status, model, attempt + 1)

                # Quota is per minute and the API states how long to wait;
                # overload is usually shorter-lived, so back off less before
                # trying the next model.
                wait = (_retry_delay(error.get("message", ""))
                        if status == "RESOURCE_EXHAUSTED" else OVERLOAD_BACKOFF)
                # Waiting past the budget, or for longer than the budget allows,
                # is worse than moving on: the next model may have quota left.
                if time.time() + wait > deadline:
                    break
                time.sleep(wait)

        raise LLMError(
            "Every model is rate-limited right now. Wait a moment and ask "
            "again. Last error - %s" % last_error)


def _retry_delay(message: str) -> float:
    """Honour the wait the API asks for, with a small margin."""
    match = re.search(r"retry in ([0-9.]+)s", message)
    if match:
        return float(match.group(1)) + RETRY_MARGIN_SECONDS
    return DEFAULT_BACKOFF

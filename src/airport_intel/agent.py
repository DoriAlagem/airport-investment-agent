"""The conversational agent: a tool-calling loop over the six tools.

The model chooses tools and writes prose. Everything numeric happens in
tools.py against the snapshot, so the same question yields the same figures
regardless of model or provider (ADR-0007).

A router was rejected because the assignment requires follow-up questions, and
"and what about the second one?" has no intent class - a tool loop handles it
natively because the history is already in context.
"""
from typing import Callable, Dict, List, Optional

from . import tools as T
from .llm import Gemini, split_parts
from .prompts import SYSTEM_PROMPT, TOOL_SCHEMAS
from .store import Store

MAX_TOOL_ROUNDS = 6

# Turns retained. Tool results are verbose, so an unbounded history grows the
# request every turn until it costs more than the answer is worth. Follow-ups
# reference the last exchange or two, not the twentieth.
#
# Lowered from 40: in a spoken conversation the whole history is re-sent on
# every round, and rounds are where the waiting is. Sixteen entries still covers
# several exchanges with their tool results.
MAX_HISTORY_ENTRIES = 16

# A transcript must look decisively English before an established Hebrew
# conversation is allowed to switch. Whisper sometimes renders Hebrew speech in
# Latin letters, and a short fragment of that is indistinguishable from English -
# which flipped the reply language mid-conversation for no visible reason.
DECISIVE_ENGLISH_CHARS = 25


class ToolCallRecord:
    """What the model asked for and what it got back.

    Kept so the interface can show its working: an agent that cites figures is
    only trustworthy if you can see where they came from.
    """

    def __init__(self, name: str, args: Dict, result: Dict):
        self.name = name
        self.args = args
        self.result = result

    def as_dict(self) -> Dict:
        return {"tool": self.name, "args": self.args, "result": self.result}



def _is_user_message(entry: Dict) -> bool:
    """A turn the person actually sent, not a tool result wearing the same role.

    Gemini has no separate role for function responses; they are "user" turns
    whose parts carry functionResponse instead of text.
    """
    if entry.get("role") != "user":
        return False
    return not any("functionResponse" in part for part in entry.get("parts", []))


class Agent:
    def __init__(self, store: Optional[Store] = None, llm: Optional[Gemini] = None):
        self.store = store or Store()
        self.llm = llm or Gemini()
        self.history: List[Dict] = []
        # The conversation's language, not the clip's. Set by the first turn and
        # kept until the speaker clearly changes language.
        self.language: Optional[str] = None
        self._dispatch: Dict[str, Callable] = {
            "resolve_airports": lambda a: T.resolve_airports(self.store, a["query"]),
            "score_airport": lambda a: T.score_airport(self.store, a["code"]),
            "rank_airports": lambda a: T.rank_airports(self.store, a["codes"]),
            "compare_airports": lambda a: T.compare_airports(self.store, a["codes"]),
            "route_profile": lambda a: T.route_profile(self.store, a["code"]),
            "current_conditions": lambda a: T.current_conditions(self.store, a["code"]),
        }

    def reset(self) -> None:
        self.history = []
        self.language = None

    def _settle_language(self, heard: Optional[str], transcript: str) -> Optional[str]:
        """Decide the reply language for this turn.

        Hebrew script is unambiguous, so it always wins. Its absence is not:
        a mis-transcription of Hebrew into Latin letters looks exactly like
        English. So an established Hebrew conversation only switches on a
        transcript long enough to be a real English sentence rather than a
        garbled fragment.
        """
        if heard not in ("he", "en"):
            return self.language

        if heard == "he":
            self.language = "he"
        elif self.language != "he" or len(transcript.strip()) >= DECISIVE_ENGLISH_CHARS:
            self.language = "en"
        return self.language

    def _run_tool(self, name: str, args: Dict) -> Dict:
        handler = self._dispatch.get(name)
        if not handler:
            return {"error": "unknown_tool", "message": "No tool named %s." % name}
        try:
            return handler(args or {})
        except KeyError as exc:
            return {"error": "bad_arguments",
                    "message": "%s missing required argument %s." % (name, exc)}
        except Exception as exc:
            # Surfaced to the model rather than raised, so it can tell the user
            # the data is unavailable instead of the request dying.
            return {"error": "tool_failed", "message": "%s failed: %s" % (name, exc)}

    def _trim_history(self) -> None:
        """Keep the tail, starting at a real question.

        Gemini rejects a history whose first entry is a model turn, and it
        rejects a function response that does not follow its own call:

            INVALID_ARGUMENT: Please ensure that function response turn comes
            immediately after a function call turn.

        Advancing to the next entry with role "user" is not enough, because a
        function RESPONSE is also role "user" - so the window could open on a
        response whose call had just been trimmed away, and the conversation
        died on about the fourth question. The window opens on a turn the user
        actually typed or spoke.
        """
        if len(self.history) <= MAX_HISTORY_ENTRIES:
            return

        start = len(self.history) - MAX_HISTORY_ENTRIES
        while start < len(self.history) and not _is_user_message(self.history[start]):
            start += 1

        if start >= len(self.history):
            # The whole window is one exchange's tool traffic. Keep more rather
            # than discarding the conversation: an over-long history costs
            # tokens, a broken one costs the answer.
            start = 0
            for i in range(len(self.history) - 1, -1, -1):
                if _is_user_message(self.history[i]):
                    start = i
                    break

        self.history = self.history[start:]

    def ask(self, message: str, language: Optional[str] = None) -> Dict:
        """One user turn. Returns the answer plus every tool call made.

        `language` pins the reply. Whisper already decided what was spoken, and
        letting the model re-guess from the transcript made short questions flip
        language between turns for no reason the user could see.
        """
        self._trim_history()
        reply_in = self._settle_language(language, message)
        if reply_in in ("he", "en"):
            message = "%s\n\n[Reply in %s.]" % (
                message, "Hebrew" if reply_in == "he" else "English")
        self.history.append({"role": "user", "parts": [{"text": message}]})
        calls_made: List[ToolCallRecord] = []

        for _ in range(MAX_TOOL_ROUNDS):
            content = self.llm.generate(self.history, SYSTEM_PROMPT, TOOL_SCHEMAS)
            # Echoed back verbatim: the model's parts carry thought signatures
            # that multi-step tool use depends on.
            self.history.append({"role": "model",
                                 "parts": content.get("parts", [])})
            text, calls = split_parts(content)

            if not calls:
                return {"answer": text,
                        "tool_calls": [c.as_dict() for c in calls_made]}

            responses = []
            for call in calls:
                name = call.get("name")
                args = call.get("args") or {}
                result = self._run_tool(name, args)
                calls_made.append(ToolCallRecord(name, args, result))
                responses.append({
                    "functionResponse": {"name": name, "response": {"result": result}}
                })
            self.history.append({"role": "user", "parts": responses})

        return {
            "answer": ("I could not complete that within the tool-call limit. "
                       "Try asking about one airport or region at a time."),
            "tool_calls": [c.as_dict() for c in calls_made],
        }

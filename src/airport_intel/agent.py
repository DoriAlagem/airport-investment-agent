"""The conversational agent: a tool-calling loop over the six tools.

The model chooses tools and writes prose. Everything numeric happens in
tools.py against the snapshot, so the same question yields the same figures
regardless of model or provider (ADR-0007).

A router was rejected because the assignment requires follow-up questions, and
"and what about the second one?" has no intent class - a tool loop handles it
natively because the history is already in context.
"""
import logging
from typing import Dict, List, Optional

from .llm import LLM, Gemini
from .messages import ModelTurn, ToolResult, ToolResultsTurn, Turn, UserTurn
from .prompts import SYSTEM_PROMPT
from .store import Store
from .toolbox import Toolbox

log = logging.getLogger(__name__)

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

TOOL_LIMIT_ANSWER = ("I could not complete that within the tool-call limit. "
                     "Try asking about one airport or region at a time.")


class Agent:
    def __init__(self, store: Optional[Store] = None, llm: Optional[LLM] = None,
                 toolbox: Optional[Toolbox] = None):
        self.store = store or Store()
        self.llm = llm or Gemini()
        self.toolbox = toolbox or Toolbox(self.store)
        self.history: List[Turn] = []
        # The conversation's language, not the clip's. Set by the first turn and
        # kept until the speaker clearly changes language.
        self.language: Optional[str] = None

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

    def _trim_history(self) -> None:
        """Keep the tail, starting at a real question.

        Gemini rejects a history whose first entry is a model turn, and it
        rejects a function response that does not follow its own call:

            INVALID_ARGUMENT: Please ensure that function response turn comes
            immediately after a function call turn.

        On Gemini's wire a tool result is also role "user", which once let the
        window open on a result whose call had been trimmed away - the
        conversation died on about the fourth question. With tool results as
        their own turn type the rule is simply: open on a UserTurn.
        """
        if len(self.history) <= MAX_HISTORY_ENTRIES:
            return

        start = len(self.history) - MAX_HISTORY_ENTRIES
        while start < len(self.history) and not isinstance(self.history[start], UserTurn):
            start += 1

        if start >= len(self.history):
            # The whole window is one exchange's tool traffic. Keep more rather
            # than discarding the conversation: an over-long history costs
            # tokens, a broken one costs the answer.
            start = 0
            for i in range(len(self.history) - 1, -1, -1):
                if isinstance(self.history[i], UserTurn):
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
        checkpoint = len(self.history)
        self.history.append(UserTurn(message))
        try:
            return self._loop()
        except Exception:
            # A question the model never answered (quota, network) is not part
            # of the conversation. Left in, it would be re-sent with the next
            # question as if it were still pending.
            del self.history[checkpoint:]
            raise

    def _loop(self) -> Dict:
        """Reason, act, observe - until the model answers or the limit is hit."""
        results: List[ToolResult] = []

        for _ in range(MAX_TOOL_ROUNDS):
            turn: ModelTurn = self.llm.generate(
                self.history, SYSTEM_PROMPT, self.toolbox.schemas())
            self.history.append(turn)

            if not turn.tool_calls:
                return self._reply(turn.text, results)

            round_results = self.toolbox.run_all(turn.tool_calls)
            results.extend(round_results)
            self.history.append(ToolResultsTurn(round_results))

        log.warning("tool-call limit reached after %d calls", len(results))
        return self._reply(TOOL_LIMIT_ANSWER, results)

    @staticmethod
    def _reply(answer: str, results: List[ToolResult]) -> Dict:
        """The answer plus every tool call behind it.

        The calls are returned so the interface can show its working: an agent
        that cites figures is only trustworthy if you can see where they came
        from.
        """
        return {"answer": answer, "tool_calls": [r.as_dict() for r in results]}

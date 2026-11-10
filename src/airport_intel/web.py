"""FastAPI server for the chat interface.

    uvicorn airport_intel.web:app --reload --port 8000

One Agent per session id, so each browser tab keeps its own history and
follow-up questions resolve against the right conversation.

The snapshot is loaded once and shared: it is read-only after construction, and
loading it per session would re-score every airport on every page open.
"""
import base64
import json
import logging
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI
from fastapi import Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import speech
from .agent import Agent
from .llm import Gemini, LLMError
from .store import Store

STATIC_DIR = Path(__file__).resolve().parents[2] / "web"

# 204: nothing to play, and not an error - the page falls back to its own voice.
HTTP_NO_CONTENT = 204

# basicConfig does nothing if the host (uvicorn, a test runner) has already
# configured logging, so this only fills the gap when nothing else has.
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Airport Investment Intelligence Agent")

_store: Optional[Store] = None

# One Agent per session, capped and evicted oldest-first. An unbounded dict
# holds every conversation that ever reached the server, which is a slow leak in
# a long-running process and unnecessary for a tool that only needs recent
# context.
MAX_SESSIONS = 200
_sessions: "OrderedDict[str, Agent]" = OrderedDict()


def _session(session_id: str) -> Agent:
    agent = _sessions.get(session_id)
    if agent is None:
        agent = Agent(store=store(), llm=Gemini())
        _sessions[session_id] = agent
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    else:
        _sessions.move_to_end(session_id)
    return agent


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


# Words that are generic to airport names rather than to an airport. "Sound" is
# here because it is a real place name in the snapshot and also what the
# assistant's own voice was transcribed as; the same goes for the rest.
GENERIC_NAME_WORDS = {
    "airport", "international", "regional", "municipal", "county", "field",
    "air", "park", "city", "bay", "north", "south", "east", "west", "new",
    "sound", "port", "lake", "river", "valley", "island", "mount", "point",
    "station", "base", "harbor", "harbour", "beach", "springs", "falls",
}

_vocabulary: Optional[set] = None


def spoken_vocabulary() -> set:
    """Single words that could plausibly be a whole question.

    Airport codes and city names only - not every word of every airport's full
    name, which would readmit exactly the generic noise this is here to stop.
    """
    global _vocabulary
    if _vocabulary is None:
        words = set()
        for code, metrics in store().metrics.items():
            words.add(code.lower())
            for part in speech.words_in(metrics.get("city") or ""):
                if len(part) >= 4 and part not in GENERIC_NAME_WORDS:
                    words.add(part)
        _vocabulary = words
    return _vocabulary


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    tool_calls: List[Dict]
    model: Optional[str] = None
    error: Optional[str] = None


@app.get("/api/meta")
def meta() -> Dict:
    """Data windows and coverage, shown permanently in the UI.

    A snapshot that does not announce its own age is the failure this whole
    design guards against (ADR-0005).
    """
    s = store()
    scored = s.scored_codes()
    return {
        "ontime_window": s.data_window("ontime"),
        "t100_window": s.data_window("t100"),
        "airports_scored": len(scored),
        "speech_provider": speech.speech_provider(),
        "airports_total": len(s.all_codes()),
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or uuid.uuid4().hex
    agent = _session(session_id)

    try:
        result = agent.ask(request.message)
    except LLMError as exc:
        # Surfaced rather than raised: the tool results are still worth showing,
        # and the user should see why the model could not answer.
        return ChatResponse(answer="", session_id=session_id, tool_calls=[],
                            error=str(exc))

    return ChatResponse(
        answer=result["answer"],
        session_id=session_id,
        tool_calls=result["tool_calls"],
        model=getattr(agent.llm, "active_model", None),
    )


@app.post("/api/diag")
def diag(payload: Dict) -> Dict:
    """Report what the microphone actually measured.

    Every voice threshold in this project was wrong the first time because it
    was chosen against synthetic audio and met a real microphone later. This
    endpoint puts the real numbers in the server log, where they can be read
    without asking the user to open a console.
    """
    log.info("MIC %s", json.dumps(payload, ensure_ascii=False))
    return {"ok": True}


class VoiceRequest(BaseModel):
    audio_base64: str
    mime_type: str = "audio/wav"
    session_id: Optional[str] = None


@app.post("/api/voice")
def voice(request: VoiceRequest) -> Dict:
    """One round trip for voice-to-voice: listen, answer, speak.

    Transcription and synthesis bracket the ordinary text path; the agent
    receives a string and returns a string exactly as it does from the keyboard
    (ADR-0008).
    """
    try:
        audio = base64.b64decode(request.audio_base64)
    except Exception:
        return {"error": "Could not decode the recording."}

    try:
        heard = speech.transcribe(audio, request.mime_type)
    except LLMError as exc:
        return {"error": "Transcription failed: %s" % exc}

    # Not an error: nothing failed, there was simply nothing to answer. It is
    # reported separately so the interface can hint and reopen the microphone
    # rather than writing a red box into the transcript under the assistant's
    # name, which is what it used to do (ADR-0026).
    transcript = (heard.get("text") or "").strip()
    log.info("HEARD %r (%s)", transcript, heard.get("language"))
    if not transcript:
        return {"unheard": "I did not catch that — try speaking a little closer."}
    if not speech.is_substantive(transcript, spoken_vocabulary()):
        log.info("REJECTED as a fragment: %r", transcript)
        return {"unheard": "I heard only “%s” — say the whole question."
                           % transcript}

    session_id = request.session_id or uuid.uuid4().hex
    agent = _session(session_id)

    try:
        result = agent.ask(transcript, language=heard.get("language"))
    except LLMError as exc:
        return {"transcript": transcript, "session_id": session_id,
                "tool_calls": [], "error": str(exc)}

    payload = {
        "transcript": transcript,
        "transcribed_by": heard.get("provider"),
        "is_rtl": heard.get("is_rtl", False),
        "answer": result["answer"],
        "tool_calls": result["tool_calls"],
        "session_id": session_id,
        "model": getattr(agent.llm, "active_model", None),
    }


    return payload


class SpeakRequest(BaseModel):
    text: str


@app.post("/api/speak")
def speak(request: SpeakRequest):
    """The spoken reply, as one audio file.

    Returns 204 when no speech service is configured, which tells the page to
    use the browser's own voice rather than sit silent.

    This replaced a streamed version that cut each reply into ~20 slices. The
    streaming bought about two seconds to the first word and cost far more than
    it bought - ordering, counting and inferring the end of an utterance, which
    is where every voice fault in this project came from (ADR-0028).
    """
    text = speech.spoken_summary(request.text)
    try:
        audio = speech.synthesize(text)
    except LLMError as exc:
        log.warning("SPEAK failed: %s", exc)
        return Response(status_code=HTTP_NO_CONTENT)
    if audio is None:
        return Response(status_code=HTTP_NO_CONTENT)
    return Response(content=audio, media_type="audio/wav")


@app.post("/api/reset")
def reset(request: ChatRequest) -> Dict:
    if request.session_id and request.session_id in _sessions:
        _sessions[request.session_id].reset()
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    """The page, never cached.

    The whole front end is one file with no build step and no content hash, so a
    cached copy is indistinguishable from a current one. Debugging a fix that
    had not actually loaded cost real time here; closing and reopening a tab is
    not reliably a reload.
    """
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )

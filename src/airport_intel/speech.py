"""Speech in and speech out.

Voice is a shell at the edges: audio becomes text before the agent sees it, and
text becomes audio after the agent is done. The agent, the tools and the scoring
are unaware any of this exists (ADR-0008), which is what lets the interface
speak Hebrew without a single change to the deterministic core.

Listening is pluggable - Whisper via Groq when a key is present, Gemini
otherwise - because transcription output is plain text and the choice of
listener changes nothing downstream. Speech output is Gemini either way; Groq
does not serve TTS.
"""
import base64
import io
import re
import struct
import time
from typing import Dict, Optional

import requests

from .llm import ENDPOINT, LLMError, load_api_key

TRANSCRIBE_MODEL = "gemini-3.5-flash-lite"

# --- OpenAI ----------------------------------------------------------------
#
# Preferred for speech output when a key is present: its Hebrew is markedly
# better than the alternatives, and one voice covers both languages, so nothing
# has to be selected per language (ADR-0025).
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
OPENAI_VOICE = "coral"

# PCM rather than MP3: the browser builds the audio buffer from it directly,
# with no decoding step that could fail or reorder anything.
OPENAI_PCM_RATE = 24000


# Browser recordings arrive as 16 kHz mono WAV, encoded client-side rather than
# as WebM/Opus: Gemini's accepted audio containers do not include WebM, and
# transcoding on the server would mean an ffmpeg dependency.
TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim in its original language. "
    "The speaker is asking about US airports, so airport names and three-letter "
    "codes such as SFO, BOS or LAX should be written in Latin letters even when "
    "the surrounding speech is Hebrew. "
    "Output only the transcript. No commentary, no translation, no quotation marks."
)


GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"

# Whisper is capped at 20 requests a minute. A short wait beats the fallback,
# which invents Hebrew content rather than admitting it could not hear.
GROQ_RETRIES = 3
GROQ_RETRY_SECONDS = 4

# The interface is bilingual, so anything else is a mis-detection rather than a
# language. Whisper left to auto-detect has produced fluent Croatian from Hebrew
# speech - plausible-looking text for a question nobody asked, which the agent
# then answers (ADR-0026).
ALLOWED_LANGUAGES = ("en", "he")

# Whisper does not return an empty string for silence - it returns a phrase it
# saw often in training. That training was full of captioned video, so what it
# produces from nothing is video sign-off: "Thank you for watching! Please
# subscribe to my channel!" (ADR-0026).
#
# These are matched as **patterns, not as strings**. An exact-match list of
# whole phrases fails on the first variation it meets - "thank you" was caught
# while "Thank you for watching! Please subscribe to my channel!" walked
# through, was answered in English, and flipped a Hebrew conversation for the
# rest of its life. The family is small and closed; its wordings are not.
SIGN_OFF_PATTERNS = [
    r"thank(?:s|\s*you)?(?:\s*(?:you|so much|very much))?(?:\s*for\s*watching)?",
    r"(?:please\s*)?(?:don'?t\s*forget\s*to\s*)?(?:like\s*(?:and\s*)?)?"
    r"subscribe(?:\s*to\s*(?:my|the|our)\s*channel)?",
    r"see\s*you(?:\s*(?:next\s*time|in\s*the\s*next\s*(?:one|video)))?",
    r"(?:good)?bye(?:\s*bye)?",
    r"(?:subtitles?|captions?|transcription|translation)\s*by[\w\s.]*",
    r"amara\.org[\w\s.]*",
    r"you",
    r"תודה(?:\s*רבה)?(?:\s*שצפית[םןמ]?[םן]?)?",
    r"להתראות",
    r"נתראה(?:\s*בפעם\s*הבאה)?",
]

# A transcript is an artefact when nothing is left of it once the sign-offs are
# removed. This is what keeps a real turn safe: "thanks, and what about Boston"
# still has a question in it after the strip, so it survives.
_SIGN_OFF = re.compile(
    r"(?:%s)" % "|".join(SIGN_OFF_PATTERNS), re.IGNORECASE | re.UNICODE)

# Greetings are deliberately absent: "hello" and "שלום" are things a person
# actually says, and rejecting them would silence a real turn. Only phrases with
# no plausible use in this interface are listed.

# The list above can never be complete, and it does not need to be. A keystroke
# transcribed as "the", or the assistant's own voice leaking past echo
# cancellation as "sound", are not on it and never will be - but they share the
# shape of every such artefact: **one word**. A person asking this interface
# something says more than one.
#
# So a single word is rejected unless it earns its place: it answers what was
# just asked, or it names an airport (the caller supplies the codes and cities,
# which live in the snapshot rather than here). Everything else is treated as
# noise and never reaches the agent, because a junk turn does not just waste a
# round trip - it enters the history, and the next turn is answered against it
# (ADR-0026).
# Greetings are listed for the same reason they are absent from the artefact
# list above: a person opening a conversation with one word deserves an answer.
CONVERSATIONAL_SINGLE_WORDS = {
    "hello", "hi", "hey", "שלום", "היי", "אהלן",
    "yes", "yeah", "yep", "no", "nope", "sure", "ok", "okay",
    "why", "how", "more", "again", "repeat", "continue", "next", "stop",
    "wait", "compare", "rank", "expansion", "congestion",
    "כן", "לא", "בטח", "אוקיי", "למה", "איך", "עוד", "שוב", "תחזרי", "תחזור",
    "תמשיכי", "תמשיך", "הבא", "עצור", "רגע", "תשווי", "תשווה",
}

# Whisper names languages in full in verbose_json.
LANGUAGE_NAMES = {"english": "en", "hebrew": "he"}

TRANSCRIBE_TIMEOUT_SECONDS = 120
SYNTHESIS_TIMEOUT_SECONDS = 180
# Gemini returns bare PCM: signed 16-bit, single channel, 24 kHz. These describe
# the RIFF header written around it, not choices.
PCM_BITS = 16
PCM_CHANNELS = 1
PCM_SAMPLE_RATE = 24000
WAV_HEADER_BYTES = 36          # RIFF chunk size excluding the leading 8 bytes
BITS_PER_BYTE = 8

HTTP_OK = 200
ERROR_EXCERPT_CHARS = 200


def _key() -> str:
    key = load_api_key()
    if not key:
        raise LLMError("No GEMINI_API_KEY configured.")
    return key


def _groq_key() -> Optional[str]:
    return load_api_key(env_var="GROQ_API_KEY")


def _openai_key() -> Optional[str]:
    return load_api_key(env_var="OPENAI_API_KEY")


def speech_provider() -> str:
    """Which engine will speak, so the interface can decide whether to ask."""
    if _openai_key():
        return "openai"
    return "browser"


def synthesize_openai(text: str, key: str,
                      timeout: int = SYNTHESIS_TIMEOUT_SECONDS) -> bytes:
    """The whole reply as one WAV, in one request.

    This used to stream, cutting the PCM into ~20 slices per answer and giving
    each its own WAV header so the browser could start on the first one. That
    bought about two seconds, and it cost far more than it bought: the slices
    had to be ordered, counted, and watched for an ending, and every voice fault
    in this project came out of that bookkeeping (ADR-0028).

    One buffer has no ordering and no ending to infer. It is simply over when it
    is over.

    One voice serves both languages: OpenAI's voices are multilingual, so
    nothing has to be selected per language or kept in sync with the answer.
    """
    resp = requests.post(
        OPENAI_TTS_URL,
        headers={"Authorization": "Bearer %s" % key,
                 "Content-Type": "application/json"},
        json={"model": OPENAI_TTS_MODEL, "voice": OPENAI_VOICE,
              "input": text, "response_format": "pcm"},
        timeout=timeout,
    )
    if resp.status_code != HTTP_OK:
        raise LLMError("openai tts %d: %s"
                       % (resp.status_code, resp.text[:ERROR_EXCERPT_CHARS]))
    return wrap_pcm_as_wav(resp.content, OPENAI_PCM_RATE)


def synthesize(text: str) -> Optional[bytes]:
    """Spoken audio for a reply, or None to let the browser use its own voice."""
    key = _openai_key()
    if not key:
        return None
    return synthesize_openai(text, key)


def transcribe(audio_bytes: bytes, mime_type: str = "audio/wav",
               timeout: int = TRANSCRIBE_TIMEOUT_SECONDS) -> Dict:
    """Speech to text, language preserved.

    Whisper is used when a Groq key is present and Gemini otherwise. The two
    are interchangeable here because transcription output is plain text - only
    the listener changes, never what the agent does with the words.

    Whisper large-v3 is the reference multilingual ASR model and is the better
    listener for Hebrew; Gemini keeps the system runnable on a single key.
    """
    groq = _groq_key()
    if groq:
        for attempt in range(GROQ_RETRIES):
            try:
                return _transcribe_groq(audio_bytes, mime_type, groq, timeout)
            except LLMError as exc:
                # Whisper allows 20 requests a minute. Waiting is far better
                # than falling back: Gemini's Hebrew transcription invents
                # content, which is worse than a short pause (ADR-0016).
                if "429" in str(exc) and attempt < GROQ_RETRIES - 1:
                    time.sleep(GROQ_RETRY_SECONDS)
                    continue
                print("groq transcription failed, falling back to gemini: %s" % exc)
                break
            except Exception as exc:
                print("groq transcription failed, falling back to gemini: %s" % exc)
                break
    return _transcribe_gemini(audio_bytes, mime_type, timeout)


def _groq_call(audio_bytes: bytes, mime_type: str, key: str, timeout: int,
               language: Optional[str] = None) -> Dict:
    ext = "wav" if "wav" in mime_type else "webm"
    form = {
        "model": GROQ_MODEL,
        # verbose_json reports the language Whisper decided on, which is the
        # only way to know a mis-detection happened.
        "response_format": "verbose_json",
        "temperature": "0",
        # Priming the decoder with the domain vocabulary measurably improves
        # airport codes, which Whisper otherwise renders phonetically
        # ("S F O" or "esefo").
        "prompt": "Airports, congestion, terminal expansion. "
                  "Codes: SFO, LAX, BOS, JFK, LGA, EWR, ANC, SNA, ORD, ATL.",
    }
    if language:
        form["language"] = language

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": "Bearer %s" % key},
        files={"file": ("speech.%s" % ext, audio_bytes, mime_type)},
        data=form,
        timeout=timeout,
    )
    if resp.status_code != HTTP_OK:
        raise LLMError("groq %d: %s"
                       % (resp.status_code, resp.text[:ERROR_EXCERPT_CHARS]))
    body = resp.json()
    return {"text": (body.get("text") or "").strip(),
            "language": body.get("language")}


def _normalise_language(name: Optional[str]) -> str:
    """Whisper reports "Hebrew", not "he".

    Applied where the value is compared rather than where it is received, so a
    raw name can never slip past the allow-list.
    """
    value = (name or "").strip().lower()
    return LANGUAGE_NAMES.get(value, value)


def _transcribe_groq(audio_bytes: bytes, mime_type: str, key: str,
                     timeout: int) -> Dict:
    """Transcribe, constrained to the two languages this interface speaks.

    **The script of the transcript decides the language, not the detector.**

    Whisper's own label is unreliable on short clips - it has reported Hebrew
    speech as English, and as Croatian. Trusting it made the reply language flip
    between turns for no reason the speaker could see. What cannot be wrong is
    the script actually produced: Hebrew characters mean Hebrew.

    The detector is still used, but only to catch its own mistake: if it names a
    language we do not support, the audio is transcribed again with Hebrew
    forced, because Hebrew is what gets mistaken. The script then decides.
    """
    first = _groq_call(audio_bytes, mime_type, key, timeout)
    detected = _normalise_language(first.get("language"))

    if detected in ALLOWED_LANGUAGES:
        return _groq_result(first["text"], corrected=False)

    forced = _groq_call(audio_bytes, mime_type, key, timeout, language="he")
    if _looks_hebrew(forced["text"]):
        return _groq_result(forced["text"], corrected=True)

    forced = _groq_call(audio_bytes, mime_type, key, timeout, language="en")
    return _groq_result(forced["text"], corrected=True)


def _is_silence_artefact(text: str) -> bool:
    """Did Whisper invent this from silence?

    Judged by what remains, not by what matches: the sign-offs are removed and
    the question is whether anything was left. A transcript made only of them
    came from a recording with nothing in it.
    """
    remainder = _SIGN_OFF.sub(" ", (text or "").strip())
    return not re.sub(r"[^\w]", "", remainder, flags=re.UNICODE)


def words_in(text: str) -> list:
    """Words, with punctuation and Hebrew niqqud out of the way."""
    return [w for w in re.split(r"[^\w']+", (text or "").lower()) if w]


def is_substantive(text: str, known_words=()) -> bool:
    """Is this a turn worth spending an agent round trip on?

    Two or more words always are - the failure being guarded against is the
    single-word fragment, and a real two-word question ("Anchorage long-haul?")
    must never be swallowed. One word passes only if it is an answer to what was
    just asked or an airport it could be naming.

    `known_words` comes from the snapshot rather than a list here, so a new
    airport in the data is understood without editing this module.
    """
    words = words_in(text)
    if len(words) >= 2:
        return True
    if not words:
        return False
    return words[0] in CONVERSATIONAL_SINGLE_WORDS or words[0] in known_words


def _groq_result(text: str, corrected: bool) -> Dict:
    """Language is read off the script, so it always matches what is displayed."""
    if _is_silence_artefact(text):
        text = ""
    hebrew = _looks_hebrew(text)
    return {
        "text": text,
        "is_rtl": hebrew,
        "language": "he" if hebrew else "en",
        "provider": "groq/whisper-large-v3" + (" (language corrected)"
                                               if corrected else ""),
    }


def _transcribe_gemini(audio_bytes: bytes, mime_type: str, timeout: int) -> Dict:
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": TRANSCRIBE_PROMPT},
                {"inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(audio_bytes).decode(),
                }},
            ],
        }],
        "generationConfig": {"temperature": 0.0},
    }
    resp = requests.post(ENDPOINT % (TRANSCRIBE_MODEL, _key()),
                         json=payload, timeout=timeout)
    body = resp.json()
    if "error" in body:
        raise LLMError("transcription failed - %s" % body["error"].get("message"))

    parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return {"text": text, "is_rtl": _looks_hebrew(text), "provider": TRANSCRIBE_MODEL}


def _looks_hebrew(text: str) -> bool:
    return any("֐" <= c <= "׿" for c in text)


def wrap_pcm_as_wav(pcm: bytes, rate: int = PCM_SAMPLE_RATE,
                    channels: int = PCM_CHANNELS, bits: int = PCM_BITS) -> bytes:
    buf = io.BytesIO()
    byte_rate = rate * channels * bits // BITS_PER_BYTE
    block_align = channels * bits // BITS_PER_BYTE
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", WAV_HEADER_BYTES + len(pcm)))
    buf.write(b"WAVEfmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, channels, rate,
                          byte_rate, block_align, bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", len(pcm)))
    buf.write(pcm)
    return buf.getvalue()


def spoken_summary(answer: str, limit: int = 420) -> str:
    """Strip markdown and trim to something worth listening to.

    Tables are dropped entirely rather than read aloud: a spoken answer wants
    the prose, and a row of numbers read cell by cell is unusable.

    The limit is deliberately short. An unabridged answer synthesised to ~70
    seconds of audio and took as long again to generate; the full text is
    already on screen, so the spoken version is the headline, not a recital.
    Trimming happens on a sentence boundary so the reply never cuts mid-word.
    """
    kept = []
    for line in answer.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") or set(stripped) <= set("-|: "):
            continue
        kept.append(stripped)
    text = " ".join(l for l in kept if l)
    for ch in "#*`_":
        text = text.replace(ch, "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # A bare rfind(".") lands inside decimals - a score of "74.2" truncated to
    # "74." reads as a different number. Only a terminator followed by a space
    # is a sentence boundary.
    stop = max((m.end() for m in re.finditer(r"[.?!]\s", cut)), default=-1)
    return cut[:stop].rstrip() if stop > limit // 2 else cut.rstrip()

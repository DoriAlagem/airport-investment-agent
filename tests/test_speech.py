"""Transcription is constrained to the two languages this interface speaks.

Whisper auto-detects across a hundred languages, and short or noisy Hebrew is
readily heard as Croatian - producing fluent, confident text for a question
nobody asked. The agent then answers that question, and nothing in the reply
reveals the substitution.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airport_intel import speech  # noqa: E402


def _stub(monkey_results):
    """Replace the network call with a scripted sequence, recording arguments."""
    calls = []

    def fake(audio, mime, key, timeout, language=None):
        calls.append(language)
        return monkey_results.pop(0)

    return fake, calls


def run(results):
    fake, calls = _stub(list(results))
    original = speech._groq_call
    speech._groq_call = fake
    try:
        out = speech._transcribe_groq(b"audio", "audio/wav", "key", 10)
    finally:
        speech._groq_call = original
    return out, calls


def test_english_is_accepted_without_a_second_call():
    out, calls = run([{"text": "Which airports in New England?", "language": "en"}])
    assert calls == [None], "one call only"
    assert out["language"] == "en"
    assert "corrected" not in out["provider"]


def test_script_overrides_a_wrong_detection():
    """Whisper has labelled Hebrew speech "English".

    The label is a guess; the script is not. Hebrew characters mean Hebrew
    whatever the detector said - otherwise the reply language flips between
    turns for no visible reason.
    """
    out, calls = run([{"text": "אילו שדות תעופה בניו אינגלנד", "language": "en"}])
    assert calls == [None], "no second call needed - the text speaks for itself"
    assert out["language"] == "he"
    assert out["is_rtl"] is True


def test_latin_script_labelled_hebrew_is_treated_as_english():
    out, _ = run([{"text": "Which airports in New England?", "language": "he"}])
    assert out["language"] == "en"
    assert out["is_rtl"] is False


def test_hebrew_is_accepted_without_a_second_call():
    out, calls = run([{"text": "אילו שדות תעופה", "language": "he"}])
    assert calls == [None]
    assert out["is_rtl"] is True
    assert "corrected" not in out["provider"]


def test_a_third_language_is_re_transcribed_as_hebrew():
    """The real failure: Hebrew speech heard as Croatian."""
    out, calls = run([
        {"text": "SFO je ucinjen za ucinjenje u Los Angelesu.", "language": "croatian"},
        {"text": "מה המצב בסן פרנסיסקו", "language": "he"},
    ])
    assert calls == [None, "he"], "detect, then force Hebrew"
    assert out["language"] == "he"
    assert "corrected" in out["provider"]
    assert "Angelesu" not in out["text"]


def test_falls_through_to_english_when_hebrew_yields_no_hebrew():
    """English misheard as another Latin-script language: forcing Hebrew
    produces nothing Hebrew, so English is the remaining answer."""
    out, calls = run([
        {"text": "Was ist der Status", "language": "german"},
        {"text": "gibberish with no hebrew", "language": "he"},
        {"text": "What is the status of SFO", "language": "en"},
    ])
    assert calls == [None, "he", "en"]
    assert out["language"] == "en"
    assert out["is_rtl"] is False


def test_language_names_are_normalised():
    """Whisper reports 'Hebrew', not 'he'."""
    out, _ = run([{"text": "מה המצב בסן פרנסיסקו", "language": "hebrew"}])
    assert out["language"] == "he"


def test_silence_artefacts_are_discarded():
    """Whisper answers silence with a phrase from its training data.

    "Thank you" and "תודה" are the usual ones. Passing them through starts a
    conversation the user never began - and the agent answers it politely,
    which is how a recording of nothing became three turns of small talk.
    """
    out, _ = run([{"text": "Thank you.", "language": "en"}])
    assert out["text"] == ""
    out, _ = run([{"text": "תודה רבה", "language": "he"}])
    assert out["text"] == ""


def test_the_whole_sign_off_family_is_discarded():
    """The wording varies; the family does not.

    An exact-match list held "thank you" and let "Thank you for watching!
    Please subscribe to my channel!" through. It was answered in English, and
    that answer flipped a Hebrew conversation permanently (ADR-0026).
    """
    for text in [
        "Thank you for watching! Please subscribe to my channel!",
        "Thanks for watching, see you next time!",
        "Please subscribe to my channel",
        "Subtitles by the Amara.org community",
        "Bye bye",
        "תודה שצפיתם",
        "להתראות",
    ]:
        out, _ = run([{"text": text, "language": "en"}])
        assert out["text"] == "", text


def test_a_sign_off_attached_to_a_real_question_survives():
    """Judged by what is left, so politeness does not delete the question."""
    out, _ = run([{"text": "Thanks, and what about Boston?", "language": "en"}])
    assert out["text"] == "Thanks, and what about Boston?"
    out, _ = run([{"text": "תודה, ומה לגבי בוסטון", "language": "he"}])
    assert out["text"] == "תודה, ומה לגבי בוסטון"


def test_a_real_greeting_survives():
    """Rejecting every short phrase would silence real turns."""
    out, _ = run([{"text": "שלום", "language": "he"}])
    assert out["text"] == "שלום"


# --- conversation language ------------------------------------------------

def _agent():
    from airport_intel.agent import Agent
    a = Agent.__new__(Agent)          # no store or API key needed
    a.history = []
    a.language = None
    return a


def test_language_is_set_by_the_first_turn():
    a = _agent()
    assert a._settle_language("he", "אילו שדות תעופה") == "he"
    assert a.language == "he"


def test_a_garbled_latin_fragment_does_not_switch_a_hebrew_conversation():
    """Whisper sometimes renders Hebrew speech in Latin letters.

    A short fragment of that is indistinguishable from English, and switching on
    it flipped the reply language mid-conversation for no visible reason.
    """
    a = _agent()
    a._settle_language("he", "אילו שדות תעופה בניו אינגלנד")
    assert a._settle_language("en", "ma hamatzav") == "he", "too short to be decisive"
    assert a._settle_language("en", "ve ma legabey") == "he"


def test_a_real_english_sentence_does_switch():
    a = _agent()
    a._settle_language("he", "אילו שדות תעופה")
    assert a._settle_language(
        "en", "And what about Boston Logan compared with Bradley?") == "en"


def test_hebrew_script_always_wins():
    a = _agent()
    a._settle_language("en", "Which airports in New England are candidates?")
    assert a._settle_language("he", "ומה לגבי בוסטון") == "he"


def test_an_unrecognised_language_leaves_the_conversation_alone():
    a = _agent()
    a._settle_language("he", "אילו שדות תעופה")
    assert a._settle_language(None, "???") == "he"


# --- single-word fragments never reach the agent (ADR-0026) -----------------
#
# Observed live: a keystroke transcribed as "the" and the assistant's own voice
# leaking past echo cancellation as "sound" each bought a full agent round trip,
# then sat in the history so the next fragment was answered against them.

VOCABULARY = {"bos", "sfo", "boston", "anchorage"}


def test_a_bare_fragment_is_not_a_question():
    assert not speech.is_substantive("the", VOCABULARY)
    assert not speech.is_substantive("sound", VOCABULARY)
    assert not speech.is_substantive("  ...  ", VOCABULARY)
    assert not speech.is_substantive("", VOCABULARY)


def test_two_words_are_always_enough():
    # The gate must never swallow a real question, however terse.
    assert speech.is_substantive("Anchorage long-haul?", VOCABULARY)
    assert speech.is_substantive("למה?  כמה", VOCABULARY)


def test_one_word_naming_an_airport_passes():
    assert speech.is_substantive("Boston", VOCABULARY)
    assert speech.is_substantive("SFO?", VOCABULARY)


def test_one_word_answering_the_previous_turn_passes():
    for word in ["yes", "why", "again", "כן", "למה", "hello"]:
        assert speech.is_substantive(word, VOCABULARY), word


def test_the_vocabulary_comes_from_the_snapshot_not_a_list():
    # An airport the module has never heard of is understood once it is in the
    # data. Nothing in speech.py needs to change.
    assert not speech.is_substantive("Napaskiak", VOCABULARY)
    assert speech.is_substantive("Napaskiak", VOCABULARY | {"napaskiak"})

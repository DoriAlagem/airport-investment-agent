"""Tests for place-name resolution.

Every case here is a bug that actually happened, or one of the same shape.
Fuzzy geography is the least deterministic part of the system and was the least
tested; these are the regressions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airport_intel import geography  # noqa: E402


# --- word boundaries -------------------------------------------------------


def test_region_is_not_shadowed_by_a_metro_substring():
    """"New England" once resolved to Los Angeles.

    The metro key "la" appears inside "eng-la-nd", and substring matching found
    it. A regional question silently became a question about one airport in
    California (ADR-0012 correction 4).
    """
    assert geography.match_metro("New England") is None
    name, regions = geography.match_region("New England")
    assert name == "new england"
    assert "US-MA" in regions and "US-VT" in regions


def test_other_substring_collisions_do_not_fire():
    for query in ("Rhode Island", "Maryland", "Oakland", "Portland"):
        metro = geography.match_metro(query)
        assert metro is None or query.lower().startswith(metro[0]), query


def test_metro_still_matches_as_a_whole_word():
    name, codes = geography.match_metro("the LA airports")
    assert codes[0] == "LAX"
    assert "SNA" in codes


# --- metros ----------------------------------------------------------------


def test_multi_airport_metros_return_primary_first():
    """The agent proceeds on a stated assumption rather than asking, so the
    primary reading must be first and the alternates must be present."""
    for query, primary in [("New York", "JFK"), ("Chicago", "ORD"),
                           ("San Francisco", "SFO"), ("Washington", "DCA")]:
        name, codes = geography.match_metro(query)
        assert codes[0] == primary, query
        assert len(codes) > 1, query


def test_longest_metro_name_wins():
    """"san francisco" must not be shadowed by a shorter overlapping key."""
    name, codes = geography.match_metro("san francisco bay area")
    assert codes[0] == "SFO"


# --- states and regions ----------------------------------------------------


def test_state_names_resolve():
    assert geography.match_region("Texas")[1] == ["US-TX"]
    assert geography.match_region("airports in Vermont")[1] == ["US-VT"]


def test_new_england_covers_exactly_six_states():
    assert len(geography.REGIONS["new england"]) == 6


# --- out of scope ----------------------------------------------------------


def test_foreign_airports_are_recognised_by_code_and_by_name():
    """Out-of-scope and not-found are different answers, and the difference
    matters: one is a scoping decision, the other is a failure (ADR-0009)."""
    assert geography.match_foreign("LHR")[0] == "LHR"
    assert geography.match_foreign("Heathrow")[0] == "LHR"
    assert geography.match_foreign("what about Frankfurt")[0] == "FRA"


def test_us_places_are_not_mistaken_for_foreign_ones():
    for query in ("Boston", "New England", "SFO", "Santa Ana"):
        assert geography.match_foreign(query) is None, query


def test_a_city_name_alone_does_not_claim_a_foreign_airport():
    """"London Ontario" is not Heathrow.

    A length rule was tried first and does not work: "London" is six letters,
    so it cleared the threshold and the query resolved to the wrong continent
    with full confidence. What identifies an airport is the part after the
    city.
    """
    assert geography.match_foreign("London Ontario") is None
    assert geography.match_foreign("Heathrow")[0] == "LHR"
    assert geography.match_foreign("London Heathrow")[0] == "LHR"


def test_the_airport_specific_word_is_enough():
    """People say "Narita", not "Tokyo Narita"."""
    for word, code in [("Narita", "NRT"), ("Schiphol", "AMS"),
                       ("Changi", "SIN"), ("Charles de Gaulle", "CDG")]:
        assert geography.match_foreign("how busy is %s" % word)[0] == code


def test_a_single_word_name_still_matches_itself():
    """"Frankfurt" is only a city, so the city has to be enough."""
    assert geography.match_foreign("Frankfurt")[0] == "FRA"
    assert geography.match_foreign("Dubai")[0] == "DXB"


def test_a_short_word_from_a_foreign_name_claims_nothing():
    """"Mexico City" must not let the word "city" claim other questions.

    This pins MIN_DISTINCTIVE_WORD. Without it the threshold can be lowered to
    1 and the whole suite still passes, while "Kansas City" starts resolving to
    Mexico City airport — found by mutation testing, not by reading.
    """
    assert geography.match_foreign("how busy is Kansas City") is None
    assert geography.match_foreign("Salt Lake City") is None
    # the full name still matches, because the phrase is unambiguous
    assert geography.match_foreign("how busy is Mexico City")[0] == "MEX"

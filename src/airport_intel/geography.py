"""Human geography: the fuzzy names people actually use for places.

"New England", "the LA airports" and "Santa Ana" are not columns in any
dataset. This module turns them into airport codes.

Multi-airport metros return a primary match plus alternates so the agent can
proceed on a stated assumption rather than stopping to ask (ADR-0012 correction
4). The behaviour is general rather than special-cased for Los Angeles: New
York, Chicago, Washington, Houston and the Bay Area all raise the same
ambiguity.
"""
from typing import Dict, List, Optional, Tuple

# Named regions -> ISO region codes as they appear in OurAirports.
REGIONS: Dict[str, List[str]] = {
    "new england": ["US-CT", "US-ME", "US-MA", "US-NH", "US-RI", "US-VT"],
    "northeast": ["US-CT", "US-ME", "US-MA", "US-NH", "US-RI", "US-VT",
                  "US-NY", "US-NJ", "US-PA"],
    "mid-atlantic": ["US-NY", "US-NJ", "US-PA", "US-DE", "US-MD", "US-VA",
                     "US-DC", "US-WV"],
    "southeast": ["US-FL", "US-GA", "US-SC", "US-NC", "US-TN", "US-AL",
                  "US-MS", "US-KY"],
    "midwest": ["US-OH", "US-MI", "US-IN", "US-IL", "US-WI", "US-MN",
                "US-IA", "US-MO", "US-ND", "US-SD", "US-NE", "US-KS"],
    "southwest": ["US-AZ", "US-NM", "US-TX", "US-OK", "US-NV"],
    "mountain west": ["US-CO", "US-UT", "US-WY", "US-MT", "US-ID"],
    "pacific northwest": ["US-WA", "US-OR", "US-ID"],
    "west coast": ["US-CA", "US-OR", "US-WA"],
    "california": ["US-CA"],
    "texas": ["US-TX"],
    "florida": ["US-FL"],
    "alaska": ["US-AK"],
    "hawaii": ["US-HI"],
}

# Metro areas served by several airports. First code is the primary reading.
METROS: Dict[str, List[str]] = {
    "los angeles": ["LAX", "BUR", "LGB", "ONT", "SNA"],
    "la": ["LAX", "BUR", "LGB", "ONT", "SNA"],
    "new york": ["JFK", "LGA", "EWR", "HPN", "ISP"],
    "nyc": ["JFK", "LGA", "EWR", "HPN", "ISP"],
    "chicago": ["ORD", "MDW"],
    "washington": ["DCA", "IAD", "BWI"],
    "dc": ["DCA", "IAD", "BWI"],
    "san francisco": ["SFO", "OAK", "SJC"],
    "bay area": ["SFO", "OAK", "SJC"],
    "houston": ["IAH", "HOU"],
    "dallas": ["DFW", "DAL"],
    "miami": ["MIA", "FLL", "PBI"],
    "south florida": ["MIA", "FLL", "PBI"],
    "boston": ["BOS", "MHT", "PVD"],
    "orange county": ["SNA"],
    "santa ana": ["SNA"],
}

STATES: Dict[str, str] = {
    "alabama": "US-AL", "alaska": "US-AK", "arizona": "US-AZ",
    "arkansas": "US-AR", "california": "US-CA", "colorado": "US-CO",
    "connecticut": "US-CT", "delaware": "US-DE", "florida": "US-FL",
    "georgia": "US-GA", "hawaii": "US-HI", "idaho": "US-ID",
    "illinois": "US-IL", "indiana": "US-IN", "iowa": "US-IA",
    "kansas": "US-KS", "kentucky": "US-KY", "louisiana": "US-LA",
    "maine": "US-ME", "maryland": "US-MD", "massachusetts": "US-MA",
    "michigan": "US-MI", "minnesota": "US-MN", "mississippi": "US-MS",
    "missouri": "US-MO", "montana": "US-MT", "nebraska": "US-NE",
    "nevada": "US-NV", "new hampshire": "US-NH", "new jersey": "US-NJ",
    "new mexico": "US-NM", "new york": "US-NY", "north carolina": "US-NC",
    "north dakota": "US-ND", "ohio": "US-OH", "oklahoma": "US-OK",
    "oregon": "US-OR", "pennsylvania": "US-PA", "rhode island": "US-RI",
    "south carolina": "US-SC", "south dakota": "US-SD", "tennessee": "US-TN",
    "texas": "US-TX", "utah": "US-UT", "vermont": "US-VT",
    "virginia": "US-VA", "washington": "US-WA", "west virginia": "US-WV",
    "wisconsin": "US-WI", "wyoming": "US-WY",
}

# Well-known non-US airports, so out-of-scope questions get a specific answer
# rather than "not found" (ADR-0009).
KNOWN_FOREIGN = {
    "LHR": "London Heathrow", "CDG": "Paris Charles de Gaulle",
    "FRA": "Frankfurt", "AMS": "Amsterdam Schiphol", "NRT": "Tokyo Narita",
    "HND": "Tokyo Haneda", "PEK": "Beijing Capital", "PVG": "Shanghai Pudong",
    "DXB": "Dubai", "SIN": "Singapore Changi", "HKG": "Hong Kong",
    "YYZ": "Toronto Pearson", "MEX": "Mexico City", "GRU": "Sao Paulo",
    "SYD": "Sydney", "ICN": "Seoul Incheon", "MAD": "Madrid", "BCN": "Barcelona",
    "FCO": "Rome Fiumicino", "MUC": "Munich", "ZRH": "Zurich", "IST": "Istanbul",
}


# A word from a foreign airport's name only identifies it if it is distinctive.
# "London" alone should not claim a query about London, Ontario.
MIN_DISTINCTIVE_WORD = 5


def _tokens(text: str) -> List[str]:
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
    return cleaned.split()


def _has_phrase(query: str, phrase: str) -> bool:
    """Whole-word phrase match.

    Substring matching is not safe here: the metro key "la" appears inside
    "New Eng-la-nd", which silently resolved a regional question to Los Angeles.
    Matching on token sequences rather than characters prevents that whole class
    of collision.
    """
    q, p = _tokens(query), _tokens(phrase)
    if not p or len(p) > len(q):
        return False
    return any(q[i:i + len(p)] == p for i in range(len(q) - len(p) + 1))


def match_region(query: str) -> Optional[Tuple[str, List[str]]]:
    """A named multi-state region, or a single state.

    Longest name first so "new york" is not shadowed by a shorter key.
    """
    for name in sorted(REGIONS, key=len, reverse=True):
        if _has_phrase(query, name):
            return name, REGIONS[name]
    for name in sorted(STATES, key=len, reverse=True):
        if _has_phrase(query, name):
            return name, [STATES[name]]
    return None


def match_metro(query: str) -> Optional[Tuple[str, List[str]]]:
    """A metro area served by more than one airport.

    Longest name first, so "san francisco" is not shadowed by a shorter key.
    """
    for name in sorted(METROS, key=len, reverse=True):
        if _has_phrase(query, name):
            return name, METROS[name]
    return None


def match_foreign(query: str) -> Optional[Tuple[str, str]]:
    """Recognise well-known non-US airports so out-of-scope gets a real answer.

    Matches the code, the full name, or the airport-specific part of the name -
    people say "Heathrow", not "London Heathrow".

    The city is deliberately not enough on its own. A length rule was tried and
    does not work: "London" is six letters, so it cleared the threshold and
    "London Ontario" resolved to Heathrow - a confident answer about the wrong
    continent. What identifies the airport is the part after the city, so that
    is what is matched.
    """
    tokens = _tokens(query)
    upper = [t.upper() for t in tokens]
    for code, name in KNOWN_FOREIGN.items():
        if code in upper or _has_phrase(query, name):
            return code, name
        if any(w in tokens for w in _distinctive_words(name)):
            return code, name
    return None


def _distinctive_words(name: str) -> List[str]:
    """The part of an airport's name that identifies it rather than its city.

    "London Heathrow" -> heathrow. "Frankfurt" -> frankfurt, because a name
    that is only a city has nothing else to offer. Short words are dropped:
    "Mexico City" contributes nothing, and matching on "city" would claim every
    question containing the word.
    """
    words = _tokens(name)
    candidates = words[1:] if len(words) > 1 else words
    return [w for w in candidates if len(w) >= MIN_DISTINCTIVE_WORD]

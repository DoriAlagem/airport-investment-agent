"""Tests for effective runway count.

Coordinates below are real, taken from OurAirports, so the assertions are
against actual airfields rather than invented geometry.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airport_intel.etl.runways import (  # noqa: E402
    INDEPENDENT_SEPARATION_FT,
    effective_runways,
)


def rwy(le, lat, lon, heading, length=10000):
    return {"le": le, "lat": lat, "lon": lon, "heading": heading,
            "length_ft": length}


# Real thresholds, two pairs 747 ft and 748 ft apart.
SFO = [
    rwy("10L", 37.628742, -122.393410, 100.0),
    rwy("10R", 37.626298, -122.393124, 100.0),
    rwy("1L", 37.607898, -122.382950, 10.0),
    rwy("1R", 37.606333, -122.381061, 10.0),
]

# Five parallels; adjacent pairs ~1,000 ft apart, groups ~4,200-4,400 ft apart.
ATL = [
    rwy("08L", 33.649502, -84.439003, 90.0),
    rwy("08R", 33.646801, -84.438400, 90.0),
    rwy("09L", 33.634701, -84.447998, 90.0),
    rwy("09R", 33.631802, -84.447998, 90.0),
    rwy("10", 33.620300, -84.447899, 90.0),
]

# Two closely-spaced pairs, the complexes ~4,500 ft apart.
LAX = [
    rwy("6L", 33.949119, -118.431187, 70.0),
    rwy("6R", 33.946820, -118.434693, 70.0),
    rwy("7L", 33.935556, -118.422089, 70.0),
    rwy("7R", 33.933659, -118.419074, 70.0),
]


def test_sfo_collapses_to_two():
    """The case this exists for.

    Four runways in two pairs 747 ft apart. In poor visibility each pair is one
    usable stream, so dividing traffic by four made SFO look like it had
    airfield capacity to spare (ADR-0023).
    """
    assert effective_runways(SFO) == 2


def test_atlanta_does_not_over_collapse():
    """ATL runs three simultaneous arrival streams and must keep them.

    A naive chain of pairwise comparisons would merge all five parallels into
    one or two groups, because each adjacent gap is small relative to the total
    spread.
    """
    assert effective_runways(ATL) == 3


def test_lax_keeps_its_two_complexes():
    assert effective_runways(LAX) == 2


def test_result_is_order_independent():
    """Runway rows arrive in arbitrary order; the answer must not depend on it."""
    import itertools
    for permutation in itertools.islice(itertools.permutations(ATL), 12):
        assert effective_runways(list(permutation)) == 3


def test_effective_never_exceeds_the_real_count():
    for airfield in (SFO, ATL, LAX):
        assert 1 <= effective_runways(airfield) <= len(airfield)


def test_single_runway_stays_one():
    assert effective_runways([rwy("09", 32.733556, -117.189667, 90.0)]) == 1


def test_crossing_runways_are_separate_alignments():
    """Runways at right angles are not parallel and are counted separately,
    even though in practice they cannot be used simultaneously - a documented
    overstatement (ADR-0023)."""
    crossing = [rwy("04", 42.36, -71.01, 40.0), rwy("15", 42.36, -71.01, 150.0)]
    assert effective_runways(crossing) == 2


def test_widely_spaced_parallels_stay_independent():
    """A pair well beyond the separation minimum must not be merged.

    Note the offset is in LONGITUDE: these runways point north-south, so
    separation between them runs east-west. Displacing them in latitude would
    move them along their own length, not apart - which is exactly the mistake
    the perpendicular projection exists to avoid.
    """
    far = [rwy("18L", 33.00, -97.000, 180.0), rwy("18R", 33.00, -97.020, 180.0)]
    assert effective_runways(far) == 2


def test_offset_along_the_runway_is_not_separation():
    """Two runways nose-to-tail on the same alignment are one strip of
    airspace, not two independent streams."""
    inline = [rwy("18L", 33.00, -97.00, 180.0), rwy("18R", 33.04, -97.00, 180.0)]
    assert effective_runways(inline) == 1


def test_short_strips_are_ignored_by_the_caller():
    """Length filtering happens before this function; a strip too short for
    air-carrier aircraft adds no capacity however it is aligned."""
    assert effective_runways([]) == 0


def test_separation_threshold_is_the_faa_dependent_minimum():
    assert INDEPENDENT_SEPARATION_FT == 2500.0

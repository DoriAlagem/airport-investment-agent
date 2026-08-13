"""Effective runway count — how many independent streams an airport really has.

Counting runways overstates capacity wherever parallels sit too close to be
operated separately. SFO has four runways in two pairs 747 ft apart; in poor
visibility each pair collapses to one usable strip, so SFO behaves like a
two-runway airport. Dividing traffic by four made it look like it had airfield
capacity to spare, and understated its score (ADR-0023).

The rule is geometric and applies everywhere - no airport is special-cased.
"""
import math
from typing import Dict, List

import duckdb

from ..config import RAW_DIR

# FAA separation below which parallel runways cannot be operated as independent
# streams at all. The full simultaneous-independent-approach standard is
# ~4,300 ft, but applying that collapses Atlanta to two effective runways when
# it demonstrably runs three arrival streams. 2,500 ft is the conservative bar:
# closer than this and the pair is one stream under any procedure.
INDEPENDENT_SEPARATION_FT = 2500.0

# Separation is measured between runway THRESHOLD coordinates, not centrelines,
# so a runway pair built exactly to the standard can measure tens of feet under
# it. A 5% tolerance absorbs that. Seattle is the case in point: its outer
# parallels measure 2,462 ft against a 2,500 ft design, and it demonstrably runs
# two independent arrival streams.
SEPARATION_TOLERANCE = 0.95

# Runways within this many degrees of each other count as parallel. Generous
# because designators round to the nearest ten degrees, so a single physical
# alignment can appear as both "08" and "09" - as it does at Atlanta.
PARALLEL_TOLERANCE_DEG = 20.0

# Below this length a strip cannot take the aircraft this thesis is about, so
# it adds no air-carrier capacity however it is aligned.
MIN_USABLE_LENGTH_FT = 4000

FT_PER_DEG_LAT = 364_000.0


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE VIEW oa_runways_raw AS
        SELECT * FROM read_csv_auto('%s', union_by_name=true)
    """ % (RAW_DIR / "runways.csv"))

    rows = con.execute("""
        SELECT airport_ident        AS ident,
               le_ident             AS le,
               TRY_CAST(length_ft AS DOUBLE)        AS length_ft,
               TRY_CAST(le_latitude_deg AS DOUBLE)  AS lat,
               TRY_CAST(le_longitude_deg AS DOUBLE) AS lon,
               TRY_CAST(le_heading_degT AS DOUBLE)  AS heading
        FROM oa_runways_raw
        WHERE COALESCE(TRY_CAST(closed AS INTEGER), 0) = 0
          -- Helipads and water landing areas are not runways; their identifiers
          -- do not follow the numeric convention, which is how they are excluded.
          AND regexp_matches(COALESCE(le_ident, ''), '^[0-9]{1,2}[LRC]?$')
          -- Geometry needs coordinates. Runways without them still count
          -- towards the raw total, but cannot be placed relative to each other.
          AND le_latitude_deg IS NOT NULL
          AND le_longitude_deg IS NOT NULL
    """).fetchall()

    by_airport: Dict[str, List[Dict]] = {}
    for ident, le, length_ft, lat, lon, heading in rows:
        by_airport.setdefault(ident, []).append({
            "le": le, "length_ft": length_ft, "lat": lat,
            "lon": lon, "heading": heading,
        })

    records = []
    for ident, runways in by_airport.items():
        usable = [r for r in runways
                  if (r["length_ft"] or 0) >= MIN_USABLE_LENGTH_FT]
        records.append((
            ident,
            len(runways),
            len(usable),
            effective_runways(usable) if usable else 0,
        ))

    con.execute("""
        CREATE OR REPLACE TABLE runway_geometry (
            ident TEXT, runway_count INTEGER,
            usable_runway_count INTEGER, effective_runway_count INTEGER)
    """)
    con.executemany("INSERT INTO runway_geometry VALUES (?, ?, ?, ?)", records)


def effective_runways(runways: List[Dict]) -> int:
    """Independent streams available, summed across alignments.

    Runways are grouped by alignment, then each group is split into clusters
    that are far enough apart to run separately.
    """
    if not runways:
        return 0
    total = 0
    for group in _by_alignment(runways):
        total += _independent_clusters(group)
    return max(total, 1)


def _heading_of(runway: Dict) -> float:
    """True heading, falling back to the designator when it is missing."""
    heading = runway.get("heading")
    if heading is not None and heading == heading:
        return float(heading) % 180.0
    digits = "".join(c for c in (runway.get("le") or "") if c.isdigit())
    return (int(digits) * 10.0) % 180.0 if digits else 0.0


def _by_alignment(runways: List[Dict]) -> List[List[Dict]]:
    """Cluster runways into parallel families, tolerant of designator rounding."""
    remaining = sorted(runways, key=_heading_of)
    groups: List[List[Dict]] = []
    for runway in remaining:
        heading = _heading_of(runway)
        for group in groups:
            # Compare against the group's first member rather than its last, so
            # a chain of small differences cannot drift a family off-axis.
            delta = abs(heading - _heading_of(group[0]))
            delta = min(delta, 180.0 - delta)     # 179 deg and 1 deg are parallel
            if delta <= PARALLEL_TOLERANCE_DEG:
                group.append(runway)
                break
        else:
            groups.append([runway])
    return groups


def _independent_clusters(group: List[Dict]) -> int:
    """How many separate streams a parallel family supports.

    Each threshold is projected onto the axis perpendicular to the runways,
    giving a one-dimensional position. Sorting by that position makes the
    result independent of input order - a chain of pairwise comparisons in
    arbitrary order would not be.
    """
    if len(group) == 1:
        return 1

    positions = sorted(_perpendicular_offsets(group))
    clusters, anchor = 1, positions[0]
    for offset in positions[1:]:
        if offset - anchor >= INDEPENDENT_SEPARATION_FT * SEPARATION_TOLERANCE:
            clusters += 1
            anchor = offset
    return clusters


def _perpendicular_offsets(group: List[Dict]) -> List[float]:
    """Offsets in feet along the axis normal to the runway alignment.

    A local flat-earth projection is used rather than great-circle distance:
    these separations are measured in hundreds of feet across a single
    airfield, where the curvature error is far below the precision of the
    threshold being applied.
    """
    theta = math.radians(sum(_heading_of(r) for r in group) / len(group))
    nx, ny = math.cos(theta), -math.sin(theta)

    lat0 = sum(r["lat"] for r in group) / len(group)
    lon0 = sum(r["lon"] for r in group) / len(group)
    ft_per_deg_lon = FT_PER_DEG_LAT * math.cos(math.radians(lat0))

    offsets = []
    for runway in group:
        dx = (runway["lon"] - lon0) * ft_per_deg_lon
        dy = (runway["lat"] - lat0) * FT_PER_DEG_LAT
        offsets.append(dx * nx + dy * ny)
    return offsets

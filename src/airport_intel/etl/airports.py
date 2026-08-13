"""Build the airport dimension: identity, geography, physical plant, peer tier.

The universe starts from airports that actually appear in T-100 with US origins,
not from the ~80k rows of OurAirports. OurAirports supplies coordinates, region
and runways; T-100 decides who exists (ADR-0009).

Hub tiers follow the federal definition in 49 U.S.C. 47102, expressed as a share
of national enplanements. Using the existing classification rather than
inventing size bands removes one arbitrary parameter from the design.
"""
import duckdb

from ..config import RAW_DIR

# 49 U.S.C. 47102, as shares of total US annual enplanements.
LARGE_HUB = 0.01
MEDIUM_HUB = 0.0025
SMALL_HUB = 0.0005


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE VIEW oa_airports AS
        SELECT * FROM read_csv_auto('%s', union_by_name=true)
    """ % (RAW_DIR / "airports.csv"))

    con.execute("""
        CREATE OR REPLACE VIEW oa_runways AS
        SELECT * FROM read_csv_auto('%s', union_by_name=true)
    """ % (RAW_DIR / "runways.csv"))

    # Runway capacity drives the runway-vs-terminal constraint split (ADR-0006).
    # Closed runways are excluded: they are pavement, but not capacity.
    #
    # The count that matters is the EFFECTIVE one - parallels too close to be
    # operated separately are one stream, not two (ADR-0023). runway_geometry
    # is built by etl/runways.py.
    con.execute("""
        CREATE OR REPLACE TABLE runway_summary AS
        SELECT
            r.airport_ident                     AS ident,
            COUNT(*)                            AS runway_count,
            MAX(TRY_CAST(r.length_ft AS INTEGER)) AS longest_runway_ft,
            COALESCE(MAX(g.effective_runway_count), COUNT(*)) AS effective_runway_count
        FROM oa_runways r
        LEFT JOIN runway_geometry g ON g.ident = r.airport_ident
        WHERE COALESCE(TRY_CAST(r.closed AS INTEGER), 0) = 0
        GROUP BY r.airport_ident
    """)

    # Enplanements are approximated by passengers boarding scheduled service at
    # the airport. FAA counts revenue enplanements; the difference is immaterial
    # at the resolution tiers require.
    con.execute("""
        CREATE OR REPLACE TABLE airport_annual AS
        SELECT
            airport,
            year,
            SUM(sched_passengers)  AS enplanements,
            SUM(total_departures)  AS departures
        FROM t100_airport_month
        WHERE country = 'US'
        GROUP BY airport, year
    """)

    con.execute("""
        CREATE OR REPLACE TABLE airports AS
        WITH latest AS (
            SELECT MAX(year) AS y FROM airport_annual
        ),
        recent AS (
            SELECT a.airport, a.enplanements, a.departures
            FROM airport_annual a, latest
            WHERE a.year = latest.y
        ),
        shares AS (
            SELECT
                airport,
                enplanements,
                departures,
                enplanements / NULLIF(SUM(enplanements) OVER (), 0) AS pax_share
            FROM recent
        )
        SELECT
            s.airport                                   AS code,
            COALESCE(oa.name, s.airport)                AS name,
            oa.municipality                             AS city,
            oa.iso_region                               AS region,
            oa.latitude_deg                             AS lat,
            oa.longitude_deg                            AS lon,
            COALESCE(r.runway_count, 0)                 AS runway_count,
            COALESCE(r.effective_runway_count, r.runway_count, 0)
                                                        AS effective_runway_count,
            r.longest_runway_ft                         AS longest_runway_ft,
            s.enplanements,
            s.departures,
            s.pax_share,
            CASE
                WHEN s.pax_share >= %(large)s  THEN 'large'
                WHEN s.pax_share >= %(medium)s THEN 'medium'
                WHEN s.pax_share >= %(small)s  THEN 'small'
                ELSE 'nonhub'
            END                                         AS tier,
            oa.iso_region IS NULL                       AS unmatched_metadata
        FROM shares s
        LEFT JOIN oa_airports oa
               ON oa.iata_code = s.airport
              -- OurAirports codes territories by their own ISO country, so a
              -- plain 'US' filter silently drops San Juan, St Thomas and Guam.
              -- BTS and the FAA treat them as US airports, and SJU alone
              -- outranks most medium hubs.
              AND oa.iso_country IN ('US', 'PR', 'VI', 'GU', 'MP', 'AS')
        LEFT JOIN runway_summary r
               ON r.ident = oa.ident
    """ % {"large": LARGE_HUB, "medium": MEDIUM_HUB, "small": SMALL_HUB})

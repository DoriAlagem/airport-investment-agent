"""Aggregate T-100 segment data to per-airport-month and per-route facts.

T-100 is monthly totals per carrier x origin x destination x aircraft type. It
carries no clock times, so nothing here can speak about peak hours — that comes
from on-time data (ADR-0014). What it does carry, and nothing else does:
passengers, seats, and every flight including freight.

Two outputs:
  t100_airport_month  - the fullness and growth inputs, plus cargo share
  t100_routes         - route-level distances for long-haul share
"""
import duckdb

from ..config import (
    CARGO_CLASSES,
    LOAD_FACTOR_CLASSES,
    LONG_HAUL_MILES,
    PASSENGER_CLASSES,
)
from .common import glob_for


def _sql_list(values) -> str:
    return ", ".join("'%s'" % v for v in values)


def build(con: duckdb.DuckDBPyConnection) -> None:
    pax = _sql_list(PASSENGER_CLASSES)
    cargo = _sql_list(CARGO_CLASSES)
    sched = _sql_list(LOAD_FACTOR_CLASSES)

    con.execute("""
        CREATE OR REPLACE VIEW t100_raw AS
        SELECT * FROM read_csv_auto('%s', union_by_name=true)
        WHERE DEPARTURES_PERFORMED > 0
    """ % glob_for("t100"))

    # Rows with zero performed departures are filings for service that did not
    # operate. Keeping them would deflate every per-departure average.

    con.execute("""
        CREATE OR REPLACE TABLE t100_airport_month AS
        SELECT
            ORIGIN                                   AS airport,
            any_value(ORIGIN_STATE_ABR)              AS state,
            -- T-100 includes foreign origins whenever the other endpoint is
            -- US, so PVG and HKG appear alongside ORD. The fund invests in US
            -- assets, so the universe is filtered on this downstream.
            any_value(ORIGIN_COUNTRY)                AS country,
            CAST(YEAR AS INTEGER)                    AS year,
            CAST(MONTH AS INTEGER)                   AS month,

            SUM(DEPARTURES_PERFORMED)                AS total_departures,

            SUM(CASE WHEN CLASS IN (%(pax)s)
                     THEN DEPARTURES_PERFORMED ELSE 0 END)   AS pax_departures,
            SUM(CASE WHEN CLASS IN (%(cargo)s)
                     THEN DEPARTURES_PERFORMED ELSE 0 END)   AS cargo_departures,

            -- Load factor inputs: scheduled passenger service only, so that
            -- charter economics do not distort "are the planes full".
            SUM(CASE WHEN CLASS IN (%(sched)s) THEN SEATS ELSE 0 END)
                                                     AS sched_seats,
            SUM(CASE WHEN CLASS IN (%(sched)s) THEN PASSENGERS ELSE 0 END)
                                                     AS sched_passengers,

            SUM(CASE WHEN CLASS IN (%(pax)s) THEN PASSENGERS ELSE 0 END)
                                                     AS pax_passengers,

            SUM(CASE WHEN CLASS IN (%(pax)s) AND DEST_COUNTRY <> 'US'
                     THEN DEPARTURES_PERFORMED ELSE 0 END)
                                                     AS intl_pax_departures,
            SUM(CASE WHEN CLASS IN (%(pax)s) AND DISTANCE >= %(lh)d
                     THEN DEPARTURES_PERFORMED ELSE 0 END)
                                                     AS longhaul_pax_departures,
            SUM(CASE WHEN CLASS IN (%(cargo)s) AND DISTANCE >= %(lh)d
                     THEN DEPARTURES_PERFORMED ELSE 0 END)
                                                     AS longhaul_cargo_departures
        FROM t100_raw
        GROUP BY ORIGIN, YEAR, MONTH
    """ % {"pax": pax, "cargo": cargo, "sched": sched, "lh": LONG_HAUL_MILES})

    # Route-level facts back route_profile(). Aggregated per year rather than
    # per month: a single month of a seasonal route is noise, and the tool
    # answers "what does this airport's network look like", not "in March".
    con.execute("""
        CREATE OR REPLACE TABLE t100_routes AS
        SELECT
            ORIGIN                       AS airport,
            DEST                         AS dest,
            any_value(DEST_COUNTRY)      AS dest_country,
            CAST(YEAR AS INTEGER)        AS year,
            CASE WHEN CLASS IN (%(cargo)s) THEN 'cargo' ELSE 'passenger' END
                                         AS service,
            MAX(DISTANCE)                AS distance_miles,
            SUM(DEPARTURES_PERFORMED)    AS departures,
            SUM(PASSENGERS)              AS passengers,
            SUM(SEATS)                   AS seats
        FROM t100_raw
        GROUP BY ORIGIN, DEST, YEAR,
                 CASE WHEN CLASS IN (%(cargo)s) THEN 'cargo' ELSE 'passenger' END
    """ % {"cargo": cargo})

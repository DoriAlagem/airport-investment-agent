"""Aggregate flight-level on-time data to hourly and monthly airport facts.

This is the only source with clock times, so peak-hour saturation can come from
nowhere else. It is also passenger-only: freight carriers fall outside the
reporting rule, so cargo is invisible here by construction (ADR-0014).

Two outputs, both facts rather than judgments — thresholds are applied in the
scoring code, not baked into the tables (ADR-0011):

  ontime_hourly        - scheduled departures per airport per month per hour
  ontime_airport_month - departures, delay minutes decomposed by cause
"""
import duckdb

from .common import glob_for


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE VIEW ontime_raw AS
        SELECT
            Origin                                    AS airport,
            CAST(Year AS INTEGER)                     AS year,
            CAST(Month AS INTEGER)                    AS month,
            FlightDate                                AS flight_date,
            -- CRSDepTime is local hhmm as an integer; midnight files as 2400,
            -- which MOD folds back to hour 0.
            MOD(CAST(TRY_CAST(CRSDepTime AS INTEGER) / 100 AS INTEGER), 24) AS hour,
            COALESCE(TRY_CAST(Cancelled AS DOUBLE), 0)          AS cancelled,
            COALESCE(TRY_CAST(DepDel15 AS DOUBLE), 0)           AS del15,
            COALESCE(TRY_CAST(CarrierDelay AS DOUBLE), 0)       AS carrier_delay,
            COALESCE(TRY_CAST(WeatherDelay AS DOUBLE), 0)       AS weather_delay,
            COALESCE(TRY_CAST(NASDelay AS DOUBLE), 0)           AS nas_delay,
            COALESCE(TRY_CAST(SecurityDelay AS DOUBLE), 0)      AS security_delay,
            COALESCE(TRY_CAST(LateAircraftDelay AS DOUBLE), 0)  AS late_aircraft_delay
        FROM read_csv_auto('%s', union_by_name=true, ignore_errors=true)
        WHERE Origin IS NOT NULL AND TRY_CAST(CRSDepTime AS INTEGER) IS NOT NULL
    """ % glob_for("ontime"))

    # Cancelled flights still occupied a scheduled slot, so they count towards
    # how busy an hour was planned to be. They are excluded from delay
    # averages, which are per operated departure.
    con.execute("""
        CREATE OR REPLACE TABLE ontime_hourly AS
        SELECT
            airport,
            year,
            month,
            hour,
            COUNT(*)                        AS scheduled_flights,
            COUNT(DISTINCT flight_date)     AS days_observed
        FROM ontime_raw
        GROUP BY airport, year, month, hour
    """)

    con.execute("""
        CREATE OR REPLACE TABLE ontime_airport_month AS
        SELECT
            airport,
            year,
            month,
            COUNT(*)                                   AS scheduled_flights,
            SUM(1 - cancelled)                         AS operated_flights,
            SUM(cancelled)                             AS cancelled_flights,
            COUNT(DISTINCT flight_date)                AS days_in_month,
            SUM(del15)                                 AS delayed_15plus,

            -- Delay is used only in its capacity-attributable form. NAS delay
            -- is the volume/airspace bucket; weather and late-aircraft delay
            -- describe things a terminal cannot fix (ADR-0003).
            SUM(nas_delay)                             AS nas_delay_min,
            SUM(carrier_delay)                         AS carrier_delay_min,
            SUM(weather_delay)                         AS weather_delay_min,
            SUM(security_delay)                        AS security_delay_min,
            SUM(late_aircraft_delay)                   AS late_aircraft_delay_min
        FROM ontime_raw
        GROUP BY airport, year, month
    """)

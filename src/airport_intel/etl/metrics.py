"""Turn the fact tables into the raw metrics the score consumes.

One row per airport. These are still measurements, not judgments — no
percentiles, no weights, no thresholds beyond the ones that define a metric
(ADR-0011). The scoring code turns these into a ranking.

Windows differ by metric, which is a consequence of ADR-0013:
  fullness, peak saturation, capacity delay  -> the on-time window (12 months)
  growth                                     -> the T-100 window (36 months)
"""
import duckdb

from ..config import CARGO_MATERIALITY, PEAK_THRESHOLD


def build(con: duckdb.DuckDBPyConnection) -> None:
    _peak(con)
    _traffic(con)
    _growth(con)
    _combine(con)


def _peak(con: duckdb.DuckDBPyConnection) -> None:
    """Peak-hour saturation: how close a typical hour runs to the busiest hour.

    Measures flatness, not size. An airport with one morning rush has hours to
    grow into; one running near its maximum all day does not (ADR-0006).

    Expressed as median operating hour / peak hour. An earlier version counted
    hours reaching 80% of the peak, which proved fragile: a single spike hour
    sets the bar for the whole day, so LAX - busy 06:00-23:00 but with one
    outsized 08:00 spike - scored as though it were empty. The ratio measures
    the same property robustly and removes an arbitrary threshold (ADR-0015).

    Slot-controlled airports show the signature clearly: capping movements per
    hour flattens the profile, so LGA sits at 0.75 while LAX sits at 0.53.

    Computed per month and then averaged, so an airport saturated only in July
    scores below one saturated year-round.
    """
    con.execute("""
        CREATE OR REPLACE TABLE peak_by_month AS
        WITH days AS (
            SELECT airport, year, month, MAX(days_in_month) AS days
            FROM ontime_airport_month
            GROUP BY airport, year, month
        ),
        -- Divide by days in the month, not by days that hour saw traffic:
        -- an hour used twice a month is near-empty, and dividing by 2 would
        -- make it look busy.
        per_hour AS (
            SELECT h.airport, h.year, h.month, h.hour,
                   h.scheduled_flights::DOUBLE / NULLIF(d.days, 0) AS per_day
            FROM ontime_hourly h
            JOIN days d USING (airport, year, month)
        ),
        peaks AS (
            SELECT airport, year, month, MAX(per_day) AS peak_per_day
            FROM per_hour
            GROUP BY airport, year, month
        )
        SELECT
            p.airport,
            p.year,
            p.month,
            MAX(k.peak_per_day)                                   AS peak_hour_flights,
            -- An "operating hour" needs at least one flight on a typical day;
            -- otherwise 03:00 with a weekly freighter counts as part of the day.
            COUNT(*) FILTER (WHERE p.per_day >= 1.0)               AS operating_hours,
            MEDIAN(p.per_day) FILTER (WHERE p.per_day >= 1.0)      AS median_hour_flights,
            -- Retained for explanation, not scoring: "N hours a day run close
            -- to the peak" is a concrete sentence for an answer, even though
            -- the ratio above is what the score uses.
            COUNT(*) FILTER (WHERE p.per_day >= 1.0
                             AND p.per_day >= %(thr)s * k.peak_per_day)
                                                                  AS near_peak_hours
        FROM per_hour p
        JOIN peaks k USING (airport, year, month)
        GROUP BY p.airport, p.year, p.month
    """ % {"thr": PEAK_THRESHOLD})

    con.execute("""
        CREATE OR REPLACE TABLE peak_metrics AS
        SELECT
            airport,
            AVG(median_hour_flights / NULLIF(peak_hour_flights, 0)) AS peak_saturation,
            AVG(peak_hour_flights)                                  AS peak_hour_flights,
            AVG(median_hour_flights)                                AS median_hour_flights,
            AVG(near_peak_hours)                                    AS near_peak_hours,
            AVG(operating_hours)                                    AS operating_hours,
            COUNT(*)                                                AS months_present
        FROM peak_by_month
        WHERE operating_hours > 0
        GROUP BY airport
    """)


def _traffic(con: duckdb.DuckDBPyConnection) -> None:
    """Fullness, capacity delay, cargo share — over the on-time window.

    T-100 is trimmed to the on-time window here so fullness and delay describe
    the same period. Growth deliberately uses the longer window instead.
    """
    con.execute("""
        CREATE OR REPLACE TABLE ontime_window AS
        SELECT MIN(year * 100 + month) AS lo, MAX(year * 100 + month) AS hi
        FROM ontime_airport_month
    """)

    con.execute("""
        CREATE OR REPLACE TABLE traffic_metrics AS
        WITH t AS (
            SELECT m.*
            FROM t100_airport_month m, ontime_window w
            WHERE m.country = 'US'
              AND m.year * 100 + m.month BETWEEN w.lo AND w.hi
        ),
        t_agg AS (
            SELECT
                airport,
                SUM(sched_passengers)                        AS passengers,
                SUM(sched_seats)                             AS seats,
                SUM(total_departures)                        AS t100_departures,
                SUM(cargo_departures)                        AS cargo_departures,
                SUM(pax_departures)                          AS pax_departures,
                SUM(intl_pax_departures)                     AS intl_pax_departures,
                SUM(longhaul_pax_departures)                 AS longhaul_pax_departures,
                SUM(longhaul_cargo_departures)               AS longhaul_cargo_departures
            FROM t GROUP BY airport
        ),
        o_agg AS (
            SELECT
                airport,
                SUM(operated_flights)   AS operated_flights,
                SUM(scheduled_flights)  AS scheduled_flights,
                SUM(nas_delay_min)      AS nas_delay_min,
                SUM(weather_delay_min)  AS weather_delay_min,
                SUM(late_aircraft_delay_min) AS late_aircraft_delay_min,
                SUM(delayed_15plus)     AS delayed_15plus,
                COUNT(*)                AS ontime_months
            FROM ontime_airport_month GROUP BY airport
        )
        SELECT
            COALESCE(t_agg.airport, o_agg.airport)           AS airport,
            t_agg.passengers,
            t_agg.seats,
            t_agg.passengers / NULLIF(t_agg.seats, 0)        AS fullness,
            t_agg.t100_departures,
            t_agg.cargo_departures,
            t_agg.cargo_departures / NULLIF(t_agg.t100_departures, 0) AS cargo_share,
            t_agg.pax_departures,
            t_agg.intl_pax_departures,
            t_agg.longhaul_pax_departures,
            t_agg.longhaul_cargo_departures,
            o_agg.operated_flights,
            o_agg.scheduled_flights,
            o_agg.nas_delay_min,
            -- Only the volume/airspace bucket. Weather and late-aircraft delay
            -- describe problems a terminal cannot fix (ADR-0003).
            o_agg.nas_delay_min / NULLIF(o_agg.operated_flights, 0) AS capacity_delay,
            o_agg.delayed_15plus / NULLIF(o_agg.operated_flights, 0) AS delayed_share,
            o_agg.ontime_months,
            -- On-time covers only carriers above 0.5% of domestic passenger
            -- revenue, so this ratio is the honest measure of how much of the
            -- airport the hourly metrics actually saw (ADR-0010).
            o_agg.scheduled_flights / NULLIF(t_agg.pax_departures, 0) AS carrier_coverage
        FROM t_agg
        FULL OUTER JOIN o_agg USING (airport)
    """)


def _growth(con: duckdb.DuckDBPyConnection) -> None:
    """Passenger CAGR over the full T-100 window, plus the load-factor trend.

    Both are needed because of the asymmetric rule in ADR-0006: falling
    passengers only signal decline if the planes are emptying too. Falling
    passengers with rising load factor means capacity was withdrawn while
    demand held, which is a constraint signal, not a decay signal.
    """
    con.execute("""
        CREATE OR REPLACE TABLE growth_metrics AS
        WITH yearly AS (
            SELECT
                airport,
                year,
                SUM(sched_passengers) AS passengers,
                SUM(sched_passengers) / NULLIF(SUM(sched_seats), 0) AS load_factor
            FROM t100_airport_month
            WHERE country = 'US'
            GROUP BY airport, year
        ),
        bounds AS (
            SELECT airport, MIN(year) AS y0, MAX(year) AS y1
            FROM yearly GROUP BY airport
        ),
        endpoints AS (
            SELECT
                b.airport,
                b.y1 - b.y0                                   AS span,
                MAX(CASE WHEN y.year = b.y0 THEN y.passengers END)  AS pax_first,
                MAX(CASE WHEN y.year = b.y1 THEN y.passengers END)  AS pax_last,
                MAX(CASE WHEN y.year = b.y0 THEN y.load_factor END) AS lf_first,
                MAX(CASE WHEN y.year = b.y1 THEN y.load_factor END) AS lf_last
            FROM bounds b
            JOIN yearly y USING (airport)
            GROUP BY b.airport, b.y0, b.y1
        )
        SELECT
            airport,
            span                                              AS growth_years,
            pax_first,
            pax_last,
            lf_first,
            lf_last,
            lf_last - lf_first                                AS load_factor_change,
            CASE
                WHEN span > 0 AND pax_first > 0
                THEN POWER(pax_last / pax_first, 1.0 / span) - 1
            END                                               AS pax_cagr
        FROM endpoints
    """)


def _combine(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE airport_metrics AS
        SELECT
            a.code,
            a.name,
            a.city,
            a.region,
            a.lat,
            a.lon,
            a.tier,
            a.runway_count,
            a.effective_runway_count,
            a.longest_runway_ft,
            a.enplanements,
            a.departures                        AS annual_departures,

            p.peak_saturation,
            p.peak_hour_flights,
            p.median_hour_flights,
            p.near_peak_hours,
            p.operating_hours,
            p.months_present                    AS peak_months_present,

            t.fullness,
            t.capacity_delay,
            t.delayed_share,
            t.cargo_share,
            t.carrier_coverage,
            t.ontime_months,
            t.pax_departures,
            t.intl_pax_departures,
            t.longhaul_pax_departures,
            t.longhaul_cargo_departures,
            t.cargo_departures,

            g.pax_cagr,
            g.load_factor_change,
            g.growth_years,

            -- Runway-vs-terminal split. High load per runway means the
            -- pavement is the ceiling and a terminal will not help (ADR-0006).
            -- Divided by EFFECTIVE runways: SFO's four strips are two usable
            -- streams, and dividing by four made it look uncongested (ADR-0023).
            p.peak_hour_flights / NULLIF(a.effective_runway_count, 0)
                                                            AS peak_flights_per_runway,

            -- Cargo is invisible to every hourly metric, so where it is
            -- material the peak-hour figure is biased low. The flag travels
            -- with the score (ADR-0014).
            COALESCE(t.cargo_share, 0) >= %(mat)s            AS cargo_bias_flag
        FROM airports a
        LEFT JOIN peak_metrics    p ON p.airport = a.code
        LEFT JOIN traffic_metrics t ON t.airport = a.code
        LEFT JOIN growth_metrics  g ON g.airport = a.code
    """ % {"mat": CARGO_MATERIALITY})

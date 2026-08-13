"""Build the SQLite snapshot the chat application reads.

Runs the whole pipeline: unzip -> DuckDB aggregation -> SQLite. DuckDB is a
build-time engine and persists nothing; the only artefact is data/airports.db
(ADR-0011).

    python -m airport_intel.etl.build
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone

from ..config import DB_PATH, ensure_dirs
from . import airports, common, metrics, ontime, runways, t100

# Tables copied to SQLite. Facts only — scores are computed in Python at query
# time so the weights stay tunable without a rebuild.
EXPORT = ["airports", "airport_metrics", "t100_routes", "ontime_hourly"]


def _window(con, table):
    row = con.execute(
        "SELECT MIN(year * 100 + month), MAX(year * 100 + month) FROM %s" % table
    ).fetchone()
    if not row or row[0] is None:
        return None, None
    fmt = lambda v: "%d-%02d" % (v // 100, v % 100)
    return fmt(row[0]), fmt(row[1])


def build(db_path=DB_PATH) -> None:
    ensure_dirs()
    con = common.connect()

    print("extracting archives")
    n_t100 = len(common.extract("t100_", "t100"))
    n_ontime = len(common.extract("ontime_", "ontime"))
    print("  %d T-100 months, %d on-time months" % (n_t100, n_ontime))

    if not n_t100 or not n_ontime:
        raise SystemExit(
            "missing raw data - run python -m airport_intel.ingest.download first"
        )

    print("aggregating T-100")
    t100.build(con)
    print("aggregating on-time")
    ontime.build(con)
    print("computing runway geometry")
    runways.build(con)
    print("building airport dimension")
    airports.build(con)
    print("computing metrics")
    metrics.build(con)

    t100_lo, t100_hi = _window(con, "t100_airport_month")
    ontime_lo, ontime_hi = _window(con, "ontime_airport_month")

    # The two windows differ by design (ADR-0013) and answers must state which
    # one they rest on, so both are recorded rather than collapsed into one.
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "t100_window_start": t100_lo,
        "t100_window_end": t100_hi,
        "ontime_window_start": ontime_lo,
        "ontime_window_end": ontime_hi,
        "t100_months": str(n_t100),
        "ontime_months": str(n_ontime),
        "airports": str(con.execute("SELECT COUNT(*) FROM airports").fetchone()[0]),
    }

    print("writing %s" % db_path)
    if db_path.exists():
        db_path.unlink()
    sq = sqlite3.connect(db_path)
    try:
        for table in EXPORT:
            df = con.execute("SELECT * FROM %s" % table).df()
            df.to_sql(table, sq, index=False)
            print("  %-20s %7d rows" % (table, len(df)))

        sq.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        sq.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))

        sq.execute("CREATE INDEX idx_metrics_code ON airport_metrics(code)")
        sq.execute("CREATE INDEX idx_metrics_tier ON airport_metrics(tier)")
        sq.execute("CREATE INDEX idx_metrics_region ON airport_metrics(region)")
        sq.execute("CREATE INDEX idx_routes_airport ON t100_routes(airport)")
        sq.commit()
    finally:
        sq.close()

    print("\ndata windows: on-time %s..%s | T-100 %s..%s"
          % (ontime_lo, ontime_hi, t100_lo, t100_hi))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the SQLite snapshot.")
    p.add_argument("--db", default=str(DB_PATH))
    args = p.parse_args(argv)
    from pathlib import Path
    build(Path(args.db))
    return 0


if __name__ == "__main__":
    sys.exit(main())

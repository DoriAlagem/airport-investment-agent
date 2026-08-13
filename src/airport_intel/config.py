"""Paths and build-wide settings.

Everything the pipeline writes lives under DATA_DIR. Raw downloads are
disposable and gitignored; the SQLite snapshot is the committed artefact
(ADR-0011).
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
WORK_DIR = DATA_DIR / "work"  # unzipped CSVs, disposable
DB_PATH = DATA_DIR / "airports.db"

# Ingest windows differ by source, because the sources feed different things
# and their sizes differ by ~50x (ADR-0013).
#
#   T-100    ~0.5 MB/month  -> load factor + the 3-year growth trend (ADR-0002)
#   On-Time   ~27 MB/month  -> peak saturation + NAS delay, both current-state
#
# The expensive file is the one that does not need history, so it gets a
# 12-month window: enough for full seasonality, without a 6-hour download.
# Windows are post-pandemic so growth measures demand, not recovery (ADR-0006).
T100_START = "2023-01"
T100_END = "2025-12"

ONTIME_START = "2025-01"
ONTIME_END = "2025-12"

# BTS throttles to ~42 KB/s per connection but not per IP, so downloads are
# parallelised. Kept modest: this is a public government server.
DOWNLOAD_WORKERS = 8



# --- domain constants ------------------------------------------------------

# T-100 service classes. Freighters report near-zero seats against tens of
# thousands of departures, which is what makes the split reliable (ADR-0014).
PASSENGER_CLASSES = ("F", "L")  # scheduled, non-scheduled passenger/cargo
CARGO_CLASSES = ("G", "P")      # scheduled, non-scheduled all-cargo

# Load factor is computed from scheduled passenger service only. Charter (L)
# carries real passengers but its seat utilisation reflects charter economics,
# not whether the airport can absorb more scheduled flights.
LOAD_FACTOR_CLASSES = ("F",)

# No industry-standard definition exists, so the threshold is chosen and
# disclosed rather than implied (ADR-0012 correction 5).
LONG_HAUL_MILES = 3000

# An hour counts as "near peak" at >=80% of that airport's own busiest hour.
# Peak saturation is the share of operating hours meeting that bar (ADR-0006).
PEAK_THRESHOLD = 0.80

# The universe floor. Measured in passengers, not departures: a departure count
# cannot tell a regional jet airport from an Alaskan village served by nine-seat
# bush planes, and an earlier departures-based floor excluded Trenton Mercer
# (156,000 passengers) while admitting Napaskiak (1,194) - see ADR-0022.
#
# 10,000 annual boardings is the federal definition of a "primary" airport
# (49 U.S.C. 47102), the same statute the hub tiers come from, so this removes
# an invented parameter rather than replacing it with another.
MIN_ANNUAL_ENPLANEMENTS = 10_000

# Cargo share above which the peak-hour bias is flagged on the score itself
# (ADR-0014).
CARGO_MATERIALITY = 0.15

# How each hub tier is named in prose. Defined once: scoring.py built these by
# appending "hubs" to the tier, which reads correctly for large/medium/small and
# produces "nonhub hubs" for everything else.
TIER_ORDER = ("large", "medium", "small", "nonhub")
TIER_LABEL = {
    "large": "large hubs",
    "medium": "medium hubs",
    "small": "small hubs",
    "nonhub": "non-hub airports",
}


def tier_label(tier):
    return TIER_LABEL.get(tier, tier or "unknown")



def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

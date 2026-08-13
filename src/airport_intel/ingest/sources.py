"""Where the raw data comes from, and how to ask for it.

Three sources, three very different access mechanisms (ADR-0004):

1. OurAirports  - plain CSV over HTTP. Trivial.
2. BTS On-Time  - prebuilt monthly zips under /PREZIP. A direct GET; no form.
3. BTS T-100    - NOT in /PREZIP. Only reachable by POSTing an ASP.NET
                  WebForms page with its __VIEWSTATE and the desired columns
                  checked. Verified working 2026-08-12.

The T-100 table used is "T-100 Segment (All Carriers)", which already combines
domestic and international. BTS trims it to a uniform end date, which means the
common-window problem of ADR-0012 correction 7 is solved at the source rather
than by us.
"""
from typing import Dict, List

# --- OurAirports -----------------------------------------------------------

OURAIRPORTS_BASE = "https://davidmegginson.github.io/ourairports-data"
OURAIRPORTS_FILES = ["airports.csv", "runways.csv"]

# --- BTS On-Time Performance ----------------------------------------------

ONTIME_URL = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)

# --- BTS T-100 Segment (All Carriers) -------------------------------------

T100_URL = (
    "https://www.transtats.bts.gov/DL_SelectFields.aspx"
    "?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4+Pn44vr45"
)

# Columns requested from T-100. Each becomes a checkbox in the POST body.
#
# CLASS distinguishes scheduled passenger service from freight-only operations,
# which is what makes the per-component cargo rule of ADR-0012 possible.
# SEATS + PASSENGERS give load factor; DISTANCE gives long-haul share.
T100_FIELDS: List[str] = [
    "YEAR",
    "MONTH",
    "ORIGIN",
    "DEST",
    "PASSENGERS",
    "SEATS",
    "DEPARTURES_PERFORMED",
    "DEPARTURES_SCHEDULED",
    "DISTANCE",
    "CLASS",
    "AIRCRAFT_TYPE",
    "AIRCRAFT_GROUP",
    "CARRIER",
    "ORIGIN_STATE_ABR",
    "DEST_STATE_ABR",
    "ORIGIN_COUNTRY",
    "DEST_COUNTRY",
]


def t100_form_data(year: int, month: int, viewstate: Dict[str, str]) -> Dict[str, str]:
    """Build the POST body for one month of T-100.

    `viewstate` carries the three ASP.NET hidden fields scraped from a fresh
    GET of the page; they are single-use and must not be cached across runs.
    """
    data = dict(viewstate)
    data.update({
        "cboGeography": "All",
        "cboYear": str(year),
        "cboPeriod": str(month),  # 1-12; the label ("January") is rejected
        "btnDownload": "Download",
    })
    for field in T100_FIELDS:
        data[field] = "on"
    return data

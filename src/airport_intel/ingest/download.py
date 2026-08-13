"""Fetch raw source files into data/raw/.

Downloads are idempotent: a file already on disk is left alone unless --force
is passed, so a run interrupted halfway resumes rather than restarting.

BTS throttles each connection to roughly 42 KB/s but does not throttle per IP,
so on-time months are fetched concurrently (ADR-0013). T-100 is fetched
serially: each request needs its own freshly scraped __VIEWSTATE, and the files
are small enough that concurrency buys nothing.
"""
import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import requests

from ..config import (
    DOWNLOAD_WORKERS,
    ONTIME_END,
    ONTIME_START,
    RAW_DIR,
    T100_END,
    T100_START,
    ensure_dirs,
)
from . import sources

USER_AGENT = "Mozilla/5.0 (airport-investment-agent; research use)"
CHUNK = 1 << 16
MIN_PLAUSIBLE_BYTES = 10_000  # anything smaller is an error page, not data

# A stalled BTS connection can hang indefinitely without closing. This is the
# per-read timeout, not a total budget, so a slow-but-alive transfer survives.
READ_TIMEOUT = 120
CONNECT_TIMEOUT = 30
HTTP_NOT_FOUND = 404
MONTHS_IN_YEAR = 12
POLITE_DELAY_SECONDS = 1


class DownloadError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _stream_to_file(response: requests.Response, dest: Path) -> int:
    """Write a streamed response to dest via a .part file.

    The temporary name means an interrupted download never leaves a truncated
    file that a later run would mistake for a complete one.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    try:
        with open(tmp, "wb") as fh:
            for chunk in response.iter_content(CHUNK):
                fh.write(chunk)
                total += len(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if total < MIN_PLAUSIBLE_BYTES:
        tmp.unlink(missing_ok=True)
        raise DownloadError(
            "%s: got %d bytes, expected a data file" % (dest.name, total)
        )
    tmp.replace(dest)
    return total


def months(start: str, end: str) -> Iterator[Tuple[int, int]]:
    """Yield (year, month) inclusive over 'YYYY-MM' bounds."""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m == MONTHS_IN_YEAR + 1:
            y, m = y + 1, 1


# --- OurAirports -----------------------------------------------------------


def download_ourairports(force: bool = False) -> None:
    s = _session()
    for name in sources.OURAIRPORTS_FILES:
        dest = RAW_DIR / name
        if dest.exists() and not force:
            print("  skip   %s (present)" % name)
            continue
        url = "%s/%s" % (sources.OURAIRPORTS_BASE, name)
        with s.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True) as r:
            r.raise_for_status()
            size = _stream_to_file(r, dest)
        print("  got    %s (%.1f MB)" % (name, size / 1e6))


# --- BTS On-Time Performance ----------------------------------------------


def download_ontime_month(year: int, month: int, force: bool = False) -> Optional[Path]:
    dest = RAW_DIR / ("ontime_%d_%02d.zip" % (year, month))
    if dest.exists() and not force:
        return dest
    url = sources.ONTIME_URL.format(year=year, month=month)
    with _session().get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True) as r:
        if r.status_code == HTTP_NOT_FOUND:
            print("  MISS   %s not published yet" % dest.name)
            return None
        r.raise_for_status()
        size = _stream_to_file(r, dest)
    print("  got    %s (%.1f MB)" % (dest.name, size / 1e6))
    return dest


def download_ontime_range(start: str, end: str, force: bool = False,
                          workers: int = DOWNLOAD_WORKERS) -> List[Path]:
    window = list(months(start, end))
    pending = [
        (y, m) for y, m in window
        if force or not (RAW_DIR / ("ontime_%d_%02d.zip" % (y, m))).exists()
    ]
    print("  %d months, %d already present, %d to fetch on %d workers"
          % (len(window), len(window) - len(pending), len(pending), workers))
    if not pending:
        return []

    done: List[Path] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(download_ontime_month, y, m, force): (y, m)
            for y, m in pending
        }
        for fut in as_completed(futures):
            y, m = futures[fut]
            try:
                path = fut.result()
                if path:
                    done.append(path)
            except Exception as exc:
                print("  FAIL   ontime %d-%02d: %s" % (y, m, exc))
    return done


# --- BTS T-100 Segment -----------------------------------------------------


def _scrape_viewstate(session: requests.Session) -> Dict[str, str]:
    """Pull the ASP.NET hidden fields required to POST the T-100 form.

    These are single-use and tied to the session, so they are re-scraped for
    every month rather than cached.
    """
    html = session.get(sources.T100_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)).text
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(r'id="%s"[^>]*value="([^"]*)"' % name, html)
        if not m:
            raise DownloadError(
                "T-100 form layout changed: %s not found. The scraper needs "
                "updating." % name
            )
        fields[name] = m.group(1)
    return fields


def download_t100_month(year: int, month: int, force: bool = False) -> Optional[Path]:
    dest = RAW_DIR / ("t100_%d_%02d.zip" % (year, month))
    if dest.exists() and not force:
        return dest

    s = _session()
    form = sources.t100_form_data(year, month, _scrape_viewstate(s))
    with s.post(sources.T100_URL, data=form,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True) as r:
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "zip" not in ctype:
            # The form answers with an HTML error page rather than an HTTP
            # error status, so content type is the only reliable signal.
            raise DownloadError(
                "T-100 %d-%02d returned %s, not a zip. The month may not be "
                "published yet, or the form changed." % (year, month, ctype)
            )
        size = _stream_to_file(r, dest)
    print("  got    %s (%.1f MB)" % (dest.name, size / 1e6))
    return dest


def download_t100_range(start: str, end: str, force: bool = False) -> List[Path]:
    done: List[Path] = []
    window = list(months(start, end))
    print("  %d months (serial: each POST needs a fresh viewstate)" % len(window))
    for year, month in window:
        try:
            path = download_t100_month(year, month, force)
            if path:
                done.append(path)
        except Exception as exc:
            print("  FAIL   t100 %d-%02d: %s" % (year, month, exc))
        time.sleep(POLITE_DELAY_SECONDS)  # the form is session-based
    return done


# --- orchestration ---------------------------------------------------------


def download_all(ontime_start: str, ontime_end: str,
                 t100_start: str, t100_end: str,
                 force: bool = False,
                 skip_ontime: bool = False, skip_t100: bool = False) -> None:
    ensure_dirs()

    print("OurAirports metadata")
    download_ourairports(force=force)

    if not skip_t100:
        print("\nBTS T-100 Segment  %s .. %s" % (t100_start, t100_end))
        download_t100_range(t100_start, t100_end, force=force)

    if not skip_ontime:
        print("\nBTS On-Time Performance  %s .. %s" % (ontime_start, ontime_end))
        download_ontime_range(ontime_start, ontime_end, force=force)

    print("\nRaw files in %s" % RAW_DIR)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Download raw aviation data.")
    p.add_argument("--ontime-start", default=ONTIME_START, help="YYYY-MM inclusive")
    p.add_argument("--ontime-end", default=ONTIME_END, help="YYYY-MM inclusive")
    p.add_argument("--t100-start", default=T100_START, help="YYYY-MM inclusive")
    p.add_argument("--t100-end", default=T100_END, help="YYYY-MM inclusive")
    p.add_argument("--force", action="store_true", help="re-download existing files")
    p.add_argument("--skip-ontime", action="store_true")
    p.add_argument("--skip-t100", action="store_true")
    args = p.parse_args(argv)

    try:
        download_all(args.ontime_start, args.ontime_end,
                     args.t100_start, args.t100_end,
                     force=args.force,
                     skip_ontime=args.skip_ontime, skip_t100=args.skip_t100)
    except DownloadError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

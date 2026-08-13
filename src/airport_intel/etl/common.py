"""Shared ETL plumbing: unzipping and a DuckDB connection.

DuckDB reads CSV directly but cannot read inside a zip, so archives are
expanded into data/work/ first. That directory is disposable — deleting it
costs a re-extract, never a re-download.
"""
import zipfile
from pathlib import Path
from typing import List

import duckdb

from ..config import RAW_DIR, WORK_DIR, ensure_dirs


def connect() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB. Nothing persists here (ADR-0011)."""
    return duckdb.connect()


def extract(prefix: str, subdir: str) -> List[Path]:
    """Expand data/raw/<prefix>*.zip into data/work/<subdir>/.

    Each archive holds exactly one CSV. The extracted file is renamed to match
    its archive so that (a) months don't overwrite each other — every T-100 zip
    contains a file called T_T100_SEGMENT_ALL_CARRIER.csv — and (b) the source
    month stays visible on disk while debugging.
    """
    ensure_dirs()
    out_dir = WORK_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for archive in sorted(RAW_DIR.glob("%s*.zip" % prefix)):
        dest = out_dir / (archive.stem + ".csv")
        if dest.exists() and dest.stat().st_size > 0:
            written.append(dest)
            continue
        with zipfile.ZipFile(archive) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                print("  warn   %s has no CSV, skipped" % archive.name)
                continue
            with zf.open(names[0]) as src, open(dest, "wb") as fh:
                fh.write(src.read())
        written.append(dest)
    return written


def glob_for(subdir: str) -> str:
    """A DuckDB-readable glob over one extracted source."""
    return str(WORK_DIR / subdir / "*.csv")

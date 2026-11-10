"""Read access to the built snapshot.

Loads the fact tables once, scores every airport once, and keeps the result in
memory. The database holds facts; scores are computed here so weights stay
tunable without a rebuild (ADR-0011).
"""
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .config import DB_PATH
from .scoring import Score, score_all


class Store:
    def __init__(self, db_path: Path = DB_PATH):
        if not Path(db_path).exists():
            raise FileNotFoundError(
                "%s not found - run: python -m airport_intel.etl.build" % db_path
            )
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        # One connection is shared by every request thread and, within a
        # request, by tools running in parallel. sqlite3 does not make a shared
        # connection safe on its own, so queries after load take this lock.
        self._lock = threading.Lock()

        self.metrics: Dict[str, Dict] = {
            r["code"]: dict(r)
            for r in self._con.execute("SELECT * FROM airport_metrics")
        }
        self.scores: Dict[str, Score] = score_all(list(self.metrics.values()))
        self.meta: Dict[str, str] = {
            r["key"]: r["value"] for r in self._con.execute("SELECT * FROM meta")
        }

    # --- windows -----------------------------------------------------------

    def data_window(self, source: str = "ontime") -> Dict[str, str]:
        """The window an answer rests on.

        The two sources cover different periods (ADR-0013), so this is reported
        per answer rather than globally - a growth claim and a congestion claim
        do not describe the same months.
        """
        return {
            "source": source,
            "start": self.meta.get("%s_window_start" % source),
            "end": self.meta.get("%s_window_end" % source),
            "built_at": self.meta.get("built_at"),
        }

    # --- lookups -----------------------------------------------------------

    def get(self, code: str) -> Optional[Dict]:
        return self.metrics.get(code.upper())

    def score(self, code: str) -> Optional[Score]:
        return self.scores.get(code.upper())

    def by_region(self, regions: List[str]) -> List[str]:
        want = {r.upper() for r in regions}
        return [c for c, m in self.metrics.items()
                if (m.get("region") or "").upper() in want]

    def search(self, text: str) -> List[Dict]:
        """Substring match over code, name and city.

        Deliberately permissive: the model handles fuzzy geography, and speech
        input mangles airport codes (ADR-0008), so this errs towards returning
        candidates rather than none.
        """
        needle = text.strip().lower()
        if not needle:
            return []
        hits = []
        for code, m in self.metrics.items():
            haystack = " ".join(filter(None, [
                code, m.get("name") or "", m.get("city") or "",
            ])).lower()
            if needle in haystack:
                hits.append(m)
        return sorted(hits, key=lambda m: -(m.get("enplanements") or 0))

    def routes(self, code: str) -> List[Dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM t100_routes WHERE airport = ? ORDER BY departures DESC",
                (code.upper(),),
            ).fetchall()
        return [dict(r) for r in rows]

"""The six tools the model may call.

Every tool returns structured data - numbers, components, caveats - never prose.
The model composes sentences from what it gets back; it never computes,
estimates, or fills a null (ADR-0007). That boundary is what makes the scoring
deterministic rather than merely claimed to be.
"""
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

from . import geography
from .config import CARGO_MATERIALITY, LONG_HAUL_MILES, TIER_LABEL, TIER_ORDER
from .scoring import Score, peak_movements_per_runway
from .store import Store

FAA_STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"

# Result caps. These bound what the model has to read, not what the data holds:
# a hundred name matches or every route out of a hub would crowd out the answer
# without making it more correct.
NAME_SEARCH_LIMIT = 8
RANK_LIMIT = 20
TOP_ROUTES = 10

# FAA notices are free text and occasionally very long; enough to carry the
# reason and the times, not the full NOTAM.
EVENT_DETAIL_CHARS = 400

FAA_TIMEOUT_SECONDS = 15

# --- helpers ---------------------------------------------------------------


def _score_payload(store: Store, code: str, score: Score, row: Dict) -> Dict:
    """A score plus everything needed to explain and qualify it."""
    return {
        "code": code,
        "name": row.get("name"),
        "city": row.get("city"),
        "region": row.get("region"),
        "tier": score.tier,
        "peer_group": TIER_LABEL.get(score.tier, score.tier),
        "final_score": score.final,
        "congestion_score": score.congestion,
        "growth_multiplier": score.growth_factor,
        "constraint_type": score.constraint_type,
        "confidence": score.confidence,
        "caveats": score.caveats,
        "components": [
            {
                "name": c.name,
                "raw_value": c.raw,
                "percentile_in_peer_group": round(c.percentile, 1)
                    if c.percentile is not None else None,
                "weight": c.weight,
            }
            for c in score.components
        ],
        # Absolute figures alongside the percentiles, because the score is
        # relative to peers and would otherwise be read as absolute (ADR-0006).
        "absolute_figures": {
            "load_factor": _round(row.get("fullness"), 3),
            "peak_hour_departures": _round(row.get("peak_hour_flights"), 1),
            "median_hour_departures": _round(row.get("median_hour_flights"), 1),
            "hours_near_peak_per_day": _round(row.get("near_peak_hours"), 1),
            "operating_hours_per_day": _round(row.get("operating_hours"), 1),
            "nas_delay_minutes_per_departure": _round(row.get("capacity_delay"), 2),
            "runway_count": row.get("runway_count"),
            "estimated_peak_movements_per_runway":
                _round(peak_movements_per_runway(row.get("peak_flights_per_runway")), 1),
            "annual_passengers": _int(row.get("enplanements")),
            "passenger_cagr": _round(row.get("pax_cagr"), 4),
            "cargo_share_of_departures": _round(row.get("cargo_share"), 3),
        },
        "data_windows": _windows(store),
    }


def _windows(store: Store) -> Dict:
    """The two data windows an answer rests on.

    Repeated verbatim in three tools before this; the pair must stay together,
    because the sources cover different periods (ADR-0013) and quoting one
    without the other misstates what an answer describes.
    """
    return {
        "congestion_and_delay": store.data_window("ontime"),
        "traffic_and_growth": store.data_window("t100"),
    }


def _round(value, digits):
    return round(value, digits) if isinstance(value, (int, float)) else None


def _int(value):
    return int(value) if isinstance(value, (int, float)) else None


def _unique_codes(codes: List[str]) -> List[str]:
    """Normalise and de-duplicate while preserving order.

    The model assembles code lists from several resolve calls, which overlap:
    asking about "the LA airports and Santa Ana" yields SNA twice. Without this
    an airport appears repeatedly in one ranking.
    """
    seen, out = set(), []
    for raw in codes or []:
        code = (raw or "").strip().upper()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _not_found(code: str) -> Dict:
    """Out-of-scope and unknown are different answers, and both beat silence."""
    foreign = geography.match_foreign(code)
    if foreign:
        return {
            "error": "out_of_scope",
            "code": foreign[0],
            "name": foreign[1],
            "message": ("%s is outside this agent's scope. The fund invests in "
                        "US airports, and the underlying data (BTS T-100 and "
                        "on-time reporting) only covers flights with a US "
                        "endpoint." % foreign[1]),
        }
    return {
        "error": "not_found",
        "code": code,
        "message": "No US airport matching '%s' in the dataset." % code,
    }


# --- 1. resolve_airports ---------------------------------------------------


def resolve_airports(store: Store, query: str) -> Dict:
    """Turn a place description into airport codes.

    Fuzzy human geography is what code handles badly and a language model
    handles well, so this tool stays permissive and reports what it assumed
    rather than guessing silently (ADR-0007).
    """
    raw = query.strip()
    upper = raw.upper()

    if store.get(upper):
        row = store.get(upper)
        result = {"query": raw, "match_type": "airport_code",
                  "airports": [_brief(store, upper)]}
        metro = _metro_containing(upper)
        if metro:
            alternates = [c for c in geography.METROS[metro]
                          if c != upper and store.get(c)]
            if alternates:
                result["alternates"] = [_brief(store, c) for c in alternates]
                result["assumption"] = (
                    "%s is one of several airports serving the %s area."
                    % (upper, metro.title()))
        return result

    metro = geography.match_metro(raw)
    if metro:
        name, codes = metro
        present = [c for c in codes if store.get(c)]
        if present:
            return {
                "query": raw,
                "match_type": "metro",
                "airports": [_brief(store, present[0])],
                "alternates": [_brief(store, c) for c in present[1:]],
                "assumption": (
                    "Reading '%s' as %s. %s also serve the area - say the word "
                    "and I will include them."
                    % (raw, present[0], ", ".join(present[1:]))
                ) if len(present) > 1 else "Reading '%s' as %s." % (raw, present[0]),
            }

    region = geography.match_region(raw)
    if region:
        name, regions = region
        codes = store.by_region(regions)
        scored = [c for c in codes if store.score(c) and store.score(c).final is not None]
        excluded = [
            {"code": c, "reason": store.score(c).excluded}
            for c in codes if store.score(c) and store.score(c).excluded
        ]
        return {
            "query": raw,
            "match_type": "region",
            "region_name": name.title(),
            "airports": [_brief(store, c) for c in
                         sorted(scored, key=lambda c: -(store.get(c).get("enplanements") or 0))],
            # Exclusions are reported, never silent: dropping small airports
            # quietly would narrow a question without telling anyone
            # (ADR-0012 correction 3).
            "excluded": excluded,
        }

    hits = store.search(raw)
    if hits:
        return {"query": raw, "match_type": "name_search",
                "airports": [_brief(store, h["code"])
                             for h in hits[:NAME_SEARCH_LIMIT]]}

    return _not_found(raw)


def _metro_containing(code: str) -> Optional[str]:
    for name, codes in geography.METROS.items():
        if code in codes and len(codes) > 1:
            return name
    return None


def _brief(store: Store, code: str) -> Dict:
    row = store.get(code) or {}
    score = store.score(code)
    return {
        "code": code,
        "name": row.get("name"),
        "city": row.get("city"),
        "region": row.get("region"),
        "tier": row.get("tier"),
        "final_score": score.final if score else None,
        "excluded": score.excluded if score else None,
    }


# --- 2. score_airport ------------------------------------------------------


def score_airport(store: Store, code: str) -> Dict:
    code = code.strip().upper()
    row = store.get(code)
    score = store.score(code)
    if not row or not score:
        return _not_found(code)
    if score.excluded:
        return {"code": code, "name": row.get("name"), "error": "excluded",
                "message": "%s is %s." % (code, score.excluded)}
    return _score_payload(store, code, score, row)


# --- 3. rank_airports ------------------------------------------------------


def rank_airports(store: Store, codes: List[str],
                  limit: int = RANK_LIMIT) -> Dict:
    """Rank a set of airports, grouped by tier.

    Never one merged list. Percentiles are computed within tier, so a single
    ranking across tiers would compare numbers that do not mean the same thing
    (ADR-0012 correction 1).
    """
    # The model supplies this, so it can arrive as 0 or a negative. Slicing with
    # a negative silently drops the WORST entries instead of keeping the best,
    # which would be an answer rather than an error.
    if limit is None or limit < 1:
        limit = RANK_LIMIT

    groups: Dict[str, List[Dict]] = {}
    excluded, unknown = [], []

    for code in _unique_codes(codes):
        row, score = store.get(code), store.score(code)
        if not row or not score:
            unknown.append(code)
            continue
        if score.excluded:
            excluded.append({"code": code, "name": row.get("name"),
                             "reason": score.excluded})
            continue
        groups.setdefault(score.tier, []).append({
            "code": code,
            "name": row.get("name"),
            "final_score": score.final,
            "congestion_score": score.congestion,
            "growth_multiplier": score.growth_factor,
            "constraint_type": score.constraint_type,
            "confidence": score.confidence,
            "caveats": score.caveats,
            "load_factor": _round(row.get("fullness"), 3),
            "peak_saturation": _round(row.get("peak_saturation"), 3),
        })

    ranked = []
    for tier in TIER_ORDER:
        if tier in groups:
            ranked.append({
                "tier": tier,
                "peer_group": TIER_LABEL[tier],
                "airports": sorted(groups[tier],
                                   key=lambda a: -(a["final_score"] or 0))[:limit],
            })

    return {
        "ranking_by_tier": ranked,
        "excluded": excluded,
        "unknown": unknown,
        "note": ("Scores rank each airport against peers of its own size. "
                 "A higher score in a smaller tier does not mean more traffic "
                 "than a larger airport."),
        "data_windows": _windows(store),
    }


# --- 4. compare_airports ---------------------------------------------------


def compare_airports(store: Store, codes: List[str]) -> Dict:
    """Side-by-side comparison.

    When the airports sit in different tiers their percentiles are not
    comparable, so raw measured figures lead and percentiles follow as context
    (ADR-0009).
    """
    rows, missing = [], []
    for code in _unique_codes(codes):
        row, score = store.get(code), store.score(code)
        if not row or not score:
            missing.append(_not_found(code))
            continue
        rows.append({
            "code": code,
            "name": row.get("name"),
            "tier": score.tier,
            "peer_group": TIER_LABEL.get(score.tier, score.tier),
            "raw_metrics": {
                "load_factor": _round(row.get("fullness"), 3),
                "peak_saturation_ratio": _round(row.get("peak_saturation"), 3),
                "peak_hour_departures": _round(row.get("peak_hour_flights"), 1),
                "nas_delay_minutes_per_departure": _round(row.get("capacity_delay"), 2),
                "annual_passengers": _int(row.get("enplanements")),
                "runway_count": row.get("runway_count"),
            },
            "tier_percentiles": {
                c.name: round(c.percentile, 1) if c.percentile is not None else None
                for c in score.components
            },
            "final_score": score.final,
            "constraint_type": score.constraint_type,
            "confidence": score.confidence,
            "caveats": score.caveats,
        })

    tiers = {r["tier"] for r in rows}
    return {
        "airports": rows,
        "missing": missing,
        "cross_tier": len(tiers) > 1,
        "comparison_basis": (
            "These airports are in different size tiers, so their scores and "
            "percentiles are not directly comparable. Compare the raw metrics; "
            "percentiles describe each airport against its own peers."
            if len(tiers) > 1 else
            "These airports are in the same tier, so scores are directly comparable."
        ),
        "data_windows": _windows(store),
    }


# --- 5. route_profile ------------------------------------------------------


def route_profile(store: Store, code: str, top_n: int = TOP_ROUTES) -> Dict:
    """Network shape: long-haul share, international mix, biggest routes.

    Passenger and cargo are reported separately. At a freight hub a blended
    figure is dominated by cargo and misleads anyone reading it as passenger
    demand (ADR-0012 correction 6).
    """
    code = code.strip().upper()
    row = store.get(code)
    if not row:
        return _not_found(code)

    routes = store.routes(code)
    if not routes:
        return {"code": code, "name": row.get("name"), "error": "no_route_data",
                "message": "No route data for %s in the current window." % code}

    out = {
        "code": code,
        "name": row.get("name"),
        "long_haul_definition_miles": LONG_HAUL_MILES,
        "assumption": ("Long-haul is defined here as %d statute miles or more, "
                       "measured great-circle. No industry-standard definition "
                       "exists." % LONG_HAUL_MILES),
        "by_service": {},
        "data_window": store.data_window("t100"),
    }

    for service in ("passenger", "cargo"):
        legs = [r for r in routes if r["service"] == service]
        total = sum(r["departures"] or 0 for r in legs)
        if not total:
            continue
        long_haul = sum(r["departures"] or 0 for r in legs
                        if (r["distance_miles"] or 0) >= LONG_HAUL_MILES)
        intl = sum(r["departures"] or 0 for r in legs
                   if (r["dest_country"] or "US") != "US")
        by_dest: Dict[str, Dict] = {}
        for r in legs:
            d = by_dest.setdefault(r["dest"], {
                "dest": r["dest"], "distance_miles": r["distance_miles"],
                "departures": 0, "passengers": 0,
            })
            d["departures"] += r["departures"] or 0
            d["passengers"] += r["passengers"] or 0

        out["by_service"][service] = {
            "total_departures": round(total),
            "long_haul_departures": round(long_haul),
            "long_haul_share": round(long_haul / total, 3),
            "international_departures": round(intl),
            "international_share": round(intl / total, 3),
            "destinations": len(by_dest),
            "top_routes": sorted(by_dest.values(),
                                 key=lambda d: -d["departures"])[:top_n],
        }

    cargo = out["by_service"].get("cargo", {}).get("total_departures", 0)
    pax = out["by_service"].get("passenger", {}).get("total_departures", 0)
    if cargo and pax and cargo / (cargo + pax) >= CARGO_MATERIALITY:
        out["note"] = (
            "Cargo is %.0f percent of departures here, so any blended "
            "long-haul figure would be dominated by freight rather than "
            "passenger demand." % (100 * cargo / (cargo + pax))
        )
    return out


# --- 6. current_conditions -------------------------------------------------


def parse_faa_events(root: ET.Element, code: str) -> List[Dict]:
    """Pull one airport's active programs out of the FAA status feed.

    The feed nests <Delay_type><Name>..</Name><Something_List><Airport><ARPT>.
    An earlier version matched on tag names ending in "closure" or "delay", but
    the container is "Airport_Closure_List" - which ends in "list" - so nothing
    ever matched and the tool reported "no active programs" unconditionally,
    including for airports that were closed at the time.

    Split out from the network call so it can be tested against a fixture
    rather than against whatever the sky is doing today.
    """
    events = []
    for delay_type in root.iter("Delay_type"):
        label = (delay_type.findtext("Name") or "FAA program").strip()
        for airport in delay_type.iter("Airport"):
            if (airport.findtext("ARPT") or "").strip().upper() != code.upper():
                continue
            detail = " ".join(
                "%s: %s" % (child.tag, (child.text or "").strip())
                for child in airport
                if child.tag != "ARPT" and (child.text or "").strip()
            )
            events.append({"type": label,
                           "detail": detail[:EVENT_DETAIL_CHARS]})
    return events


def current_conditions(store: Store, code: str,
                       timeout: int = FAA_TIMEOUT_SECONDS) -> Dict:
    """Live FAA disruptions. Never scored.

    The feed reports only what is active right now and stores no history, so it
    cannot describe a typical week - and letting it touch the score would make
    the ranking non-deterministic (ADR-0004).
    """
    code = code.strip().upper()
    row = store.get(code)
    if not row:
        return _not_found(code)

    try:
        resp = requests.get(FAA_STATUS_URL, timeout=timeout,
                            headers={"User-Agent": "airport-investment-agent"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        return {"code": code, "error": "faa_feed_unavailable",
                "message": "Could not reach the FAA status feed: %s" % exc}

    events = parse_faa_events(root, code)

    return {
        "code": code,
        "name": row.get("name"),
        "active_events": events,
        "status": "disruptions active" if events else "no active FAA programs",
        "note": ("This is live and separate from the historical score. It "
                 "reflects conditions right now, not a typical week, and does "
                 "not affect the ranking."),
    }

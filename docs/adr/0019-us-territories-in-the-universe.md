# ADR-0019: US territories are part of the airport universe

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extends:** [ADR-0009](0009-airport-universe-and-peer-tiers.md)

---

## Context

ADR-0009 defined the universe as US airports above a volume floor, grouped into
federal hub tiers. "US" was left as an obvious term. It is not.

The first build joined BTS traffic to OurAirports metadata on
`iso_country = 'US'`. Inspecting the unmatched rows showed the largest were not
obscure airfields but **US territories**:

| Code | Airport | OurAirports country | Annual departures |
|------|---------|--------------------|-------------------|
| SJU | Luis Muñoz Marín, San Juan | `PR` | 68,110 |
| STT | Cyril E. King, St Thomas | `VI` | 21,180 |
| STX | Henry E. Rohlsen, St Croix | `VI` | 13,862 |
| SPN | Saipan | `MP` | 12,095 |
| GUM | Antonio B. Won Pat, Guam | `GU` | 8,415 |

OurAirports codes each territory by its own ISO country, so a literal `'US'`
filter silently dropped all of them. **SJU alone has more departures than
Hartford (BDL)** and is a federally classified medium hub.

---

## Decision

The universe includes airports whose OurAirports country is any of
**`US`, `PR`, `VI`, `GU`, `MP`, `AS`** — the fifty states plus Puerto Rico, the
US Virgin Islands, Guam, the Northern Mariana Islands and American Samoa.

---

## Rationale

1. **BTS and the FAA already treat them as US airports.** They appear in T-100
   and in on-time reporting under the same rules, and carry federal hub
   classifications. Excluding them would disagree with the data's own
   definition.
2. **They are US infrastructure.** A fund investing in US airport modernisation
   can invest in San Juan. Dropping it narrows the client's opportunity set for
   no reason.
3. **The exclusion was accidental, not reasoned.** It came from a convenient
   string comparison, and the only reason it surfaced was that the unmatched
   rows were inspected rather than assumed to be noise. Left alone it would have
   silently removed a medium hub from every regional query.

---

## Consequences

- After the fix, **every large, medium and small hub in the universe has complete
  metadata** — coordinates, region and runways. The remaining unmatched rows are
  Alaskan seaplane bases and heliports, which fall below the volume floor anyway.
- Territory `iso_region` values take unusual forms (`PR-U-A`, `GU-U-A`,
  `MP-U-A`) rather than the `US-XX` pattern. Region-based geography lookups are
  written against the state list and do not match these, so a query for a named
  US region will not return territory airports. Direct lookup by code works.
  Documented rather than fixed; a "Caribbean" or "Pacific territories" region
  entry would close it.
- Guam and Saipan sit far outside the continental US, so any future
  distance-based or catchment logic must not assume a contiguous landmass.

---

## Note on method

This was found by printing the rows that failed to join and reading them, rather
than by trusting a filter that looked obviously correct. The join was not
throwing an error — it was quietly producing a smaller, plausible dataset. That
is the failure mode worth building the habit against.

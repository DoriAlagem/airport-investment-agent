# ADR-0021: Visual language taken from the client's own site

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** Dor
- **Extends:** [ADR-0017](0017-interface-makes-determinism-visible.md)

---

## Context

ADR-0017 decided what the interface must *show* — evidence cards, tool traces,
computed confidence — but not how it should look. The first build used a
conventional product-chrome style: soft grey background, shadowed cards, blue
accents, semibold headings.

The brief comes from Wonderful, an applied-AI company with a published design
language. Matching it is not decoration: a deliverable that looks like it
belongs to the people reading it reads as considered rather than generic.

---

## Decision

The visual language was taken **from wonderful.ai directly** — the live site was
loaded and its computed styles read, rather than approximated from memory.

| Property | Observed | Adopted |
|---|---|---|
| Ground | pure white `#fff` | `--bg: #ffffff` (inverted to `#0a0a0a` in dark mode) |
| Ink | pure black | `--ink: #0a0a0a`, secondary tones as alpha rather than grey hues |
| Display type | 82 px, **weight 300** | Light-weight headings throughout: hero 300, section headings 300 |
| Buttons | fully rounded pills | `--radius-pill: 999px` on the composer, send, mic and controls |
| Surfaces | flat, hairline borders | `--shadow: none`, 6 px card radius, 1 px lines |
| Colour | reserved for content | Accent used only in data marks, never in chrome |

The signature is the **light display weight**. It is what makes the reference
read as considered rather than loud, and it was the single highest-impact change.

Body text uses Inter with a system fallback. The reference's display face (ABC
Favorit Light) is licensed and cannot be redistributed, so it is not used; the
weight and spacing carry the resemblance instead.

---

## What did not change

The data visualisation palette is untouched. Its blue and orange were validated
for colourblind separation, contrast and lightness banding in both themes
(ADR-0017), and restyling chrome is no reason to invalidate a checked palette.
Status colours likewise remain the reserved set, still paired with an icon and a
word so meaning never rests on hue.

**Chrome follows the brand; data follows the accessibility rules.** They are
separate systems and were kept separate.

---

## Consequences

- Dark mode is now true black rather than blue-grey, matching the reference's
  inversion. Both themes were re-checked by screenshot after the change.
- Flat surfaces put more weight on spacing and hairlines to establish hierarchy;
  cards that previously relied on shadow needed slightly more padding.
- The product is named **AI.I — Airport Investment Intelligence**, set in the
  same light weight, with the separating dot as the only accent-coloured element
  in the entire chrome.
- If the brand changes, the change is confined to the token block at the top of
  the stylesheet plus the type weights — the component layer reads roles, never
  raw colour.

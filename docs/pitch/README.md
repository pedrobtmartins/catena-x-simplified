# Pitch deck

*Traceability, simplified* — 14 slides on why a lightweight Traceability KIT app can work where
Trace-X stalled, with speaker notes on every slide.

- **View**: open [`index.html`](index.html) in a browser (fonts load from Google Fonts; tick
  *Speaker notes* to show them).
- **Sources**: [`deck.json`](deck.json) (title, slide order, sections, typefaces) and one file per
  slide in [`slides/`](slides/), in the 1920×1080 slide format of the Slides artifact the deck was
  made in. [`parts-production.jpg`](parts-production.jpg) is the app screenshot used on slide 11 (the current UI after a local test sync against a production connector, October 2026; part names, serials, part numbers, Catena-X IDs and BPNL blurred); [`notification-detail.png`](notification-detail.png), a received alert, is kept as an alternative.
- **Rebuild** the viewer after editing a slide: `python3 docs/pitch/build.py`.

Before presenting, fill in the bracketed placeholders (presenter, contact, timeline, team and the
asks on slide 13).

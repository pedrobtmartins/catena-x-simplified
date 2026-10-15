# Web UI

React + TypeScript (Vite). Screens:

- **Parts** — summary (own parts, supplier/customer links, aspect version mix), search, filters by
  kind and aspect version (v3/v4), and the parts table;
- **Part detail** — attributes, source aspects and the one-level as-built tree (customers ← part →
  suppliers); partner twins not yet cached are drawn dashed. *Send quality alert* (own parts with a
  known customer) and *Start investigation* (the part's supplier parts, or a cached partner part);
- **Notifications** — inbox and outbox with open counts; the menu shows how many received
  notifications are not acknowledged yet;
- **Notification detail** — status along the KIT state model, the actions this side may take
  (send, acknowledge, accept/decline with an answer, close), affected parts, message log, and for
  received notifications the *next hop*: the own parts concerned and the direct partners to forward
  to;
- **New alert / investigation** — select the affected parts, see the recipients computed from the
  local tree (one notification per partner), set severity, description and response date, then save
  drafts or send;
- **Partners** — direct suppliers and customers from the own BoM/usage data, their DSP connector
  (editable), linked/cached twins and the last partner sync;
- **Sync history** — latest run, timeline of recorded runs with their issues, and the sync source;
- **Setup** — a guided checklist (what each piece is, what to ask the IT team for, the settings it
  goes in, and a *Copy request for IT* message), the own participant with *Test connections*,
  adding partners by BPNL and finding their connectors and names through the dataspace services.
  The app opens on it while no Digital Twin Registry is configured.

Sending and status changes need a configured EDC; without one, drafts can still be created.

The palette follows the open-source Eclipse Tractus-X portal theme
([portal-shared-components](https://github.com/eclipse-tractusx/portal-shared-components),
Apache-2.0): primary blue `#0F71CB`, orange `#FFA600`, lime `#B3CB2D`; typeface Libre Franklin
(with IBM Plex Mono for identifiers), bundled via `@fontsource` so the UI needs no external fonts.
Colors are CSS custom properties at the top of [`src/styles.css`](src/styles.css).

```bash
npm install
npm run dev     # http://localhost:5173, proxies /api to the backend on :8000
npm run build   # type-check and build into dist/
```

In production the backend serves `dist/` when `CXS_WEB_DIST_DIR` is set (see
[../backend/README.md](../backend/README.md)).

# Web UI

React + TypeScript (Vite). Three screens:

- **Parts** — summary (own parts, supplier/customer links, aspect version mix), search, filters by
  kind and aspect version (v3/v4), and the parts table;
- **Part detail** — attributes, source aspects and the one-level as-built tree (customers ← part →
  suppliers); partner twins not yet cached are drawn dashed;
- **Sync history** — latest run, timeline of recorded runs with their issues, and the sync source.

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

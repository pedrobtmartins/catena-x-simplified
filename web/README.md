# Web UI

React + TypeScript (Vite). Lists the cached parts and shows a part with its direct parents and
children; the header triggers a sync of the participant's own twins.

```bash
npm install
npm run dev     # http://localhost:5173, proxies /api to the backend on :8000
npm run build   # type-check and build into dist/
```

In production the backend serves `dist/` when `CXS_WEB_DIST_DIR` is set (see
[../backend/README.md](../backend/README.md)).

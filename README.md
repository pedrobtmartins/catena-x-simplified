# catena-x-simplified

A lightweight, interoperable traceability application for Catena-X, based on the
Traceability KIT (8.0.0) and the Eclipse Tractus-X 26.03 release.

- Quality Alerts and Quality Investigations (Notification API 1.2.1 and 2.0.0)
- SerialPart/Batch/BoM/Usage aspect models, v3 and v4
- Saturn-only (DSP 2025-1); EDC, DTR and identity are participant prerequisites

See [docs/architecture.md](docs/architecture.md) for the design and
[docs/glossary.md](docs/glossary.md) for the Catena-X terms.

## Status

Phase 1 (core) is implemented: aspect model adapters (v3/v4), own DTR sync via the Tractus-X SDK
with a recorded sync history, local cache, one-level as-built tree, REST API and the web UI
(parts, part detail with tree, sync history). Phase 2 (partners and notifications) is implemented:
direct partners' twins read through the EDC, quality alerts and investigations (Notification API
1.2.1 and 2.0.0, KIT state model, assisted hop-by-hop forwarding) and their UI (inbox/outbox,
notification detail, composer, partners). It is tested against mocks; the run against real EDCs on
the umbrella environment is phase 3. See [the phases](docs/architecture.md#10-phases).

## Quick start

Runs the app against a mock participant (a small DTR and submodel server with six battery
modules, mixing SerialPart 3.0.0 and 4.0.0) — no dataspace needed.

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 22.

```bash
# 1. Mock participant (terminal 1)
cd backend
uv sync
uv run python devtools/mock_participant.py --port 8081

# 2. Backend (terminal 2) — the example settings point to the mock
cd backend
cp .env.example .env
uv run uvicorn catenax_simplified.main:app --reload

# 3. Web UI (terminal 3) — http://localhost:5173
cd web
npm install
npm run dev
```

Click **Sync own twins** in the UI (or `curl -X POST localhost:8000/api/sync`). The API's
interactive documentation is at http://localhost:8000/docs.

To serve the built UI from the backend instead: `npm run build` in `web/`, then set
`CXS_WEB_DIST_DIR=../web/dist` in `backend/.env` and open http://localhost:8000.

Against a real participant, set the DTR, OAuth and submodel settings in `backend/.env`
(see [backend/README.md](backend/README.md#configuration)).

### Three-company demo (no EDCs)

Tier-2 (cell maker, still on SerialPart 3) → Tier-1 (module maker) → OEM, each with its own app,
database and mock registry, on one machine:

```bash
cd web && npm install && npm run build && cd ../backend
uv sync
uv run python devtools/demo_network.py
```

Open http://127.0.0.1:8002 (Tier-2), http://127.0.0.1:8001 (Tier-1) and http://127.0.0.1:8003
(OEM). Send a quality alert from a Tier-2 cell, forward it from Tier-1's inbox to the OEM, and
answer it back. The apps run in **development mode** (`CXS_DEV_DIRECT`): partners are reached
directly instead of through EDCs — the UI says so on every page. It shows how the app behaves; it
is not a dataspace test.

## Repository layout

- [`backend/`](backend/README.md) — FastAPI application (Python, Tractus-X SDK)
- [`web/`](web/README.md) — React UI
- [`docs/architecture.md`](docs/architecture.md) — architecture and decisions
- [`docs/glossary.md`](docs/glossary.md) — Catena-X and Tractus-X terms
- [`docs/pitch/`](docs/pitch/README.md) — pitch deck (open `docs/pitch/index.html`)

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under the [Apache License 2.0](LICENSE);
third-party notices in [NOTICE.md](NOTICE.md).

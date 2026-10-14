# Backend

FastAPI application (Python 3.12+, [uv](https://docs.astral.sh/uv/)). See
[../docs/architecture.md](../docs/architecture.md) for the design.

```
src/catenax_simplified/
  aspects/        aspect model adapters (v3, v4, industry_core v4) → internal model
  dataspace/      ports + DTR (Tractus-X SDK) and submodel access
  storage/        local cache (SQLAlchemy; SQLite or Postgres)
  traceability/   own-twin and partner sync, one-level as-built tree
  api/            REST API for the UI
devtools/         mock participant (DTR + submodels) for local development
tests/            unit and API tests (no infrastructure needed)
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Run against the mock participant (6 battery modules, mixing SerialPart 3.0.0 and 4.0.0):

```bash
uv run python devtools/mock_participant.py --port 8081 &
cp .env.example .env          # its defaults point to the mock participant
uv run uvicorn catenax_simplified.main:app --reload
curl -X POST localhost:8000/api/sync
```

The UI (`../web`) runs with `npm run dev` and proxies `/api` to port 8000. To serve the built UI
from the backend, set `CXS_WEB_DIST_DIR=../web/dist`.

## Configuration

All settings are `CXS_*` environment variables, or a `.env` file in the directory the app is
started from. [`.env.example`](.env.example) lists them all with comments; see also
[`config.py`](src/catenax_simplified/config.py).

| Variable                        | Purpose                                                              |
|---------------------------------|----------------------------------------------------------------------|
| `CXS_OWN_BPNL`                  | The participant's BPNL (required)                                    |
| `CXS_DATABASE_URL`              | SQLAlchemy URL, e.g. `postgresql+psycopg://…` (install the `postgres` extra) |
| `CXS_DTR_BASE_URL`              | Own DTR base URL; `CXS_DTR_API_PATH` defaults to `/api/v3`           |
| `CXS_OAUTH_*`                   | Keycloak client credentials for the DTR (`URL`, `REALM`, `CLIENT_ID`, `CLIENT_SECRET`) |
| `CXS_SUBMODEL_HREF_REWRITES`    | JSON list of `[public_prefix, internal_prefix]`: reads own submodels from the backend instead of the public data plane |
| `CXS_SUBMODEL_HEADERS`          | JSON object of extra headers for the submodel backend (e.g. an API key) |
| `CXS_EDC_MANAGEMENT_URL`        | Own EDC management API (Saturn); with `CXS_EDC_MANAGEMENT_PATH` and `CXS_EDC_API_KEY`. Enables partner sync |
| `CXS_ACCEPTED_POLICIES`         | JSON list of usage policies accepted in partners' catalogs; empty = no negotiation |
| `CXS_ACCEPT_ANY_POLICY`         | Accept any offered policy — development only                         |
| `CXS_PARTNER_CONNECTORS`        | JSON object BPNL → partner DSP endpoint (addresses set through the API win) |
| `CXS_SYNC_INTERVAL_SECONDS`     | Periodic sync (own twins, then partners); `0` (default) disables it   |
| `CXS_WEB_DIST_DIR`              | Directory of the built UI, served at `/`                             |

## API

| Method | Path                         | Description                                   |
|--------|------------------------------|-----------------------------------------------|
| GET    | `/api/health`                | Status, own BPNL, DTR URL, sync schedule, supported aspect versions |
| GET    | `/api/stats`                 | Own parts by kind and aspect version; supplier/customer links |
| GET    | `/api/parts`                 | Cached parts with parent/child counts (`search`, `kind`, `aspect_major`, `own_only`, `limit`, `offset`) |
| GET    | `/api/parts/{id}`            | One part                                      |
| GET    | `/api/parts/{id}/tree`       | Part with its direct parents and children     |
| POST   | `/api/sync`                  | Sync own twins from the DTR now               |
| GET    | `/api/sync/last`             | Report of the last sync                       |
| GET    | `/api/sync/runs`             | Recorded sync runs, newest first (`limit`)    |
| GET    | `/api/partners`              | Direct partners (from own BoM/usage relations): roles, linked twins, cached parts, connector, last sync |
| PUT    | `/api/partners/{bpnl}`       | Set a partner's name and DSP connector address |
| POST   | `/api/partners/sync`         | Cache direct partners' twins through the EDC (`bpnl` for one partner) |

Partner sync reads only the twins own parts are linked to (one level) and only their
SerialPart/Batch submodels — never a partner's BoM or usage. Contract agreements and access tokens
are reused through the Tractus-X SDK's connection manager (in memory, per process).

Every sync run is stored (`sync_runs` table) with its counters and issues. Timestamps are returned
in UTC.

Interactive documentation: `/docs`.

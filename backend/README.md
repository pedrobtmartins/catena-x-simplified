# Backend

FastAPI application (Python 3.12+, [uv](https://docs.astral.sh/uv/)). See
[../docs/architecture.md](../docs/architecture.md) for the design.

```
src/catenax_simplified/
  aspects/        aspect model adapters (v3, v4, industry_core v4) → internal model
  dataspace/      ports + DTR (Tractus-X SDK) and submodel access
  storage/        local cache (SQLAlchemy; SQLite or Postgres)
  traceability/   own-twin sync, one-level as-built tree
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
CXS_OWN_BPNL=BPNL000000000T1A CXS_DTR_BASE_URL=http://localhost:8081 \
  uv run uvicorn catenax_simplified.main:app --reload
curl -X POST localhost:8000/api/sync
```

The UI (`../web`) runs with `npm run dev` and proxies `/api` to port 8000. To serve the built UI
from the backend, set `CXS_WEB_DIST_DIR=../web/dist`.

## Configuration

All settings are `CXS_*` environment variables (or a `.env` file); see
[`config.py`](src/catenax_simplified/config.py).

| Variable                        | Purpose                                                              |
|---------------------------------|----------------------------------------------------------------------|
| `CXS_OWN_BPNL`                  | The participant's BPNL (required)                                    |
| `CXS_DATABASE_URL`              | SQLAlchemy URL, e.g. `postgresql+psycopg://…` (install the `postgres` extra) |
| `CXS_DTR_BASE_URL`              | Own DTR base URL; `CXS_DTR_API_PATH` defaults to `/api/v3`           |
| `CXS_OAUTH_*`                   | Keycloak client credentials for the DTR (`URL`, `REALM`, `CLIENT_ID`, `CLIENT_SECRET`) |
| `CXS_SUBMODEL_HREF_REWRITES`    | JSON list of `[public_prefix, internal_prefix]`: reads own submodels from the backend instead of the public data plane |
| `CXS_SUBMODEL_HEADERS`          | JSON object of extra headers for the submodel backend (e.g. an API key) |
| `CXS_SYNC_INTERVAL_SECONDS`     | Periodic own-twin sync; `0` (default) disables it                     |
| `CXS_WEB_DIST_DIR`              | Directory of the built UI, served at `/`                             |

## API

| Method | Path                         | Description                                   |
|--------|------------------------------|-----------------------------------------------|
| GET    | `/api/health`                | Status, own BPNL, whether a DTR is configured |
| GET    | `/api/parts`                 | Cached parts (`search`, `kind`, `own_only`, `limit`, `offset`) |
| GET    | `/api/parts/{id}`            | One part                                      |
| GET    | `/api/parts/{id}/tree`       | Part with its direct parents and children     |
| POST   | `/api/sync`                  | Sync own twins from the DTR now               |
| GET    | `/api/sync/last`             | Report of the last sync                       |

Interactive documentation: `/docs`.

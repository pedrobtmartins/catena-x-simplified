# Backend

FastAPI application (Python 3.12+, [uv](https://docs.astral.sh/uv/)). See
[../docs/architecture.md](../docs/architecture.md) for the design.

```
src/catenax_simplified/
  aspects/        aspect model adapters (v3, v4, industry_core v4) → internal model
  dataspace/      ports + DTR (Tractus-X SDK), submodel access, EDC: partner reads,
                  notification sending, publishing our notification assets
  notifications/  quality notification payloads (API 1.2.1/2.0.0), state model, service
  storage/        local cache and notification log (SQLAlchemy; SQLite or Postgres)
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

`devtools/demo_network.py` runs three companies (Tier-2 → Tier-1 → OEM) side by side in
development mode — see the [root README](../README.md#three-company-demo-no-edcs).

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
| `CXS_NOTIFICATION_BASE_URL`     | Where our EDC's data plane reaches this app; with an EDC, the notification assets are published at startup |
| `CXS_NOTIFICATION_API_KEY`      | Required as `X-Api-Key` on `/api/qualitynotifications/*`; also put in the assets' data address |
| `CXS_NOTIFICATION_ACCESS_POLICY`, `CXS_NOTIFICATION_USAGE_POLICY` | JSON ODRL permissions of the notification assets; defaults: active membership / `DataExchangeGovernance:1.0` + `cx.core.qualityNotifications:1` |
| `CXS_NOTIFICATION_ASSET_PREFIX` | Prefix of the asset, policy and contract IDs (default `cxs-qualitynotification`) |
| `CXS_DEV_DIRECT`                | **Development only.** Reach partners without EDCs: notifications are posted to the partner apps (`CXS_PARTNER_CONNECTORS` = their base URLs), partner twins read from `CXS_DEV_PARTNER_DTRS` (BPNL → DTR URL with API path). Never in a dataspace |
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
| GET    | `/api/partners/checks`       | Recorded partner health checks, newest first (`bpnl`, `limit`) |
| POST   | `/api/partners/checks`       | Check all partners (`level`; `only_unhealthy` defaults to true) |
| POST   | `/api/partners/{bpnl}/checks` | Check one partner (`level`: `discovery`, `catalog` or `full`) |
| GET    | `/api/notifications`         | Inbox/outbox (`direction`, `type`, `status`, `partner`, `open_only`, `limit`, `offset`) |
| GET    | `/api/notifications/summary` | Open notifications per direction; received ones not yet acknowledged |
| POST   | `/api/notifications/plan`    | Recipients of an alert/investigation about the given parts, from the local tree |
| POST   | `/api/notifications`         | Create one draft per recipient (`send: true` sends them right away) |
| GET    | `/api/notifications/{id}`    | Notification with affected parts, message log, forwarding links and possible actions |
| GET    | `/api/notifications/{id}/forward-plan` | Next hop for a received notification |
| POST   | `/api/notifications/{id}/send` | Send a draft through the EDC                |
| POST   | `/api/notifications/{id}/status` | Change the status (sent to the partner as an update) |
| POST   | `/api/notifications/assets`  | Publish the notification assets in our EDC again |

Partners call the Traceability KIT's Notification API through our EDC:

| Method | Path                                 | Description                           |
|--------|--------------------------------------|---------------------------------------|
| POST   | `/api/qualitynotifications/receive`  | New alert or investigation → `201` (`400` malformed, `409` duplicate, `422` not for us) |
| POST   | `/api/qualitynotifications/update`   | Status update → `200` (`404` unknown, `422` not allowed by the state model) |

Partner sync reads only the twins own parts are linked to (one level) and only their
SerialPart/Batch submodels — never a partner's BoM or usage. Contract agreements and access tokens
are reused through the Tractus-X SDK's connection manager (in memory, per process).

Quality notifications: an **alert** goes to the direct customers of the affected own parts, an
**investigation** to the direct suppliers of the affected supplier parts — both from the local tree.
Sending fetches the partner's catalog for the KIT `dct:type`, picks the highest
`cx-common:version` we speak (2.0.0, else 1.2.1; none → no negotiation), negotiates and POSTs.
`RECEIVED` is set when the partner answers with success; a failed delivery keeps the draft with
the error. Status changes are only applied locally once the partner accepted the update. A
received notification can be forwarded one hop: its forward plan derives the next hop's parts
(alert: own parts containing the affected supplier parts; investigation: supplier parts in the
affected own parts) and the new notification is linked to it locally. We publish 8 assets
(receive/update × alert/investigation × 1.2.1/2.0.0), all served by the same two endpoints.

Partner health checks are cumulative: `discovery` resolves the partner's connector, `catalog`
also looks for the DTR offer and the notification offers we need for the partner's roles, and
`full` also negotiates the DTR and reads one shell descriptor through the EDR. `full` creates
negotiation and transfer state in both connectors, so it needs `confirm_state_change: true`
(else `409`). Only one check runs at a time (`409` while busy); `503` when no checker is
configured. Each check is stored (`partner_checks` table) with its steps; error details are
scrubbed of credentials.

Every sync run is stored (`sync_runs` table) with its counters and issues. Timestamps are returned
in UTC.

Interactive documentation: `/docs`.

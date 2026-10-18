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
  migrations/     database migrations (Alembic), applied at startup
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
| `CXS_OAUTH_*`                   | OAuth 2.0 client credentials for the own DTR: `CLIENT_ID`, `CLIENT_SECRET`, optional `SCOPE`, and either a Keycloak `URL` + `REALM` or any `TOKEN_URL` (wins) |
| `CXS_SUBMODEL_HREF_REWRITES`    | JSON list of `[public_prefix, internal_prefix]`: reads own submodels from the backend instead of the public data plane. Without it (and with an EDC), a data plane that refuses a direct read (401/403: it wants an EDR) is read through the own EDC instead: the app negotiates with its own connector (the `dspEndpoint` in the descriptor's `subprotocolBody`) for the submodel's asset, so the accepted policies must include the own offers' policies |
| `CXS_SUBMODEL_HEADERS`          | JSON object of extra headers for the submodel backend (e.g. an API key) |
| `CXS_EDC_MANAGEMENT_URL`        | Own EDC management API (Saturn); with `CXS_EDC_MANAGEMENT_PATH`. Enables partner sync |
| `CXS_EDC_API_KEY`               | Sent as `X-Api-Key` to the management API |
| `CXS_EDC_OAUTH_*`               | Or OAuth 2.0 client credentials for the management API (`TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET`, optional `SCOPE`); a fresh token is sent with every call. Both can be set |
| `CXS_ACCEPTED_POLICIES`         | JSON list of usage policies accepted in partners' catalogs; empty = no negotiation. Compared by meaning: Jupiter (`cx-policy:FrameworkAgreement`, `odrl:eq`) and Saturn spellings (`FrameworkAgreement` or its `https://w3id.org/catenax/policy/` IRI, `eq`) match, the order of constraints does not matter; the constraints themselves must be the same. An admin can add more on the Setup page; the app accepts both lists |
| `CXS_ACCEPT_ANY_POLICY`         | Accept any offered policy — development only                         |
| `CXS_PARTNER_CONNECTORS`        | JSON object BPNL → partner DSP endpoint (addresses set through the API win) |
| `CXS_CENTRAL_IDP_*`             | Technical user of the dataspace's central IdP (`URL`, `REALM` (default `CX-Central`), `CLIENT_ID`, `CLIENT_SECRET`) for the core services below; independent of the DTR's `CXS_OAUTH_*` |
| `CXS_DISCOVERY_FINDER_URL`      | Discovery Finder (`…/api/v1.0/administration/connectors/discovery/search`): finds partners' DSP endpoints by BPNL on the Setup page |
| `CXS_EDC_DISCOVERY_URL`         | EDC Discovery (`…/api/administration/connectors/discovery`), asked directly instead of through the Discovery Finder; wins when both are set |
| `CXS_BPDM_POOL_URL`             | BPDM Pool API up to the version segment (e.g. `https://business-partners.example/pool/api`): partners' legal names by BPNL (`/v7/legal-entities/{bpnl}`) |
| `CXS_BP_EXPLORER_ADDRESS`       | Or a BPDM Pool offered through an EDC, such as the Cofinity-X Business Partner Explorer (subscribe to "BP Explorer" in their marketplace first): its DSP endpoint, e.g. `https://business-partner-explorer-edc.dataspaceos.svc.cofinity-x.com/api/v1/dsp` (pre-production `https://business-partner-explorer-edc.dataspaceos.preprod.cofinity-x.com/api/v1/dsp`). Our EDC negotiates for its asset and reads the Pool's `/v6/members` API (`POST /legal-entities/search` with `bpnLs`). Needs an EDC and an accepted policy matching the offer; wins over `CXS_BPDM_POOL_URL` |
| `CXS_BP_EXPLORER_BPNL`          | BPN of the explorer's connector (default `BPNLCOFINITYEZFA`, Cofinity-X) |
| `CXS_BP_EXPLORER_ASSET_ID`      | The asset to negotiate for; needed only if the explorer's catalog offers us more than one |
| `CXS_NOTIFICATION_BASE_URL`     | Where our EDC's data plane reaches this app; with an EDC, the notification assets are published at startup |
| `CXS_NOTIFICATION_API_KEY`      | Required as `X-Api-Key` on `/api/qualitynotifications/*`; also put in the assets' data address |
| `CXS_NOTIFICATION_ACCESS_POLICY`, `CXS_NOTIFICATION_USAGE_POLICY` | JSON ODRL permissions of the notification assets; defaults: active membership / `DataExchangeGovernance:1.0` + `cx.core.qualityNotifications:1` |
| `CXS_NOTIFICATION_ASSET_PREFIX` | Prefix of the asset, policy and contract IDs (default `cxs-qualitynotification`) |
| `CXS_DEV_DIRECT`                | **Development only.** Reach partners without EDCs: notifications are posted to the partner apps (`CXS_PARTNER_CONNECTORS` = their base URLs), partner twins read from `CXS_DEV_PARTNER_DTRS` (BPNL → DTR URL with API path). Never in a dataspace |
| `CXS_SYNC_TWIN_IDS`             | Load only these own twins, e.g. to test with a few vehicles of a registry with millions of twins: AAS IDs (or globalAssetIds) one per line, or any text containing them — every `urn:uuid:…` is taken, so a CSV can be pasted (also on the Setup page, at most 10,000). Own children in their bills of material are loaded too; the cache then holds only this subset. Empty: the whole DTR |
| `CXS_SYNC_INTERVAL_SECONDS`     | Periodic sync (own twins, then partners); `0` (default) disables it   |
| `CXS_WEB_DIST_DIR`              | Directory of the built UI, served at `/`                             |
| `CXS_ADMIN_PASSWORD_HASH`       | Enables the admin login (with `CXS_SECRET_KEY`); create it with `uv run python -m catenax_simplified.admin hash-password`. `CXS_ADMIN_USERNAME` defaults to `admin` |
| `CXS_SECRET_KEY`                | At least 32 characters (`uv run python -m catenax_simplified.admin secret-key`): signs admin sessions and encrypts the secrets entered in the UI. Keep it stable — another key cannot read them |
| `CXS_ADMIN_SESSION_HOURS`       | Admin session lifetime, 1–24 hours (default 8)                        |
| `CXS_EXTRA_CA_DIR`              | Directory of extra CA certificates trusted next to the public ones (see below); the image sets `/etc/catenax-simplified/ca-certificates` |

## Private CA certificates

The app only trusts the public CAs (certifi's bundle). When your EDC, DTR or IdP uses an HTTPS
certificate issued by your company's own CA, calls to it fail with
`CERTIFICATE_VERIFY_FAILED … self-signed certificate in certificate chain`; the connection test on
the Setup page says so and points here.

Put the root CA certificate (`*.crt`, `*.pem` or `*.cer`; PEM, a PEM chain, or DER) into the
directory of `CXS_EXTRA_CA_DIR` and restart. At startup the app writes certifi's bundle plus those
certificates to one file and points `REQUESTS_CA_BUNDLE` and `SSL_CERT_FILE` at it, so the public
CAs stay trusted. The log names the certificates it added. Other and hidden files are ignored.

- **Docker Compose:** drop the certificate into [`deploy/certs/`](../deploy/certs/README.md)
  (git-ignored), or set `CXS_CA_CERTS_DIR` to another directory; `deploy/compose.yaml` mounts it.
- **`docker run`:** `-v ./certs:/etc/catenax-simplified/ca-certificates:ro`.
- **Helm:** `caCertificates` in the chart's values — an existing ConfigMap or Secret, or the PEM
  inline (see the [chart's README](../deploy/helm/catenax-simplified/README.md)).
- **Locally (`uv run`):** `CXS_EXTRA_CA_DIR=/path/to/certs`.

If you set `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE` yourself, that bundle wins and the directory is
not used (it must then contain the public CAs as well). This is about the services the app calls at
runtime; a TLS-inspecting proxy during `docker build` is the build secret described in the
[repository README](../README.md#container-image).

## Admin and settings entered in the UI

With `CXS_ADMIN_PASSWORD_HASH` and `CXS_SECRET_KEY` set, an admin signs in on the web UI
(*Admin sign-in*) and can:

- enter the connection settings on the Setup page — the DTR, the EDC management API, the
  notification inbox and the dataspace services, with their OAuth clients and keys. They are stored
  in the database (secrets encrypted with a key derived from `CXS_SECRET_KEY`), applied at once
  without a restart, and tested right away;
- add, change and remove partners (without the admin login anyone can, as before).

A setting the deployment sets (an environment variable or `.env`) always wins and is shown locked;
the UI only fills in what the deployment leaves out. Reading parts, partners and notifications needs
no sign-in. After five failed sign-ins from one address, sign-in is refused for 15 minutes; behind a
proxy that hides client addresses this applies to everyone at once. The session cookie is
`HttpOnly`, `SameSite=Strict`, and `Secure` when the app is reached over HTTPS (the image runs
uvicorn with `--proxy-headers`). Changes are logged with the admin and the setting names, never
the values.

If `CXS_SECRET_KEY` changes, the secrets entered in the UI can no longer be decrypted: they are
ignored, and the Setup page asks for them again.

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
| PUT    | `/api/partners/{bpnl}`       | Add a partner, or set its name and DSP connector address |
| DELETE | `/api/partners/{bpnl}`       | Forget what was set for a partner; one found in own twins stays listed |
| GET    | `/api/partners/{bpnl}/discovery` | DSP endpoints registered for a BPNL in the discovery services (nothing is stored) |
| GET    | `/api/auth/me`               | Whether the admin login is set up and who is signed in |
| POST   | `/api/auth/login`, `/api/auth/logout` | Admin sign-in (sets the session cookie) and sign-out |
| GET    | `/api/setup/config`          | **Admin.** The settings that can be entered in the UI: source (deployment or UI), locked, value (never for secrets) |
| PUT    | `/api/setup/config`          | **Admin.** Store settings (`null` removes one), apply them at once and return the connection tests |
| GET    | `/api/setup/policies`        | The accepted usage policies: the deployment's (locked) and those added on Setup, each with a short form |
| PUT    | `/api/setup/policies`        | **Admin.** Replace the policies added on Setup (`{"added": [...]}`, ODRL bodies) and apply them at once; one that means the same as an accepted policy is kept once |
| POST   | `/api/setup/policies/offers` | **Admin** once the login is set up. Read a connector's catalog through the own EDC (`bpnl`, optional `connector_address`, optional `asset_id`; without it, the DTR offer) and list the offered policies, each with whether it is accepted. Nothing is negotiated |
| POST   | `/api/setup/connection-tests` | Read-only calls to the own DTR and EDC and the core services with the configured credentials; one result each (the Business Partner Explorer: its catalog only, no negotiation) |
| GET    | `/api/partners/{bpnl}/legal-entity` | A BPNL's legal name from the BPDM Pool or the Business Partner Explorer (nothing is stored) |
| POST   | `/api/partners/names`        | Name every unnamed partner after its legal name in the BPDM Pool or the Business Partner Explorer |
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

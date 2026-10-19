# Developing

Where things live in the code, how a request travels through it, and how to make the common
changes. For what the app does see [what-the-app-does.md](what-the-app-does.md); for the design
decisions, [architecture.md](architecture.md); for conventions, setup and checks before a push,
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Code map

### Backend (`backend/src/catenax_simplified/`)

| Package | What it holds | Depends on |
|---|---|---|
| `config.py` | `Settings`: every `CXS_*` variable | — |
| `aspects/` | Aspect model versions (`registry.py`, the only place that names a model URN), payload adapters to the internal model (`adapters.py`, `model.py`), Catena-X ID handling | — |
| `dataspace/` | Everything that talks to the outside: own DTR (`dtr.py`) and submodels (`submodels.py`), partners through the EDC (`edc.py`, `partners.py`, `notifications.py`, `health.py`), notification assets in the own EDC, discovery, BPDM names, OAuth, connection tests, development-mode doubles (`direct.py`). Interfaces in `ports.py` and as `Protocol`s next to their implementations | Tractus-X SDK, `aspects` |
| `storage/` | Tables (`tables.py`), repositories (`repository.py`), engine and migrations at startup (`db.py`); migrations in `migrations/` | SQLAlchemy |
| `traceability/` | Own-twin sync, partner sync, one-level tree, partner checks, data checks | `dataspace` interfaces, `storage` |
| `notifications/` | Quality notifications: payloads of both API versions (`messages.py`), the KIT state model (`states.py`), the service (`service.py`) | `dataspace` interfaces, `storage` |
| `admin/` | Admin login, encrypted settings entered in the UI | `storage` |
| `api/` | FastAPI app and `Runtime` (`app.py`), schemas, notification endpoints, admin endpoints | everything above |
| `wiring.py` | Builds the adapters from the settings (`build_*`) | everything above |

Domain code (`traceability`, `notifications`) only sees interfaces (`TwinRegistry`,
`SubmodelReader`, `PartnerDataClient`, `NotificationSender`, `PartnerHealthChecker`). The
concrete classes are chosen in `wiring.py`, so tests and development mode swap them freely.

### Web UI (`web/src/`)

One file per page (`PartList`, `PartDetail`, `Notifications`, `NotificationDetail`, `Compose`,
`Partners`, `SyncHistory`, `Setup`, `Login`), a few shared parts (`ui.tsx`, `icons.tsx`,
`DataChecks.tsx`, `PartnerHealth.tsx`, `ConnectorOverview.tsx`, `Checklist.tsx`,
`ConfigEditor.tsx`), the shell and routing in `App.tsx`, and the API client and types in
`api.ts`. Styles are plain CSS in `styles.css`, with the colour tokens on `:root`. React only, no
UI framework.

**Themes**: every colour is a token on `:root` at the top of `styles.css` (light), redefined at its
end for dark, under `prefers-color-scheme: dark` and again under `:root[data-theme="dark"]`. A new
colour gets a token in all three places, never a literal in a rule. `Theme.tsx` holds the
System / Light / Dark switch in the top bar; the choice is kept in `localStorage` and applied by a
small script in `index.html` before the first paint.

## How a request travels

**Sync own twins** (`POST /api/sync`):
`api/app.py:trigger_sync` → `ExclusiveRunner.start` (one sync at a time, in a background thread;
the API answers 202 and the UI polls `GET /api/sync/status`) →
`traceability/sync.py:OwnTwinSync.run` → `TwinRegistry.iter_twins` (SDK, paged) → per twin,
`SubmodelReader.read` for each supported submodel → `aspects.parse` (picks the adapter from the
`semanticId`) → `PartRepository.upsert_part` / `replace_relations` → a `SyncRunRow` in the
history. If the data plane refuses a direct read (401/403), `EdcFallbackSubmodelReader` reads
through the own EDC from then on.

**Send a quality alert** (`POST /api/notifications` with `send`):
`api/notifications.py:create` → `NotificationService.create` (`plan_recipients` on the local tree,
one draft per customer) → `NotificationService.send` → `EdcNotificationSender.send` (partner
catalog, highest compatible Notification API version, accepted policy, negotiation, POST through
the EDR) → status `SENT`, then `RECEIVED` when the partner answers 201.

**Receive one** (`POST /api/qualitynotifications/receive`, called by the own EDC's data plane):
API key check → `NotificationService.receive` (one parser for 1.2.1 and 2.0.0) → a
`NotificationRow` in the inbox.

## Common changes

### Support a new aspect model version

1. Add the official example payload from `eclipse-tractusx/sldt-semantic-models` to
   `backend/tests/fixtures/aspects/` as `<namespace>-<version>.json`, unmodified.
2. Register the version in `aspects/registry.py` (`SUPPORTED`) with the payload shape it has.
3. If the shape is new, map it in `aspects/adapters.py`. Nothing outside `aspects` changes.

The fixture test reads every file in that folder, so the new version is tested at once.

### Add an API endpoint

1. A handler in `api/app.py` (or `api/notifications.py`, `api/admin.py`) with a response model
   from `api/schemas.py`. Its docstring is the endpoint's description in `/docs`.
2. Logic that is more than reading the cache goes into `traceability/` or `notifications/`, not
   into the handler.
3. A test in `tests/test_api.py` (the `client` fixture runs the app on the test scenario), the
   type and the call in `web/src/api.ts`, and a row in the API table of `backend/README.md`.

### Add a setting

1. A field in `config.py` (`Settings`), with a comment saying what it is for.
2. If an admin may enter it in the UI, a `ConfigField` in `admin/config_store.py` (`FIELDS`).
3. Use it in `wiring.py` when it changes how an adapter is built.
4. Document it in `backend/.env.example` and `backend/README.md`.

### Talk to a new dataspace service

Put the client in `dataspace/` behind a `Protocol`, build it in `wiring.py` from the settings,
and give `ConnectionTester` a read-only test for it so the Setup page can check it. Domain code
gets the interface, never the client.

### Add a data check

Data checks read only the local cache. Add the rule to `traceability/data_checks.py` as a new
`kind` of `DataFinding`, extend `DataFindingOut.kind` in `api/schemas.py` and `DataFinding` in
`web/src/api.ts`, and give it a label and a sentence in `web/src/DataChecks.tsx`. Test it with
rows built directly in a session, like `tests/test_data_checks.py`.

### Change the database

Change `storage/tables.py` and generate a migration as described in
[CONTRIBUTING.md](../CONTRIBUTING.md#conventions). `tests/test_migrations.py` fails while tables
and migrations disagree.

## Tests

- `tests/scenario.py` is a small Tier-1 battery module maker mixing v3 and v4; most API and sync
  tests run on it.
- `tests/builders.py` builds submodel payloads and shell descriptors in the published shapes,
  `tests/fakes.py` has in-memory doubles of the dataspace interfaces.
- HTTP calls to the DTR, data planes and EDC are mocked with `responses`; nothing needs a network.
- For a manual run, `backend/devtools/mock_participant.py` serves a DTR and submodels, and
  `backend/devtools/demo_network.py` runs three companies without EDCs (development mode).

## Documentation in the code

Every module starts with a docstring saying what it is for. Public classes and functions have
one when their name does not say it all: what it does, and why when that is not obvious.
Endpoint docstrings and schema docstrings are what `/docs` shows. Comments explain why, not
what. In the web UI, each file starts with a comment saying what the page or part does.

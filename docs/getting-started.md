# Getting started

How to get catena-x-simplified running, from a laptop demo to an instance next to your company's
EDC and DTR, and what to check when something does not work. For what the app does, see
[what-the-app-does.md](what-the-app-does.md); for the code, [developing.md](developing.md); for
every setting, [backend/README.md](../backend/README.md#configuration).

## Pick a mode

| Mode | What you get | Needs |
|---|---|---|
| [1. Local, mock participant](#1-local-mock-participant) | One company with six battery modules from a mock DTR; parts, structure, data checks | Python, Node |
| [2. Three-company demo](#2-three-company-demo) | Tier-2 → Tier-1 → OEM on one machine; partner sync and quality notifications end to end, without EDCs | Python, Node |
| [3. Next to a real EDC and DTR](#3-next-to-a-real-edc-and-dtr) | The app against your company's connector and registry, reading partners through the dataspace | Docker, your company's settings |

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 22, and for mode 3
Docker with Compose. Depending on the installation, Compose is `docker compose` or
`docker-compose`; the commands below use the first.

```bash
git clone https://github.com/pedrobtmartins/catena-x-simplified.git
cd catena-x-simplified
```

## 1. Local, mock participant

Three terminals; the [README's quick start](../README.md#quick-start) explains each step.

```bash
cd backend && uv sync && uv run python devtools/mock_participant.py --port 8081
```

```bash
cd backend && cp .env.example .env && uv run uvicorn catenax_simplified.main:app --reload
```

```bash
cd web && npm install && npm run dev
```

Open http://localhost:5173 and click **Sync own twins**. The API's documentation is at
http://localhost:8000/docs.

## 2. Three-company demo

```bash
cd web && npm install && npm run build && cd ../backend
uv sync
uv run python devtools/demo_network.py
```

Tier-1 is at http://127.0.0.1:8001, Tier-2 at :8002, the OEM at :8003. Each company gets its own
mock DTR, database and app, and the script syncs everything once at start. Ctrl-C stops all of
it; the next start begins from fresh data.

- The apps run in **development mode**: partners are reached directly, not through EDCs, and the UI
  says so on every page. It shows the app's behaviour, not dataspace connectivity.
- They serve the UI from `web/dist`. After pulling a new version, rebuild the UI **and** restart the
  demo: an old backend serving a new UI gives confusing errors.

## 3. Next to a real EDC and DTR

### What to ask your company for

| Item | Setting | Notes |
|---|---|---|
| The company's BPNL | `CXS_OWN_BPNL` | |
| DTR address and its OAuth client | `CXS_DTR_BASE_URL`, `CXS_OAUTH_*` | Plus `CXS_SUBMODEL_HREF_REWRITES` if submodels are read from an internal backend |
| EDC management API and its key or OAuth client | `CXS_EDC_MANAGEMENT_URL`, `CXS_EDC_API_KEY` / `CXS_EDC_OAUTH_*` | Without it, there is no partner sync and no notifications |
| The company's root CA certificate, if the EDC, DTR or IdP use internal certificates | a file in `deploy/certs/` | See [Private CA certificates](../backend/README.md#private-ca-certificates) |
| The usage policies the company accepts | `CXS_ACCEPTED_POLICIES`, or the Setup page | Without any, the app negotiates with no one |
| Dataspace services (central IdP user, discovery, BPDM) | `CXS_CENTRAL_IDP_*`, `CXS_EDC_DISCOVERY_URL` or `CXS_DISCOVERY_FINDER_URL`, `CXS_BPDM_POOL_URL` or `CXS_BP_EXPLORER_*` | Optional: connector addresses by BPNL and partner names |
| Where the EDC's data plane reaches this app, and an API key | `CXS_NOTIFICATION_BASE_URL`, `CXS_NOTIFICATION_API_KEY` | Only to receive quality notifications |

### Steps

1. **Settings.** Copy the example and fill it in; every line is commented.

   ```bash
   cp deploy/.env.example deploy/.env
   ```

   `deploy/.env` holds secrets and is git-ignored. Never commit it, and do not send it by chat or
   email: pass it through a password manager or another secure channel, or better, give each
   person their own credentials.

2. **CA certificate** (if needed): drop the root CA (`.crt`/`.pem`) into `deploy/certs/`.

3. **Admin login**, so settings and partners can be changed in the UI:

   ```bash
   cd backend
   uv run python -m catenax_simplified.admin hash-password   # → CXS_ADMIN_PASSWORD_HASH
   uv run python -m catenax_simplified.admin secret-key      # → CXS_SECRET_KEY, keep it stable
   ```

   Put both into `deploy/.env`. Only the hash is stored: a forgotten password cannot be recovered,
   only replaced with a new hash. Changing `CXS_SECRET_KEY` makes the secrets entered in the UI
   unreadable.

4. **Start** the app and its Postgres:

   ```bash
   docker compose -f deploy/compose.yaml up -d --build
   ```

   It listens on port 8000 (`CXS_PORT` in `deploy/.env` changes it). For a second instance on the
   same machine, give it another project name and port:
   `CXS_PORT=8020 docker compose -p my-test -f deploy/compose.yaml up -d --build`.

5. **Check the connections** on the **Setup** page (sign in as admin): test the DTR, the EDC and the
   dataspace services. The checklist there shows what is still missing.

6. **Accepted policies.** On the Setup page, under accepted usage policies, read a partner's catalog
   for an asset: the app lists each offered policy and whether it is accepted, and an admin can
   accept it as offered. Nothing is negotiated by reading the catalog.

7. **First sync: start small.** With a large registry, paste a few twin IDs (or a CSV containing
   them) into the twin selection on the Setup page (`CXS_SYNC_TWIN_IDS`). Then click **Sync own
   twins**, and look at **Sync history** and **Data checks**.

8. **Partners.** On **Partners**, find each partner's connector (discovery, or enter it by hand),
   then check it:
   - **Catalog** only reads: start there.
   - **Full** negotiates and creates contracts in both connectors.

   Then sync the partners: all of them, one partner, or only the supplier parts under one part
   from that part's **Structure** panel.

### Updating

```bash
git pull
docker compose -f deploy/compose.yaml up -d --build
```

The schema migrates at startup. A restart drops the cached contracts and tokens, so the first sync
afterwards negotiates again, and a sync running during the restart is cut off: let it finish
first.

## Working together

- **Code:** one branch and one pull request per change. Run the checks in
  [CONTRIBUTING.md](../CONTRIBUTING.md#before-you-push) before pushing; CI runs the same.
- **Two instances against the same EDC** both publish the notification assets at startup, under the
  same IDs and each with its own address, so the last one to start receives the partners'
  notifications. Leave `CXS_NOTIFICATION_BASE_URL` unset on the second, so it publishes nothing.
  A different `CXS_NOTIFICATION_ASSET_PREFIX` also works, but partners then see two sets of
  notification assets in your catalog.
- **Each instance negotiates on its own** with the partners it syncs. For a large partner, agree
  who runs the full sync rather than both doing it at once.
- **Screenshots or reports leaving the team:** remove partner names, serial numbers and BPNLs.

## When something does not work

| Symptom | Likely cause | What to do |
|---|---|---|
| `CERTIFICATE_VERIFY_FAILED … self-signed certificate in certificate chain` | The EDC, DTR or IdP uses the company's own CA | Put the root CA into `deploy/certs/` and restart |
| Setup's EDC test times out; partner checks fail at *Connector discovery* with a 5xx from the own connector | The own EDC's management API is slow or down, not the partner | Ask whoever runs the EDC; retry later |
| `no accepted usage policies configured`, or `Offered: … Accepted: …` | No accepted policy matches the partner's offer | Accept the offered policy on the Setup page, if the company agrees with it |
| `… returned HTTP 5xx from the partner's data plane` | The partner's data plane or the DTR behind it failed | On their side: copy the check's report for the partner. A failing `GET /lookup/shells` is already retried as `POST /lookup/shellsByAssetLink` |
| `… refused the access token` | The token expired or the partner refused it; the app already renewed it once | If it persists, the partner should check its policy and data plane |
| A partner sync ends *partial* with twins missing | The partner publishes no twins with those Catena-X IDs, or does not let you see them | Compare the IDs in your bills of material with the partner's twins: a data issue to settle with the partner |
| A connector is *healthy* but notifications are *incomplete* | The partner does not offer all the quality-notification assets | Separate use case: the connector is fine for reading twins |
| The UI shows old screens or a strange error right after an update | The browser holds the old UI, or the backend did not restart | Reload the page; rebuild and restart the app (both, in the demo) |
| `401` from `/api/partners/…` | An admin login is set up | Sign in as admin first |

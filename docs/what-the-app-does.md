# What the app does

A functional description of catena-x-simplified: what it reads, what it shows, what it sends and
what it deliberately leaves to others. For the design and the decisions behind it, see
[architecture.md](architecture.md); for the terms, the [glossary](glossary.md); for every setting,
[backend/README.md](../backend/README.md#configuration).

## In one paragraph

The app answers the Traceability KIT's question *"a part is defective — which of my products
contain it, which customers must I warn, which supplier must investigate?"* for **one company**.
It reads the company's own parts from its Digital Twin Registry (DTR) into a local database,
links each part one level up and down (its components and the customers it went to), reads the
matching parts of its **direct** partners through the company's EDC, and exchanges **quality
alerts and investigations** with those partners following the KIT. It never walks the supply
chain beyond the direct partners: a deeper level is reached when the partner forwards the
notification, hop by hop, with its own copy of the app or any other KIT-compliant application.

## What it needs and what it does not do

The company must already be a Catena-X participant. The app **uses**, and does not install:

| The company already runs | The app uses it to |
|---|---|
| EDC connector (Tractus-X, Saturn) | negotiate with partners, read their data, receive and send notifications |
| Digital Twin Registry | find the company's own twins |
| Submodel server / data plane | read the aspect models of those twins |
| Identity (BPNL, wallet) | — (the EDC uses it; the app only needs the BPNL) |

It does **not**:

- publish the company's own part data (that is the Industry Core KIT's job, done before the app);
- read a partner's bill of materials or usage, or anything beyond the direct partners (no IRS);
- decide anything on its own: notifications are created, sent, answered and forwarded by a user.

## What it does, step by step

### 1. Loads the company's own parts

*UI: **Parts**, **Sync history** · API: `POST /api/sync`, `GET /api/sync/last`, `GET /api/sync/runs`*

- Reads every twin of the own DTR (AAS API v3, paged), or only a **selection** for a test
  (`CXS_SYNC_TWIN_IDS`, also pasteable as a CSV on the Setup page): the listed twins plus, through
  their bills of material, their own children.
- For each twin, reads the submodels it understands, in their value-only form:

  | Internal model | Accepted aspect models |
  |---|---|
  | Part (serialized) | SerialPart 3.0.0, 3.0.1, 4.0.0; industry_core SerialPart 4.0.0 |
  | Part (batch) | Batch 3.0.0, 3.0.1, 4.0.0; industry_core Batch 4.0.0 |
  | Components | SingleLevelBomAsBuilt 3.0.0, 4.0.0; industry_core 4.0.0 |
  | Customers | SingleLevelUsageAsBuilt 3.0.0, 4.0.0; industry_core 4.0.0 |

  Versions are mixed freely; each is mapped to the same internal model, so a partner on
  SerialPart 3 and one on 4 look the same in the app.
- Reads each submodel **directly** (optionally rewriting the public address to an internal one).
  When the data plane refuses a direct read because it wants a contract (HTTP 401/403), the app
  reads the company's own submodels **through its own EDC**, like a partner's: one negotiation per
  shared asset, then plain reads with the access token.
- Stores the parts and their one-level relations locally, removes parts that disappeared from the
  registry, and records every run: twins, parts, relations, unsupported submodels and each
  problem, with the submodel it concerns.
- Runs on demand (**Sync own twins**) or periodically (`CXS_SYNC_INTERVAL_SECONDS`).
- **Checks the bills of material** it has read (`GET /api/data-checks`, shown in Sync history and on
  the affected parts): a serialized unit is in one place at a time, so the app reports a part declared
  in an assembly and again in one of its sub-assemblies, or in two own parts that do not contain one
  another (unless it is a batch). Findings sharing the same assemblies are listed together, since they
  usually have one cause: a twin to correct where it is published.

### 2. Shows the parts and their tree

*UI: **Parts**, part detail · API: `GET /api/parts`, `/api/parts/{id}`, `/api/parts/{id}/tree`, `/api/stats`*

- A searchable list of own parts (by Catena-X ID, part number or name; serialized or batch;
  aspect model v3 or v4), with counts of own parts, links to suppliers and links to customers.
- Per part: its attributes, the submodels they came from, and the **as-built tree one level deep**:
  the components it contains (and from which supplier) and the customers it was delivered to.
  Answers come from the local database, not from the network, so they are immediate.

### 3. Knows the direct partners

*UI: **Partners**, **Setup** · API: `/api/partners…`*

- The direct partners are **derived from the data**: every BPNL named as a supplier in the bills
  of material or as a customer in the usage relations.
- Each partner needs the address of its connector (DSP endpoint). It comes from the deployment's
  settings, is entered by hand, or is looked up by BPNL in the dataspace's **discovery** services
  (Discovery Finder or EDC Discovery), from which the user picks one.
- Partner **names** come from the BPDM Pool, directly or through an EDC where the operating
  company offers it that way (the Cofinity-X Business Partner Explorer).
- **Partner sync** (`POST /api/partners/sync`): for every partner, negotiates access to its DTR,
  looks up the counterpart twins of the own relations by Catena-X ID and reads their SerialPart or
  Batch. It reads nothing else: no partner bill of materials, no partner usage.

### 4. Checks the partners' connectors

*UI: **Partners** (connector health) · API: `/api/partners/checks`, `/api/partners/{bpnl}/checks`*

Before relying on a partner, the app can check its connector with the same path it uses for
real work, at three cumulative levels:

1. **Discovery**: the partner's connector is found and answers with its DSP address and protocol.
2. **Catalog**: it offers a DTR and the notification assets this partner needs (with a warning for
   an incompatible Notification API version).
3. **Full**: negotiates the DTR and reads one shell descriptor through the access token. This
   creates contracts in both connectors, so it asks for confirmation.

Checks run one at a time and are stored per partner. A failed check can be copied as a report to
send to the partner.

### 5. Exchanges quality notifications

*UI: **Notifications** (inbox, outbox, detail, composer) · API: `/api/notifications…` · KIT endpoints: `/api/qualitynotifications/receive`, `/update`*

- **Alert** (to customers, downstream): the user picks affected own parts; the app proposes the
  recipients from the local usage relations: the direct customers that received those parts.
- **Investigation** (to suppliers, upstream): the user picks suspect components; the app proposes
  the direct suppliers from the local bills of material.
- **Sending**: the app finds the partner's notification asset in its catalog, picks the highest
  version both sides support (Notification API **2.0.0**, else **1.2.1**), checks the offered usage
  policy against the company's accepted ones, negotiates and delivers. A failed delivery stays a
  draft with the error, to be retried.
- **Receiving**: at startup the app publishes **eight assets** in the company's EDC (receive and
  update × alert and investigation × 1.2.1 and 2.0.0) with the KIT's policies; partners' messages
  arrive through the EDC's data plane, protected by an API key. Affected items unknown locally are
  still accepted and shown as unknown: a stale cache must not drop a quality notification.
- **Status**, following the KIT state model: *created → sent → received → acknowledged →
  accepted / declined → closed*. A change is applied locally only once the partner has accepted the
  update; only the sender closes.
- **Forwarding** (the next hop): for a received alert, the app finds the own parts that contain the
  affected components and proposes an alert to *their* customers; for a received investigation,
  the components of the affected parts and an investigation to *their* suppliers. The user reviews
  and sends; the new notification is linked to the one it came from, so each hop shows its
  previous and next hop.
- Every message sent or received is kept in the notification's log.

### 6. Is set up in the browser

*UI: **Setup** · API: `/api/setup/config`, `/api/setup/policies`, `/api/setup/connection-tests`, `/api/auth/…`*

- A guided checklist: the company (BPNL), its DTR, loading the parts, its EDC, receiving
  notifications, the partners' connectors and the dataspace services. The DTR, the EDC, the
  discovery and the BPDM can each be tested from there (**connection tests**).
- An administrator (one local account) signs in to enter or change the connection settings.
  Settings fixed by the deployment win and are shown locked; secrets entered in the UI are stored
  encrypted. A change takes effect without a restart.
- **Accepted usage policies**: the deployment's are shown locked; an admin adds more, which the app
  accepts next to them. To find the policy a connector really offers, the app reads that
  connector's catalog for an asset (only the catalog, nothing is negotiated) and shows each offered
  policy with whether it is accepted, so it can be accepted as offered.

## How it behaves in the dataspace

- **Connectors**: Tractus-X EDC 0.12 (release 26.03), DSP 2025-1 with Saturn policies; partners
  still on Jupiter are reached over DSP 0.8 through the same EDC.
- **Policies**: the app only accepts the usage policies the company lists
  (`CXS_ACCEPTED_POLICIES`, plus those added on the Setup page); if no offer matches, it does not negotiate and says which policies
  were offered. Policies spelled the Jupiter or the Saturn way are compared by meaning.
- **Reuse**: a negotiation happens once per partner, asset and policy set; the access token of an
  asset is reused for a minute, so reading many submodels of one shared asset is a series of
  plain reads. Tokens live in memory: after a restart, the app negotiates again.
- **All dataspace access** goes through the official Tractus-X SDK behind the app's own
  interfaces.

## Deployment and modes

- **One container** (backend and UI), with PostgreSQL; Docker Compose or the Helm chart in
  [`deploy/`](../deploy/compose.yaml). The database schema is migrated at startup.
- The company's own root CA can be mounted and is then trusted for the EDC, DTR and identity
  provider ([Private CA certificates](../backend/README.md#private-ca-certificates)).
- **Development mode** (`CXS_DEV_DIRECT`): partners are reached without EDCs, for local demos
  only (the three-company demo in the [README](../README.md#three-company-demo-no-edcs)). The UI
  says so on every page.

## What has been verified

- **Automated tests** (252) on every change, including every official example payload of the
  supported aspect models and a quality alert passed through three companies, each with its own
  database.
- **Tractus-X umbrella lab** (26.03, local Kubernetes), three companies each with its own EDC,
  DTR, submodel server and app: every app syncs its own twins and reads its direct partners'
  twins through the EDCs, the full connector check is healthy for every partner, and a quality
  alert travels Tier-2 → Tier-1 → OEM with the acceptance coming back on both hops
  ([deploy/umbrella](../deploy/umbrella/README.md#status)).
- **A one-off local test against a production EDC and DTR** (October 2026): a local instance of the
  app synced a selection of 200 vehicles (303 twins with their children) from a production
  registry, reading every submodel through the company's own EDC, with no problems, in
  7.5 minutes. This was a test, not a production deployment.

Not verified yet: notifications with a real partner outside the lab — that is the pilot.

## Not (yet) included

- Block notifications and the KIT's quality tasks / ZeroKmFailure (phase 4).
- Release 26.09 (EDC 0.13, `industry_core` models as the default); reading `industry_core` v4
  is already supported.
- Contracts and tokens kept across restarts; single sign-on with the company's identity
  provider; checking a notification's sender against the contract's BPNL.

# Umbrella 26.03 lab

Three companies on the Tractus-X umbrella's legacy data-exchange profile (wallet stub), each with
its own EDC, Digital Twin Registry, submodel server and an instance of this application:

| Company | Umbrella participant | BPNL | EDC API key | App release |
|---|---|---|---|---|
| Tier-2 (cells, SerialPart 3) | `tx-data-provider` | `BPNL00000003AYRE` | `TEST2` | `cxs-tier2` |
| Tier-1 (modules) | `dataconsumerOne` | `BPNL00000003AZQP` | `TEST1` | `cxs-tier1` |
| OEM (vehicles) | `dataconsumerTwo` | `BPNL00000003AVTH` | `TEST3` | `cxs-oem` |

Files here:

- `values-lab.yaml` — on top of the umbrella's `values-adopter-data-exchange.yaml`: enables
  `dataconsumerTwo`, gives every company its own DTR and submodel server, adds the third BPNL to
  the wallet stub, turns off the umbrella's own (AsPlanned) test data.
- `seed.py` / `seed-job.sh` — seeds each company (submodels, EDC policies/assets/contracts, DTR
  shells) from inside the cluster, using the app image. Every specific asset ID is shared with
  the three BPNs (see [Visibility in the DTR](#visibility-in-the-dtr)).
- `participants.json` — in-cluster endpoints of the three companies.
- `app-tier2.yaml`, `app-tier1.yaml`, `app-oem.yaml` — values of this repository's chart for each
  company's app: its EDC, DTR and submodel server, the direct partners' DSP endpoints, the usage
  policies the seeding and the apps' notification assets offer, the umbrella's test API keys.
  **Lab values only**, never a template for a real dataspace.

## Status

Verified on a local k3s cluster (colima on Apple Silicon), 14–15 October 2026:

- the seeding runs and can be run again; each DTR holds only its own company's twins (18 / 6 / 3);
- the three apps start, publish their notification assets (also again after a restart), sync their
  own twins (18 / 6 / 3) and read every direct partner's twins through the EDCs (discovery over
  DSP 2025-1, negotiation, EDR, DTR, submodels; none missing);
- partner checks pass at every level: the full EDR check (discovery, DTR and notification offers,
  EDR, registry answer) is *Healthy* for every direct partner of every company;
- a quality alert travels Tier-2 → Tier-1 → OEM (Tier-1 forwards it for the module that contains
  the cell), and the acceptance comes back on both hops (Notification API 2.0.0).

The runbook below is put together from those runs; it has not been replayed from an empty machine
in one go yet.

## Runbook

All commands from the root of this repository unless noted. `UMBRELLA` is a checkout of the
umbrella at its 26.03 release.

### 1. Prerequisites

- colima, Docker CLI, kubectl, Helm (4 works; see the note on `helm upgrade`), Python 3 for the
  checks below
- about 8 CPUs and 24 GiB of RAM for the VM (three EDCs, three Vaults, three DTRs, Postgres
  instances, the wallet stub, the apps)
- the umbrella:

  ```bash
  git clone -b release-26.03 https://github.com/eclipse-tractusx/tractus-x-umbrella.git ~/code/tractus-x-umbrella
  ```

  ```bash
  export UMBRELLA=~/code/tractus-x-umbrella
  ```

### 2. Cluster

k3s in colima, with Rosetta on Apple Silicon (the DTR image is amd64 only):

```bash
colima start --kubernetes --vm-type vz --vz-rosetta --cpu 8 --memory 24 --disk 100
```

### 3. Ingress and `*.tx.test` names

The umbrella's components reach each other through ingress host names (`*.tx.test`). Install
ingress-nginx, then make CoreDNS answer those names with the ingress controller (k3s reads the
`coredns-custom` ConfigMap):

```bash
helm upgrade --install ingress-nginx ingress-nginx --repo https://kubernetes.github.io/ingress-nginx -n ingress-nginx --create-namespace --set controller.service.type=LoadBalancer
```

```bash
kubectl -n kube-system create configmap coredns-custom --from-literal=txtest.override='rewrite name regex (.+)\.tx\.test ingress-nginx-controller.ingress-nginx.svc.cluster.local answer auto'
```

```bash
kubectl -n kube-system rollout restart deploy/coredns
```

### 4. Umbrella

```bash
helm dependency build $UMBRELLA/charts/umbrella
```

```bash
helm install umbrella $UMBRELLA/charts/umbrella -n umbrella --create-namespace -f $UMBRELLA/charts/umbrella/values-adopter-data-exchange.yaml -f deploy/umbrella/values-lab.yaml
```

Wait until every pod in `umbrella` is running (the DTRs start slowly under Rosetta):

```bash
kubectl -n umbrella get pods
```

### 5. App image

With colima's Docker runtime, an image built locally is available to the cluster:

```bash
DOCKER_BUILDKIT=1 docker build -t catenax-simplified:latest .
```

### 6. Seed the three companies

```bash
deploy/umbrella/seed-job.sh
```

```bash
kubectl -n umbrella logs job/cxs-seed
```

The log ends with one line per company: 18, 6 and 3 twins, 2 assets each. Run it again any time
(policies, assets, contracts and shells are updated).

### 7. The apps

```bash
for c in tier2 tier1 oem; do helm install cxs-$c deploy/helm/catenax-simplified -n umbrella -f deploy/umbrella/app-$c.yaml; done
```

Each app publishes its 8 notification assets in its EDC at startup; `/api/health` reports
`notification_assets.state: published`. After a new image: `kubectl -n umbrella rollout restart
deploy/cxs-tier2 deploy/cxs-tier1 deploy/cxs-oem`.

To open them (Tier-1 on 8011, Tier-2 on 8012, OEM on 8013; restart the forwards after the apps'
pods are replaced):

```bash
kubectl -n umbrella port-forward svc/cxs-tier1 8011:8000 & kubectl -n umbrella port-forward svc/cxs-tier2 8012:8000 & kubectl -n umbrella port-forward svc/cxs-oem 8013:8000 &
```

### 8. Check the flow

Own twins first in every company (partners come from the own BoM and usage data), then the
partners through the EDCs:

```bash
for p in 8012 8011 8013; do curl -s -X POST "localhost:$p/api/sync?wait=true"; echo; done
```

```bash
for p in 8012 8011 8013; do curl -s -X POST "localhost:$p/api/partners/sync?wait=true"; echo; done
```

Expected: own sync 18 / 6 / 3 twins without issues; partner sync `ok` for every partner (Tier-1
reads Tier-2's 18 and the OEM's 3 twins, Tier-2 reads Tier-1's 6, the OEM the 3 modules it
uses), none missing.

In the UI (e.g. Tier-1 at <http://localhost:8011>):

1. **Partners** → **Check unhealthy**: a read-only catalog check of every partner; both turn
   *Healthy* in the connector overview.
2. A partner's health panel → **Full EDR**: negotiates for the partner's DTR and reads it. It
   creates contract and transfer state in both EDCs, hence the confirmation.
3. **Parts** → a module that the OEM uses (*Used in · customer* is filled, e.g.
   `urn:uuid:aaaaaaaa-0000-4000-8000-000000000002`) → **Send quality alert** → **Create and
   send**. The alert turns *Received* at Tier-1 and shows up in the OEM's inbox (port 8013);
   **Acknowledge** there, and Tier-1's alert turns *Acknowledged*.

### 9. Start over

Remove the apps and the umbrella (the Postgres volumes go with the namespace):

```bash
for c in tier2 tier1 oem; do helm uninstall cxs-$c -n umbrella; done
```

```bash
helm uninstall umbrella -n umbrella && kubectl delete namespace umbrella
```

## Visibility in the DTR

The umbrella's DTRs run without authentication and without granular access control; the caller's
identity is the `Edc-Bpn` header (set by the data plane for a partner, and by the app towards its
own DTR). The DTR shows a shell, with its `globalAssetId`, only to its owning tenant
(`default-tenant` here) and to a BPN that one of its specific asset IDs is shared with
(`externalSubjectId`, one per entry). A call without `Edc-Bpn` sees no shells at all, and
`PUBLIC_READABLE` only works for `manufacturerPartId` and `digitalTwinType`. So the seeding shares
every specific asset ID with all three BPNs.

## Troubleshooting

- **amd64 pods fail with `exec ...: no such file or directory`** (Apple Silicon): the Rosetta
  binfmt handler (flag `F`) holds a stale handle on `/mnt/lima-rosetta/rosetta`. Re-register it
  and delete the failing pods; this keeps the in-memory Vaults:

  ```bash
  colima ssh -- sudo sh -c 'echo -1 > /proc/sys/fs/binfmt_misc/rosetta; echo ":rosetta:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x3e\x00:\xff\xff\xff\xff\xff\xfe\xfe\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/mnt/lima-rosetta/rosetta:OCF" > /proc/sys/fs/binfmt_misc/register'
  ```

  Restarting the VM also works, but wipes the Vaults (next point).
- **EDCs fail with `Failed to fetch client secret from the vault with alias: edc-wallet-secret`**:
  the Vaults run in dev mode (in memory) and lost their secrets with a VM or Vault restart. Re-run
  the umbrella's `*-post-install-vault-setup` jobs (from `helm get hooks umbrella -n umbrella`).
- **`helm upgrade umbrella` fails with a conflict on `caBundle`** (Helm 4): vault-k8s manages the
  webhooks' caBundle; pass `--server-side=false`.
- **Own sync finds 0 twins**: the shells are not shared with the company's BPN (seeding older than
  the sharing with the three BPNs) — run the seeding again.
- **`notification_assets.state: failed` with HTTP 405**: an app older than the fix that updates
  existing policies by ID; rebuild the image and restart the apps.

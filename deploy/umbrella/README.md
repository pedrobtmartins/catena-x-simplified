# Umbrella 26.03 lab (work in progress — seeding verified, app-to-EDC flow not yet)

Three companies on the Tractus-X umbrella's legacy data-exchange profile (wallet stub):

| Company | Umbrella participant | BPNL | EDC API key |
|---|---|---|---|
| Tier-2 (cells, SerialPart 3) | `tx-data-provider` | `BPNL00000003AYRE` | `TEST2` |
| Tier-1 (modules) | `dataconsumerOne` | `BPNL00000003AZQP` | `TEST1` |
| OEM (vehicles) | `dataconsumerTwo` | `BPNL00000003AVTH` | `TEST3` |

- `values-lab.yaml` — on top of the umbrella's `values-adopter-data-exchange.yaml`: enables
  `dataconsumerTwo`, gives every company its own DTR and submodel server, adds the third BPNL to
  the wallet stub, turns off the umbrella's own (AsPlanned) test data.
- `seed.py` / `seed-job.sh` — seeds each company (submodels, EDC policies/assets/contracts, DTR
  shells) from inside the cluster, using the app image.
- `participants.json` — in-cluster endpoints of the three companies.
- `app-tier2.yaml`, `app-tier1.yaml`, `app-oem.yaml` — values of this repository's chart for each
  company's app against its EDC, DTR and submodel server: direct partners' DSP endpoints, the
  usage policies the seeding and the apps' notification assets offer, the umbrella's test API
  keys. Lab values only. Install them into the umbrella's namespace (image as for the seeding):

  ```bash
  for c in tier2 tier1 oem; do
    helm install cxs-$c deploy/helm/catenax-simplified -n umbrella -f deploy/umbrella/app-$c.yaml
  done
  ```

Status: on a local k3s cluster (colima on Apple Silicon) the umbrella with these values runs,
the seeding runs (and can be run again), each DTR holds only its own company's twins (18 / 6 /
3), and Tier-1's EDC gets Tier-2's catalog with both seeded datasets over DSP 2025-1. With the
`app-*.yaml` values the three apps start, publish their notification assets, sync their own twins
(18 / 6 / 3) and read every direct partner's twins through the EDCs (negotiation, EDR, DTR and
submodels; none missing). The seeding shares every specific asset ID with the three BPNs: the
DTR only shows a shell to the BPN in `Edc-Bpn` (which the app sends to its own DTR, and the data
plane on a partner's behalf) that one of its IDs is shared with. Through the EDCs, Tier-1's
partner checks pass at every level (catalog for both partners; full EDR for Tier-2: discovery,
DTR and notification offers, EDR, registry answer), and a quality alert Tier-1 → OEM arrives and
its acknowledgement comes back (Notification API 2.0.0). A full runbook is still to be written.

Notes from that run:

- **Ingress and `*.tx.test` inside the cluster**: install ingress-nginx and point the names at
  it with a CoreDNS rewrite (k3s reads `coredns-custom`):
  `rewrite name regex (.+)\.tx\.test ingress-nginx-controller.ingress-nginx.svc.cluster.local answer auto`.
- **Apple Silicon**: the DTR image (`sldt-digital-twin-registry:0.11.0`) is amd64 only, so the
  VM needs Rosetta (`colima start --kubernetes --vm-type vz --vz-rosetta`). If amd64 pods start
  failing with `exec ...: no such file or directory`, the binfmt handler (flag `F`) holds a stale
  handle on `/mnt/lima-rosetta/rosetta`. Re-register it inside the VM (`colima ssh`, as root:
  `echo -1 > /proc/sys/fs/binfmt_misc/rosetta`, then write the same entry to `.../register`) and
  delete the failing pods. That keeps the in-memory Vaults; restarting the VM also works but
  wipes them (see below).
- **App image**: `seed-job.sh` uses `catenax-simplified:latest`; with colima's Docker runtime,
  `DOCKER_BUILDKIT=1 docker build -t catenax-simplified:latest .` at the repository root makes it
  available to the cluster.
- **The Vaults run in dev mode (in memory)**: after a VM or Vault restart the EDCs fail with
  `Failed to fetch client secret from the vault with alias: edc-wallet-secret`. Re-run the
  umbrella's `*-post-install-vault-setup` jobs (from `helm get hooks umbrella`).
- **Helm 4**: `helm upgrade` conflicts with the caBundle that vault-k8s manages in its webhooks;
  pass `--server-side=false`.

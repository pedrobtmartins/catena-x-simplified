# Umbrella 26.03 lab (work in progress — not yet verified end to end)

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

Status: the umbrella with these values was installed and all pods ran on a k3s cluster; the
seeding has **not** run yet, and the app instances are not configured against the EDCs yet.
A runbook follows once the end-to-end flow has passed.

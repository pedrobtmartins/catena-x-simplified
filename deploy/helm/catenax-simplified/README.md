# Helm chart: catena-x-simplified

Runs the app for one participant, next to its existing EDC and DTR (they are prerequisites, not
part of this chart).

```bash
docker build -t registry.example.com/catenax-simplified:0.1.0 .   # from the repo root, then push
helm install traceability deploy/helm/catenax-simplified -n traceability --create-namespace -f my-values.yaml
```

`my-values.yaml` (see [`values.yaml`](values.yaml) for everything):

```yaml
image:
  repository: registry.example.com/catenax-simplified
  tag: "0.1.0"
config:
  CXS_OWN_BPNL: "BPNL000000000T1A"
  CXS_DTR_BASE_URL: "http://my-dtr:8080"
  CXS_EDC_MANAGEMENT_URL: "http://my-edc-controlplane:8081"
  CXS_NOTIFICATION_BASE_URL: "http://traceability-catenax-simplified.traceability:8000"
  CXS_ACCEPTED_POLICIES: '[{"permission": …}]'
existingSecret: traceability-secrets   # CXS_EDC_API_KEY, CXS_NOTIFICATION_API_KEY, CXS_DATABASE_URL …
```

- Settings are `CXS_*` variables: plain ones in `config` (a ConfigMap), secret ones in `secrets`
  (a Secret the chart creates) or in your own Secret (`existingSecret`).
- Without `CXS_DATABASE_URL` the app uses SQLite on the chart's volume; for production point it to
  Postgres (`postgresql+psycopg://…`). Migrations run at startup.
- One replica: syncs and the EDR cache run in the process.
- Your EDC, DTR or IdP use HTTPS certificates from your company's own CA? Give the app the root CA
  certificate with `caCertificates` (an existing ConfigMap or Secret, or the PEM inline); keys
  ending in `.crt`, `.pem` or `.cer` are mounted into `/etc/catenax-simplified/ca-certificates` and
  trusted next to the public CAs from the next start. Key names must be unique across the sources.
  See [Private CA certificates](../../../backend/README.md#private-ca-certificates).

  ```bash
  kubectl -n traceability create configmap company-ca --from-file=company-root.crt
  helm upgrade traceability deploy/helm/catenax-simplified --reuse-values \
    --set caCertificates.existingConfigMap=company-ca
  ```
- The notification endpoints (`/api/qualitynotifications/*`) must only be reachable through your
  EDC's data plane; don't expose them through the ingress to the internet. Set
  `CXS_NOTIFICATION_API_KEY` — the app adds it to the assets it publishes.

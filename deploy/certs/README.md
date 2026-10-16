# Extra CA certificates

Put your company's root CA certificate(s) here (`*.crt`, `*.pem` or `*.cer`, PEM or DER) when
the EDC, DTR or IdP use HTTPS certificates issued by an internal CA. `deploy/compose.yaml` mounts
this directory into the container; at startup the app trusts these certificates in addition to
the public CAs. Restart the app after adding one:

```bash
docker compose -f deploy/compose.yaml up -d --force-recreate app
```

Certificates are ignored by git (see `.gitignore` here); only this README is committed.

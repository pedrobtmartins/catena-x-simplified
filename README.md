# catena-x-simplified

A lightweight, interoperable traceability application for Catena-X, based on the
Traceability KIT (8.0.0) and the Eclipse Tractus-X 26.03 release.

- Quality Alerts and Quality Investigations (Notification API 1.2.1 and 2.0.0)
- SerialPart/Batch/BoM/Usage aspect models, v3 and v4
- Saturn-only (DSP 2025-1); EDC, DTR and identity are participant prerequisites

See [docs/architecture.md](docs/architecture.md).

## Repository layout

- [`backend/`](backend/README.md) — FastAPI application (Python, Tractus-X SDK)
- [`web/`](web/README.md) — React UI
- [`docs/`](docs/architecture.md) — architecture and decisions

## Status

Phase 1 (core) is implemented: aspect model adapters (v3/v4), own DTR sync via the Tractus-X SDK,
local cache, one-level as-built tree, REST API and a minimal UI. Phase 2 adds partner consumption
via the EDC and quality notifications. See [the phases](docs/architecture.md#10-phases).

# Glossary

Catena-X and Eclipse Tractus-X terms as they are used in this project.

## Network and organizations

| Term | Meaning |
|------|---------|
| **Catena-X** | The data ecosystem of the automotive industry: participants, standards (CX-xxxx) and the rules for sharing data between companies. |
| **Eclipse Tractus-X** | The open-source project that provides reference implementations for Catena-X (connector, registry, SDK, KITs). Releases are named by year and month, e.g. **26.03**. |
| **Participant** | A company in the network, identified by its BPNL. |
| **BPN** (Business Partner Number) | Identifier of a business partner: **BPNL** for a legal entity (`BPNL` + 12 characters), **BPNS** for a site, **BPNA** for an address. |
| **KIT** | A Tractus-X package of documentation, APIs and models for one use case or capability, e.g. the **Traceability KIT** (this app) or the **Industry Core KIT** (the digital twins it builds on). |
| **Umbrella** | The Tractus-X Helm chart that installs a complete reference environment (connectors, registries, wallet stub, sample participants) for development and testing. |

## Dataspace infrastructure

| Term | Meaning |
|------|---------|
| **EDC** (Eclipse Dataspace Connector) | The connector every participant runs to offer and consume data. The **control plane** negotiates contracts; the **data plane** transfers the data. This project targets the Tractus-X EDC. |
| **DSP** (Dataspace Protocol) | The protocol connectors speak to each other: catalog, contract negotiation, transfer. Version **2025-1** is the one used with Saturn policies. |
| **Asset** | Something a connector offers, e.g. a submodel endpoint or a notification endpoint. Classified by `dct:type` and, for notifications, `cx-common:version`. |
| **Contract negotiation / agreement** | The DSP exchange that grants a consumer access to an asset under its usage policy; the result is a contract agreement. |
| **EDR** (Endpoint Data Reference) | The endpoint and access token a consumer receives after a successful negotiation and transfer; reusable until it expires. |
| **Access / usage policy** | ODRL rules on an asset: who may see the offer (access, typically by BPNL) and under which conditions the data may be used (usage). |
| **Jupiter / Saturn** | Generations of Catena-X connector policies. **Jupiter** (DSP 0.8) is supported until the end of 2026; **Saturn** (CX-0152, DSP 2025-1) is the current one. This app is Saturn-only. |
| **DCP / wallet / Identity Hub** | Decentralized identity: each participant holds verifiable credentials in a wallet (Tractus-X Identity Hub) that the connector presents to its partners. |
| **Discovery** | Services (or DID documents) that resolve a partner's BPNL to its connector endpoint. |

## Digital twins and data models

| Term | Meaning |
|------|---------|
| **DTR** (Digital Twin Registry) | A participant's registry of digital twins, implementing the AAS Registry API v3. It holds **shell descriptors**, each with **submodel descriptors** that point to the data. |
| **AAS** (Asset Administration Shell) | The Industrie 4.0 standard the registry and submodel APIs follow. |
| **Digital twin** | A shell descriptor for one real object. Industry Core defines **PartType** (a catalog part) and **PartInstance** (a serialized part or a batch). |
| **Catena-X ID / `globalAssetId`** | The network-wide ID of a twin, `urn:uuid:<UUIDv4>`. Called `catenaXId` in the v3 aspect models. |
| **Submodel** | One aspect of a twin (e.g. its SerialPart data), served by a submodel server. Read in the value-only form at `<href>/$value`. |
| **`semanticId`** | The aspect model a submodel follows, e.g. `urn:samm:io.catenax.serial_part:3.0.0#SerialPart`. The app picks its adapter by this ID. |
| **Aspect model / SAMM** | A data model in the Semantic Aspect Meta Model, published in `eclipse-tractusx/sldt-semantic-models`. |
| **SerialPart / Batch** | Aspect models for a serialized part and a production batch. |
| **SingleLevelBomAsBuilt** | The direct children of a part as built (its bill of materials, one level). |
| **SingleLevelUsageAsBuilt** | The direct parents a part was built into (one level up). |
| **v3 / v4 / industry_core** | Aspect model versions in use: v3 (`catenaXId`, still in release status), v4 (`globalAssetId`, 26.03) and the same v4 moved to the `io.catenax.industry_core.*` namespace (26.09). |

## Traceability

| Term | Meaning |
|------|---------|
| **Quality Alert** | A notification from a supplier to its direct customers: parts it delivered are affected by a quality issue. |
| **Quality Investigation** | A notification from a customer to its direct supplier: please check these parts. |
| **Notification API** | The Traceability KIT API for sending and updating alerts and investigations (`/qualitynotifications/receive`, `/update`); version **1.2.1** is mandatory, **2.0.0** optional. |
| **Notification states** | CREATED → SENT → RECEIVED → ACKNOWLEDGED → ACCEPTED / DECLINED → CLOSED. |
| **Block Notification** | Optional KIT notification that blocks (quarantines) parts in the supply chain. |
| **IRS** (Item Relationship Service) | Tractus-X service that walks the tree of twins across companies recursively. Used by Trace-X; not used here (see [architecture](architecture.md#5-performance-principles-lessons-from-trace-x)). |
| **Trace-X** | The Tractus-X reference traceability app (`traceability-foss`), last included in release 25.06. |
| **One-level tree** | This app's view of a part: its direct parents and children only, from the local cache. |
| **Hop by hop** | Propagation of a notification from one direct partner to the next, each deciding whether to forward it. |

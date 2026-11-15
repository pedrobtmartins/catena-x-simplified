# Roadmap

Phases 1 to 3 are done:
- **Phase 1:** core, registry sync and UI.
- **Phase 2:** partners and quality notifications.
- **Phase 3:** the umbrella lab and a local test against production EDCs.

What comes next is below. Each item links to its issue, where the details and the definition of done live. The issues are grouped in the [Now](https://github.com/pedrobtmartins/catena-x-simplified/milestone/1) and [Next](https://github.com/pedrobtmartins/catena-x-simplified/milestone/2) milestones and carry the [`roadmap`](https://github.com/pedrobtmartins/catena-x-simplified/labels/roadmap) label. What the app does not include today is in [what the app does](docs/what-the-app-does.md#not-yet-included).

## Now

| Item | Why |
|---|---|
| [EDC contracts kept across restarts (#52)](https://github.com/pedrobtmartins/catena-x-simplified/issues/52) | Today every restart, and every settings save, negotiates again with every partner. |
| [Release 26.09 (#53)](https://github.com/pedrobtmartins/catena-x-simplified/issues/53) | EDC 0.13 moves connector discovery to `/v3`, and `industry_core` models become the default. |

## Next

| Item | Why |
|---|---|
| [Block notifications (#54)](https://github.com/pedrobtmartins/catena-x-simplified/issues/54) | The KIT's optional notifications that quarantine parts in the supply chain. |
| [Quality tasks and ZeroKmFailure (#55)](https://github.com/pedrobtmartins/catena-x-simplified/issues/55) | The rest of the Traceability KIT's quality use cases. |
| [Check a notification's sender against the contract (#56)](https://github.com/pedrobtmartins/catena-x-simplified/issues/56) | Today the receiver trusts `senderBpn` in the payload. |
| [Single sign-on (#57)](https://github.com/pedrobtmartins/catena-x-simplified/issues/57) | Administration with the company's identity provider instead of one local account. |
| [Python 3.13 (#58)](https://github.com/pedrobtmartins/catena-x-simplified/issues/58) | The private CA test fails under the stricter X.509 checks, and CI only runs 3.12. |
| [Web unit tests (#59)](https://github.com/pedrobtmartins/catena-x-simplified/issues/59) | `web/` has no tests yet; CI only builds it. |

## Later

- **A pilot with real partners:** quality alerts and investigations with partners outside the lab, through their production connectors. This waits until a partner is available; until then, notifications are tested in the umbrella lab.

This roadmap is a plan, not a promise. Ideas and questions are welcome as [issues](https://github.com/pedrobtmartins/catena-x-simplified/issues).

"""Consumer-side EDC access shared by partner reads and notification sending.

Wraps the Tractus-X SDK's Saturn ``ConnectorConsumerService``: connector discovery (cached per
connector) and contract negotiation against the company's accepted usage policies. The SDK
compares policies literally; before negotiating, the offers that mean the same as an accepted
policy (``policies.same_policy``) are added in their offered spelling, so partners still on
Jupiter (DSP 0.8, ``cx-policy:``/``odrl:`` terms) match the same accepted policies.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from .policies import describe, offers_of, same_policy
from .ports import DataspaceError

DCT_TYPE_KEY = "'http://purl.org/dc/terms/type'.'@id'"
# The KIT's asset examples use the https form of the Dublin Core namespace; partners publish both.
DCT_TYPE_KEYS = (DCT_TYPE_KEY, "'https://purl.org/dc/terms/type'.'@id'")
EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"
ASSET_ID_KEY = f"{EDC_NAMESPACE}id"
# Jupiter's DSP. Negotiations over it need Jupiter's JSON-LD context: the Saturn one (Catena-X
# 2025-9) does not define the ``cx-policy:`` prefix of their offers, and the provider then sees
# another policy than it offered and terminates the negotiation. Their offers also use ``edc:``
# operands (e.g. ``edc:BusinessPartnerNumber``, ``edc:inForceDate``), so the prefix is declared:
# without it the own EDC rejects the request (HTTP 400).
DSP_0_8 = "dataspace-protocol-http"
JUPITER_NEGOTIATION_CONTEXT = [
    "https://w3id.org/tractusx/policy/v1.0.0",
    "http://www.w3.org/ns/odrl.jsonld",
    {"@vocab": "https://w3id.org/edc/v0.0.1/ns/", "edc": "https://w3id.org/edc/v0.0.1/ns/"},
]


@dataclass(frozen=True)
class Partner:
    """A partner as the dataspace layer sees it: its BPNL and the DSP endpoint of its
    connector.
    """

    bpnl: str
    connector_address: str  # the partner's DSP endpoint, e.g. https://edc.partner/api/v1/dsp


class ConnectorConsumer(Protocol):
    """The subset of the Tractus-X SDK's Saturn ``ConnectorConsumerService`` used here."""

    def get_discovery_info(
        self, bpnl: str, counter_party_address: str = ...
    ) -> tuple[str, str, str]: ...

    def get_catalog_with_filter(
        self,
        counter_party_id: str,
        counter_party_address: str,
        filter_expression: list[dict],
        timeout: int | None = ...,
        protocol: str = ...,
    ) -> dict: ...

    def do_dsp(
        self,
        counter_party_id: str,
        counter_party_address: str,
        filter_expression: list[dict],
        policies: list | None,
        protocol: str = ...,
    ) -> tuple[str, str]: ...

    def get_transfer_id(
        self,
        counter_party_id: str,
        counter_party_address: str,
        filter_expression: list[dict],
        policies: list | None = ...,
        protocol: str = ...,
    ) -> str: ...

    # The EDR controller of the own EDC (``refresh(oid=...)``).
    edrs: Any


def equals(key: str, value: str) -> dict:
    """An EDC catalog filter: ``key`` equals ``value``."""
    return {"operandLeft": key, "operator": "=", "operandRight": value}


def datasets(catalog: Any) -> Iterator[dict]:
    """Every dataset of a (possibly nested or federated) DCAT catalog."""
    if isinstance(catalog, list):
        for item in catalog:
            yield from datasets(item)
    elif isinstance(catalog, dict):
        for key, value in catalog.items():
            name = key.split(":")[-1].split("#")[-1]
            if name == "dataset":
                yield from (d for d in (value if isinstance(value, list) else [value]) if d)
            elif name == "catalog":
                yield from datasets(value)


def _with_other_dct_namespace(filter_expression: list[dict]) -> list[dict] | None:
    """The filter with the other Dublin Core namespace for ``dct:type``, if it has one."""
    swapped = [
        {**f, "operandLeft": DCT_TYPE_KEYS[1 - DCT_TYPE_KEYS.index(f["operandLeft"])]}
        if f.get("operandLeft") in DCT_TYPE_KEYS
        else f
        for f in filter_expression
    ]
    return swapped if swapped != filter_expression else None


@dataclass(frozen=True)
class OfferedPolicy:
    """A usage policy a connector offers for one of its assets."""

    asset_id: str
    policy: dict  # the ODRL body, without the offer's @id/@type
    accepted: bool


class EdcNegotiator:
    """Catalog requests and contract negotiations with partners' connectors through the own
    EDC (Tractus-X SDK).

    Resolves each connector's protocol (DSP 2025-1, or 0.8 for Jupiter partners) once, only
    negotiates for offers whose usage policy the company accepts (compared by meaning,
    whichever way the policy is spelled), and lets the SDK reuse negotiations and EDRs.
    """

    def __init__(self, consumer: ConnectorConsumer, accepted_policies: list[dict] | None):
        """``accepted_policies``: the usage policies the company accepts (bodies without
        ``@id``/``@type``, as offered in the partner's catalog); ``None`` accepts any policy and
        is meant for development only."""
        self.consumer = consumer
        self._policies = accepted_policies
        self._discovery: dict[tuple[str, str], tuple[str, str, str]] = {}

    def counter_party(self, bpnl: str, address: str) -> tuple[str, str, str]:
        """(versioned DSP address, counter-party ID, protocol) for a connector, cached."""
        key = (bpnl, address)
        if key not in self._discovery:
            try:
                self._discovery[key] = self.consumer.get_discovery_info(
                    bpnl=bpnl, counter_party_address=address
                )
            except Exception as exc:
                raise DataspaceError(
                    f"connector discovery for {bpnl} at {address} failed: {exc}"
                ) from exc
        return self._discovery[key]

    def accepts(self, policy: dict) -> bool:
        """Whether the company accepts this offered policy (compared by meaning)."""
        if self._policies is None:
            return True
        return any(same_policy(policy, p) for p in self._policies)

    def offered_policies(
        self, bpnl: str, address: str, filter_expression: list[dict]
    ) -> list[OfferedPolicy]:
        """The usage policies the connector offers for the matching assets, each once per
        asset, and whether the company accepts it. Only reads the catalog."""
        found = list(datasets(self.catalog(bpnl, address, filter_expression)))
        other = _with_other_dct_namespace(filter_expression)
        if not found and other:
            found = list(datasets(self.catalog(bpnl, address, other)))
        result: list[OfferedPolicy] = []
        for dataset in found:
            asset_id = dataset.get("@id") or dataset.get("id") or ""
            for offer in offers_of(dataset):
                body = {k: v for k, v in offer.items() if k not in ("@id", "@type")}
                if any(o.asset_id == asset_id and same_policy(o.policy, body) for o in result):
                    continue
                result.append(OfferedPolicy(str(asset_id), body, self.accepts(body)))
        return result

    def catalog(self, bpnl: str, address: str, filter_expression: list[dict]) -> dict:
        """The partner connector's catalog, filtered (e.g. by asset id or ``dct:type``)."""
        dsp_address, counter_party_id, protocol = self.counter_party(bpnl, address)
        try:
            return self.consumer.get_catalog_with_filter(
                counter_party_id=counter_party_id,
                counter_party_address=dsp_address,
                filter_expression=filter_expression,
                protocol=protocol,
            )
        except Exception as exc:
            raise DataspaceError(f"catalog request to {bpnl} failed: {exc}") from exc

    def negotiate(
        self, bpnl: str, address: str, filter_expression: list[dict], refresh: bool = False
    ) -> tuple[str, str]:
        """Negotiate (or reuse) access to the matching asset; returns (endpoint, token).

        ``refresh``: the partner refused the token it had, so the own EDC renews the EDR of the
        same transfer (the SDK still holds its ID) instead of handing back the one it has, which
        it only renews once it has expired by its own clock."""
        if self._policies is not None and not self._policies:
            raise DataspaceError("no accepted usage policies configured (CXS_ACCEPTED_POLICIES)")
        dsp_address, counter_party_id, protocol = self.counter_party(bpnl, address)
        policies, offered, matched = self._policies, [], True
        if policies is not None:
            filter_expression, policies, offered, matched = self._equivalent_offers(
                bpnl, address, filter_expression
            )
        jupiter = (
            {"negotiation_context": JUPITER_NEGOTIATION_CONTEXT} if protocol == DSP_0_8 else {}
        )
        request = {
            "counter_party_id": counter_party_id,
            "counter_party_address": dsp_address,
            "filter_expression": filter_expression,
            "policies": policies,
            "protocol": protocol,
            **jupiter,
        }
        try:
            if refresh:
                endpoint, token = self._refreshed(self.consumer.get_transfer_id(**request))
            else:
                endpoint, token = self.consumer.do_dsp(**request)
        except DataspaceError:
            raise
        except Exception as exc:
            message = f"negotiation with {bpnl} failed: {exc}"
            if offered and not matched:
                accepted = "; ".join(describe(p) for p in self._policies or [])
                message += f" Offered: {'; '.join(offered)}. Accepted: {accepted}."
            raise DataspaceError(message) from exc
        if not endpoint or not token:
            raise DataspaceError(f"negotiation with {bpnl} returned no endpoint or token")
        return endpoint, token

    def _refreshed(self, transfer_id: str) -> tuple[str, str]:
        """(endpoint, token) of a renewed EDR for the transfer."""
        failed = f"renewing the EDR of transfer {transfer_id} failed"
        try:
            response = self.consumer.edrs.refresh(
                oid=transfer_id, verify=getattr(self.consumer, "verify_ssl", True)
            )
        except Exception as exc:
            raise DataspaceError(f"{failed}: {exc}") from exc
        if response is None or not response.ok:
            raise DataspaceError(f"{failed}: HTTP {getattr(response, 'status_code', None)}")
        address = response.json()
        return _edr_field(address, "endpoint"), _edr_field(address, "authorization")

    def _equivalent_offers(
        self, bpnl: str, address: str, filter_expression: list[dict]
    ) -> tuple[list[dict], list[dict], list[str], bool]:
        """(filter, accepted policies plus the offers equivalent to one of them, every offer
        described, whether any offer is accepted). Uses the other Dublin Core namespace for
        ``dct:type`` if only that one finds the asset; a catalog that cannot be read changes
        nothing."""
        policies = list(self._policies or [])
        found: list[dict] = []
        try:
            found = list(datasets(self.catalog(bpnl, address, filter_expression)))
            other = _with_other_dct_namespace(filter_expression)
            if not found and other:
                found = list(datasets(self.catalog(bpnl, address, other)))
                if found:
                    filter_expression = other
        except DataspaceError:
            pass
        offered: list[str] = []
        matched = False
        for dataset in found:
            for offer in offers_of(dataset):
                body = {k: v for k, v in offer.items() if k not in ("@id", "@type")}
                offered.append(describe(body))
                if any(same_policy(body, p) for p in self._policies or []):
                    matched = True
                    if body not in policies:
                        policies.append(body)
        return filter_expression, policies, list(dict.fromkeys(offered)), matched


def _edr_field(address: dict, name: str) -> str:
    """A field of an EDR data address, plain or in the EDC namespace."""
    return str(address.get(name) or address.get(f"{EDC_NAMESPACE}{name}") or "")

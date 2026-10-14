"""Consumer-side EDC access shared by partner reads and notification sending.

Wraps the Tractus-X SDK's Saturn ``ConnectorConsumerService``: connector discovery (cached per
connector) and contract negotiation against the company's accepted usage policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .ports import DataspaceError

DCT_TYPE_KEY = "'http://purl.org/dc/terms/type'.'@id'"
# The KIT's asset examples use the https form of the Dublin Core namespace; partners publish both.
DCT_TYPE_KEYS = (DCT_TYPE_KEY, "'https://purl.org/dc/terms/type'.'@id'")
ASSET_ID_KEY = "https://w3id.org/edc/v0.0.1/ns/id"


@dataclass(frozen=True)
class Partner:
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


def equals(key: str, value: str) -> dict:
    return {"operandLeft": key, "operator": "=", "operandRight": value}


class EdcNegotiator:
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

    def catalog(self, bpnl: str, address: str, filter_expression: list[dict]) -> dict:
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

    def negotiate(self, bpnl: str, address: str, filter_expression: list[dict]) -> tuple[str, str]:
        """Negotiate (or reuse) access to the matching asset; returns (endpoint, token)."""
        if self._policies is not None and not self._policies:
            raise DataspaceError("no accepted usage policies configured (CXS_ACCEPTED_POLICIES)")
        dsp_address, counter_party_id, protocol = self.counter_party(bpnl, address)
        try:
            endpoint, token = self.consumer.do_dsp(
                counter_party_id=counter_party_id,
                counter_party_address=dsp_address,
                filter_expression=filter_expression,
                policies=self._policies,
                protocol=protocol,
            )
        except Exception as exc:
            raise DataspaceError(f"negotiation with {bpnl} failed: {exc}") from exc
        if not endpoint or not token:
            raise DataspaceError(f"negotiation with {bpnl} returned no endpoint or token")
        return endpoint, token
